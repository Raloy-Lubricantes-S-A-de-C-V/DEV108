import contextvars
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone


N8N_MONITOR_SESSION_KEY = 'n8n_monitor_events'
N8N_MONITOR_MAX_EVENTS = int(getattr(settings, 'N8N_MONITOR_MAX_EVENTS', 80))
N8N_MONITOR_HOST = 'n8n.raloy.com.mx'
# Solo el admin maestro puede ver el monitor flotante de n8n.
N8N_MONITOR_ADMIN_EMAIL = 'pjimenezb@raloy.com.mx'
N8N_FAILURE_STATUSES = {
    'error',
    'failed',
    'failure',
    'fail',
    'n8n_error',
    'partial',
    'rejected',
    'cancelled',
}
N8N_ERROR_TEXT_MARKERS = (
    'problem in node',
    'forbidden',
    'not found',
    'could not be found',
    'cannotaddparent',
    'cannot add parent',
    'increasing the number of parents',
    'bad request',
    'unauthorized',
    'permission denied',
    'quota exceeded',
    'timed out',
    'timeout',
    'network error',
    'nodeapierror',
    'http error',
)
N8N_BLOCKING_WEBHOOK_PATHS = {
    '/webhook/preparar-directorio2',
    '/webhook/subir-pdf-final',
    '/webhook/request-signature',
    '/webhook/descargar-pdf-drive',
    '/webhook/subir-pdf-usuario',
    '/webhook/analizar-plantilla',
}

_current_request = contextvars.ContextVar('n8n_monitor_current_request', default=None)


def set_current_request(request):
    return _current_request.set(request)


def reset_current_request(token):
    _current_request.reset(token)


def get_current_request():
    return _current_request.get()


def is_n8n_url(url):
    try:
        parsed = urlparse(str(url or ''))
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and parsed.netloc.lower() == N8N_MONITOR_HOST


def webhook_label(url):
    try:
        parsed = urlparse(str(url or ''))
    except ValueError:
        return str(url or '')
    return parsed.path or str(url or '')


def _webhook_path(url):
    try:
        return urlparse(str(url or '')).path
    except ValueError:
        return ''


def event_decision(webhook_url, ok):
    if ok:
        return 'continue', 'OK'
    if _webhook_path(webhook_url) in N8N_BLOCKING_WEBHOOK_PATHS:
        return 'stop', 'FALLA - PARAR'
    return 'continue_with_warning', 'FALLA - CONTINUAR'


def session_can_view_monitor(request):
    try:
        admin_email = str(request.session.get('admin_email') or '').strip().lower()
        return admin_email == N8N_MONITOR_ADMIN_EMAIL
    except Exception:
        return False


def get_session_events(request):
    try:
        events = request.session.get(N8N_MONITOR_SESSION_KEY, [])
    except Exception:
        return []
    return events if isinstance(events, list) else []


def _truthy_error_value(value):
    if value in (None, False, '', [], {}):
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ('false', 'none', 'null', 'ok', 'success')
    return True


def _looks_like_error_text(value):
    text = str(value or '').strip().lower()
    if not text:
        return False
    return any(marker in text for marker in N8N_ERROR_TEXT_MARKERS)


def _status_code_is_error(value):
    try:
        return int(value) >= 400
    except (TypeError, ValueError):
        return False


def _iter_nested(value):
    if isinstance(value, dict):
        for child in value.values():
            yield child
    elif isinstance(value, list):
        for child in value:
            yield child


def _find_n8n_error(value, depth=0):
    if depth > 8:
        return ''

    if isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in ('error', 'errors', 'error_message', 'errormessage') and _truthy_error_value(item):
                return _compact_detail(item)
            if key_lower in ('status', 'state', 'result'):
                status = str(item or '').strip().lower()
                if status in N8N_FAILURE_STATUSES:
                    return _compact_detail(value.get('message') or value.get('detail') or item)
            if key_lower in ('ok', 'success') and item is False:
                return _compact_detail(value.get('message') or value.get('detail') or key)
            if key_lower in ('code', 'statuscode', 'status_code', 'http_status') and _status_code_is_error(item):
                return _compact_detail(value.get('message') or value.get('detail') or f'HTTP {item}')
            if key_lower in ('message', 'detail', 'fullmessage', 'full_message', 'description') and _looks_like_error_text(item):
                return _compact_detail(item)

        for child in _iter_nested(value):
            found = _find_n8n_error(child, depth + 1)
            if found:
                return found

    elif isinstance(value, list):
        for child in value:
            found = _find_n8n_error(child, depth + 1)
            if found:
                return found

    elif isinstance(value, str) and _looks_like_error_text(value):
        return _compact_detail(value)

    return ''


def _compact_detail(value):
    if isinstance(value, dict):
        for key in ('message', 'error', 'detail', 'description', 'reason'):
            item = value.get(key)
            if item:
                return _compact_detail(item)
    if isinstance(value, list):
        return _compact_detail(value[0]) if value else ''
    return str(value or '')[:240]


def _response_payload(response):
    try:
        return response.json()
    except Exception:
        return None


def _response_detail(response):
    data = _response_payload(response)
    found = _find_n8n_error(data)
    if found:
        return found

    if not (200 <= getattr(response, 'status_code', 0) < 300):
        try:
            return str(getattr(response, 'text', '') or '')[:240]
        except Exception:
            return ''
    return ''


def response_error_detail(response):
    return _response_detail(response)


def response_was_successful(response):
    ok = 200 <= getattr(response, 'status_code', 0) < 300
    if not ok:
        return False

    content_type = str(getattr(response, 'headers', {}).get('content-type', '')).lower()
    if content_type and 'application/json' not in content_type and 'text/json' not in content_type:
        return True

    data = _response_payload(response)
    return not bool(_find_n8n_error(data))


def record_n8n_event(request, webhook_url, ok, method='POST', http_status=None, error='', source='backend'):
    if request is None or not is_n8n_url(webhook_url):
        return None

    now = timezone.localtime(timezone.now())
    decision, decision_label = event_decision(webhook_url, bool(ok))
    event = {
        'id': uuid.uuid4().hex,
        'webhook_url': str(webhook_url or ''),
        'webhook_label': webhook_label(webhook_url),
        'method': str(method or 'POST').upper(),
        'ok': bool(ok),
        'decision': decision,
        'decision_label': decision_label,
        'http_status': http_status,
        'error': str(error or '')[:240],
        'source': str(source or 'backend')[:40],
        'timestamp': now.isoformat(),
        'timestamp_label': now.strftime('%Y-%m-%d %H:%M:%S'),
    }

    try:
        events = get_session_events(request)
        events = [*events, event][-N8N_MONITOR_MAX_EVENTS:]
        request.session[N8N_MONITOR_SESSION_KEY] = events
        request.session.modified = True
    except Exception as exc:
        print(f"No se pudo registrar evento n8n en sesion: {exc}")
        return None
    return event


def record_response(request, webhook_url, response, method='POST', source='backend'):
    if request is None or not is_n8n_url(webhook_url):
        return None
    ok = response_was_successful(response)
    return record_n8n_event(
        request,
        webhook_url,
        ok,
        method=method,
        http_status=getattr(response, 'status_code', None),
        error='' if ok else _response_detail(response),
        source=source,
    )


def record_exception(request, webhook_url, exc, method='POST', source='backend'):
    return record_n8n_event(
        request,
        webhook_url,
        False,
        method=method,
        http_status=None,
        error=str(exc),
        source=source,
    )


def record_client_event(request, data):
    webhook_url = str(data.get('webhook_url') or data.get('url') or '').strip()
    if not is_n8n_url(webhook_url):
        return None
    error = _find_n8n_error(data.get('response_body'))
    ok = bool(data.get('ok')) and not error
    return record_n8n_event(
        request,
        webhook_url,
        ok,
        method=str(data.get('method') or 'POST').upper(),
        http_status=data.get('http_status') or data.get('status'),
        error=error or data.get('error') or '',
        source='frontend',
    )

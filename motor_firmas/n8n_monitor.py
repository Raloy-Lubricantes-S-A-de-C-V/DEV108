import contextvars
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone


N8N_MONITOR_SESSION_KEY = 'n8n_monitor_events'
N8N_MONITOR_MAX_EVENTS = int(getattr(settings, 'N8N_MONITOR_MAX_EVENTS', 80))
N8N_MONITOR_HOST = 'n8n.raloy.com.mx'

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


def session_can_view_monitor(request):
    try:
        return bool(request.session.get('owner_email') or request.session.get('admin_email'))
    except Exception:
        return False


def get_session_events(request):
    try:
        events = request.session.get(N8N_MONITOR_SESSION_KEY, [])
    except Exception:
        return []
    return events if isinstance(events, list) else []


def _response_detail(response):
    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, list) and data:
        data = data[0]

    if isinstance(data, dict):
        for key in ('error', 'message', 'detail', 'msg'):
            value = data.get(key)
            if value:
                return str(value)[:240]

    if not (200 <= getattr(response, 'status_code', 0) < 300):
        try:
            return str(getattr(response, 'text', '') or '')[:240]
        except Exception:
            return ''
    return ''


def response_was_successful(response):
    ok = 200 <= getattr(response, 'status_code', 0) < 300
    if not ok:
        return False

    content_type = str(getattr(response, 'headers', {}).get('content-type', '')).lower()
    if content_type and 'application/json' not in content_type and 'text/json' not in content_type:
        return True

    try:
        data = response.json()
    except Exception:
        return True

    if isinstance(data, list) and data:
        data = data[0]

    if not isinstance(data, dict):
        return True

    status = str(data.get('status') or '').strip().lower()
    if status in ('error', 'failed', 'failure', 'n8n_error'):
        return False
    return not bool(data.get('error'))


def record_n8n_event(request, webhook_url, ok, method='POST', http_status=None, error='', source='backend'):
    if request is None or not is_n8n_url(webhook_url):
        return None

    now = timezone.localtime(timezone.now())
    event = {
        'id': uuid.uuid4().hex,
        'webhook_url': str(webhook_url or ''),
        'webhook_label': webhook_label(webhook_url),
        'method': str(method or 'POST').upper(),
        'ok': bool(ok),
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
    return record_n8n_event(
        request,
        webhook_url,
        bool(data.get('ok')),
        method=str(data.get('method') or 'POST').upper(),
        http_status=data.get('http_status') or data.get('status'),
        error=data.get('error') or '',
        source='frontend',
    )

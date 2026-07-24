import os
import json
import requests
import traceback
import re
import uuid
import shutil
import base64
import shlex
import hashlib
from datetime import datetime, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from urllib.parse import quote, parse_qs, urlparse
from django.conf import settings
from django.core import signing
from django.http import JsonResponse, HttpResponse, Http404, FileResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from .models import ProcesoFirma, DirectorioFirmas, OTPLogin, AdministradorPortal, PlantillaFormulario, CarpetaDominio, \
    DocumentoPDFUsuario, AreaFirmex, ConfiguracionFirmex, ConfiguracionDriveResguardo, EtiquetaDocumento
from .n8n_monitor import (
    get_current_request,
    get_session_events,
    record_client_event,
    record_exception,
    record_response,
    response_error_detail,
    response_was_successful,
    session_can_view_monitor,
)
from .utils import (
    estampar_firma_en_pdf,
    estampar_variables_en_pdf,
    estampar_campos_posicionados_en_pdf,
    crear_notificacion_firma,
    reubicar_firmas_en_pdf,
)

# WEBHOOKS DE N8N
N8N_WEBHOOK_NOTIFICAR_CORREO = "https://n8n.raloy.com.mx/webhook/enviar-correo-firma"
N8N_WEBHOOK_FINALIZAR_PROCESO = "https://n8n.raloy.com.mx/webhook/subir-pdf-final"
N8N_WEBHOOK_NOTIFICAR_OWNER = "https://n8n.raloy.com.mx/webhook/notificar-owner"
N8N_WEBHOOK_RECUPERAR_PIN = "https://n8n.raloy.com.mx/webhook/recuperar-pin-firma"
N8N_WEBHOOK_ENVIAR_OTP = "https://n8n.raloy.com.mx/webhook/enviar-otp-portal"
N8N_WEBHOOK_INVITAR_REGISTRO = "https://n8n.raloy.com.mx/webhook/invitar-registro-firma"
N8N_WEBHOOK_ANALIZAR_PLANTILLA = "https://n8n.raloy.com.mx/webhook/analizar-plantilla"
N8N_WEBHOOK_PREPARAR_DIR = "https://n8n.raloy.com.mx/webhook/preparar-directorio2"
N8N_WEBHOOK_SUBIR_PDF_USUARIO = "https://n8n.raloy.com.mx/webhook/subir-pdf-usuario"
N8N_WEBHOOK_REQUEST_SIGNATURE = "https://n8n.raloy.com.mx/webhook/request-signature"
N8N_WEBHOOK_DESCARGAR_PDF_DRIVE = "https://n8n.raloy.com.mx/webhook/descargar-pdf-drive"
N8N_WEBHOOK_ENVIAR_QR = "https://n8n.raloy.com.mx/webhook/enviar-qr-trazabilidad"
N8N_WEBHOOK_NOTIFICAR_FIRMX = "https://n8n.raloy.com.mx/webhook/notificar-firmx"

PUBLIC_BASE_URL = "https://dsign.raloy.com.mx"
QR_TRAZABILIDAD_SALT = "motor_firmas.trazabilidad_qr"
QR_TRAZABILIDAD_MAX_AGE_SECONDS = getattr(settings, "QR_TRAZABILIDAD_MAX_AGE_SECONDS", 60 * 60 * 24 * 30)
BRAND_DEFAULT_DOMAIN = "raloy.com.mx"
BRAND_DEFAULT_COLOR = "#162839"
BRAND_DEFAULT_LOGO_URL = "/static/motor_firmas/img/raloy-logo.svg"
BRAND_LEGACY_INVERTED_LOGO_URL = "/static/motor_firmas/img/raloy-logo-inverted.svg"
BRAND_DEFAULT_NAME = "Raloy Lubricantes"
BRAND_LOGO_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
FIRMX_TERMINAL_STATUSES = {'COMPLETED', 'CANCELLED'}
PORTAL_LABEL_ALL_VALUE = 'all'
PORTAL_LABEL_UNTAGGED_VALUE = 'sin_etiqueta'
PORTAL_LABEL_RESERVED_NAMES = {'all', 'todo', 'sin etiqueta', 'sin_etiqueta'}
PORTAL_LABEL_PATH_SEPARATOR = ' / '
DRIVE_STORAGE_POLICY = 'formatos_pdfs_v1'
DEFAULT_DRIVE_ARCHIVE_ROOT_FOLDER_ID = '1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0'
DEFAULT_DRIVE_FORMATOS_FOLDER_ID = '1QAFVrdUC76S_xmwjgqxIyzk0tUMoLmk9'
DEFAULT_DRIVE_PDFS_FOLDER_ID = '1uiTpBfXLjfOedTfdf7xdlQKEsv91YhyA'
DEFAULT_DRIVE_API_PDFS_FOLDER_ID = '1GlACvY3TOOq6k3nZ7YNdRG2AqGvlUOvP'
DEFAULT_DRIVE_CONTRATOS_BASE_FOLDER_ID = '1PEBBy7nhpqcgL4VG7bAfg2MRKq3vHwOB'
DRIVE_ARCHIVE_ROOT_FOLDER_ID = getattr(settings, 'DRIVE_ARCHIVE_ROOT_FOLDER_ID', DEFAULT_DRIVE_ARCHIVE_ROOT_FOLDER_ID)
DRIVE_FORMATOS_FOLDER_ID = getattr(settings, 'DRIVE_FORMATOS_FOLDER_ID', DEFAULT_DRIVE_FORMATOS_FOLDER_ID)
DRIVE_FORMATOS_FOLDER_NAME = getattr(settings, 'DRIVE_FORMATOS_FOLDER_NAME', 'Formatos')
DRIVE_PDFS_FOLDER_NAME = getattr(settings, 'DRIVE_PDFS_FOLDER_NAME', 'PDFs')
DRIVE_PDFS_FOLDER_ID = getattr(settings, 'DRIVE_PDFS_FOLDER_ID', DEFAULT_DRIVE_PDFS_FOLDER_ID)
DRIVE_API_PDFS_FOLDER_ID = getattr(settings, 'DRIVE_API_PDFS_FOLDER_ID', DEFAULT_DRIVE_API_PDFS_FOLDER_ID)
DRIVE_CONTRATOS_BASE_FOLDER_ID = getattr(settings, 'DRIVE_CONTRATOS_BASE_FOLDER_ID', DEFAULT_DRIVE_CONTRATOS_BASE_FOLDER_ID)
DRIVE_CONTRATOS_BASE_FOLDER_NAME = getattr(settings, 'DRIVE_CONTRATOS_BASE_FOLDER_NAME', 'Contratos_Base')
DRIVE_CONTRATOS_BASE_FOLDER_ID = getattr(settings, 'DRIVE_CONTRATOS_BASE_FOLDER_ID', DEFAULT_DRIVE_CONTRATOS_BASE_FOLDER_ID)
PDF_UPLOAD_RETRY_COOLDOWN_SECONDS = int(getattr(settings, 'PDF_UPLOAD_RETRY_COOLDOWN_SECONDS', 90))
PDF_UPLOAD_N8N_TIMEOUT_SECONDS = int(getattr(settings, 'PDF_UPLOAD_N8N_TIMEOUT_SECONDS', 15))
FIRMA_LIBRE_DUPLICATE_GUARD_SECONDS = int(getattr(settings, 'FIRMA_LIBRE_DUPLICATE_GUARD_SECONDS', 10 * 60))
PDF_LEGACY_DUPLICATE_WINDOW_SECONDS = int(getattr(settings, 'PDF_LEGACY_DUPLICATE_WINDOW_SECONDS', 2 * 60 * 60))

_MONGO_CLIENT = None


def tracked_post(url, *args, **kwargs):
    request = get_current_request()
    try:
        response = requests.post(url, *args, **kwargs)
    except Exception as exc:
        record_exception(request, url, exc, method='POST', source='backend')
        raise

    record_response(request, url, response, method='POST', source='backend')
    response.n8n_monitor_ok = response_was_successful(response)
    response.n8n_monitor_error = '' if response.n8n_monitor_ok else response_error_detail(response)
    return response


def _n8n_response_error(response):
    if response_was_successful(response):
        return ''
    return response_error_detail(response) or f"HTTP {getattr(response, 'status_code', '')}".strip()


def _n8n_error_respond_webhook_sin_usar(error):
    text = str(error or '').strip().lower()
    return 'unused respond to webhook node found in the workflow' in text


def _pausar_subida_pdf_usuario_por_n8n(error, detail='', document_id='', owner_email=''):
    message = str(error or '').strip() or 'N8N no confirmo la subida del PDF a Google Drive.'
    detail = str(detail or '').strip()
    request = get_current_request()
    event = record_exception(
        request,
        N8N_WEBHOOK_SUBIR_PDF_USUARIO,
        RuntimeError(detail or message),
        method='POST',
        source='backend',
    )
    _registrar_evento_global_n8n_monitor(event, request, owner_email=owner_email)
    return JsonResponse({
        'status': 'paused',
        'source': 'n8n',
        'n8n_paused': True,
        'id': str(document_id or ''),
        'error': message,
        'detail': detail,
        'admin_notice': 'El proceso quedo pausado. Revisa el monitor n8n del administrador; debe aparecer subir-pdf-usuario como FALLA - PARAR.',
    }, status=502)


def _registrar_advertencia_finalizacion_n8n(proceso, n8n_error):
    summary_data = _json_or_default(getattr(proceso, 'summary_data', {}) or {}, {})
    warning = {
        'type': 'unused_respond_to_webhook',
        'webhook': 'subir-pdf-final',
        'message': str(n8n_error or '')[:500],
        'created_at': _datetime_for_mongo().isoformat(),
    }
    warnings = _json_or_default(summary_data.get('n8n_warnings', []), [])
    warnings.append(warning)
    summary_data['n8n_warnings'] = warnings[-20:]
    summary_data['n8n_finalizar_pdf_warning'] = warning
    _mongo_update_document(ProcesoFirma, proceso, {'summary_data': summary_data})
    return warning


def _default_json_value(default):
    if isinstance(default, dict):
        return {}
    if isinstance(default, list):
        return []
    return default


def _json_or_default(value, default):
    parsed = value
    if parsed in (None, ''):
        return _default_json_value(default)

    while isinstance(parsed, str):
        try:
            next_value = json.loads(parsed)
        except (TypeError, ValueError):
            return _default_json_value(default)
        if next_value == parsed:
            break
        parsed = next_value

    if isinstance(default, dict):
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(default, list):
        return parsed if isinstance(parsed, list) else []
    return parsed


def _normalizar_firmantes(firmantes):
    firmantes = _json_or_default(firmantes, [])
    for f in firmantes:
        if isinstance(f, dict):
            if 'nombre' in f:
                f['nombre'] = str(f['nombre'] or '').strip().upper()
            if 'email' in f:
                f['email'] = str(f['email'] or '').strip().lower()
            if 'iniciales' in f:
                f['iniciales'] = str(f['iniciales'] or '').strip().upper()
    return [f for f in firmantes if isinstance(f, dict)]


def _normalizar_email(email):
    return str(email or '').strip().lower()


def _normalizar_dominio(dominio):
    dominio = str(dominio or '').strip().lower()
    return dominio[1:] if dominio.startswith('@') else dominio


def _drive_default_config():
    return {
        'root_folder_id': str(DRIVE_ARCHIVE_ROOT_FOLDER_ID or '').strip() or DEFAULT_DRIVE_ARCHIVE_ROOT_FOLDER_ID,
        'formatos_folder_id': str(DRIVE_FORMATOS_FOLDER_ID or '').strip() or DEFAULT_DRIVE_FORMATOS_FOLDER_ID,
        'pdfs_folder_id': str(DRIVE_PDFS_FOLDER_ID or '').strip() or DEFAULT_DRIVE_PDFS_FOLDER_ID,
        'api_pdfs_folder_id': str(DRIVE_API_PDFS_FOLDER_ID or '').strip() or DEFAULT_DRIVE_API_PDFS_FOLDER_ID,
        'contratos_base_folder_id': str(DRIVE_CONTRATOS_BASE_FOLDER_ID or '').strip() or DEFAULT_DRIVE_CONTRATOS_BASE_FOLDER_ID,
    }


def _drive_configuracion():
    defaults = _drive_default_config()
    try:
        config = _mongo_find_one(ConfiguracionDriveResguardo)
    except Exception as exc:
        print(f"No se pudo cargar ConfiguracionDriveResguardo; usando defaults: {exc}")
        config = None
    if not config:
        return defaults

    return {
        key: str(getattr(config, key, '') or defaults[key]).strip() or defaults[key]
        for key in defaults
    }


def _drive_config_payload():
    config = _drive_configuracion()
    return {
        **config,
        'storage_policy': DRIVE_STORAGE_POLICY,
        'formatos_folder_name': DRIVE_FORMATOS_FOLDER_NAME,
        'pdfs_folder_name': DRIVE_PDFS_FOLDER_NAME,
        'contratos_base_folder_name': DRIVE_CONTRATOS_BASE_FOLDER_NAME,
    }


def _drive_root_folder_id():
    return _drive_configuracion()['root_folder_id']


def _drive_formatos_folder_id():
    return _drive_configuracion()['formatos_folder_id']


def _drive_configured_pdfs_folder_id():
    return _drive_configuracion()['pdfs_folder_id']


def _drive_pdfs_folder_id():
    return _drive_configured_pdfs_folder_id() or _drive_root_folder_id()


def _drive_api_pdfs_folder_id():
    return _drive_configuracion()['api_pdfs_folder_id']


def _drive_contratos_base_folder_id():
    return _drive_configuracion().get('contratos_base_folder_id', '') or DEFAULT_DRIVE_CONTRATOS_BASE_FOLDER_ID


def _drive_storage_payload():
    config = _drive_configuracion()
    return {
        'storage_policy': DRIVE_STORAGE_POLICY,
        'root_folder_id': config['root_folder_id'],
        'formatos_folder_id': config['formatos_folder_id'],
        'pdfs_folder_id': config['pdfs_folder_id'],
        'api_pdfs_folder_id': config['api_pdfs_folder_id'],
        'contratos_base_folder_id': config.get('contratos_base_folder_id', ''),
        'formatos_folder_name': DRIVE_FORMATOS_FOLDER_NAME,
        'pdfs_folder_name': DRIVE_PDFS_FOLDER_NAME,
    }


def _primer_dict_json(value):
    if isinstance(value, list):
        return _primer_dict_json(value[0]) if value else {}
    return value if isinstance(value, dict) else {}


def _preparar_estructura_drive_plantilla(doc_id, root_folder_id=None):
    root_folder_id = str(root_folder_id or _drive_root_folder_id()).strip()
    formatos_folder_id = _drive_formatos_folder_id()
    pdfs_folder_id = _drive_pdfs_folder_id()
    contratos_base_folder_id = _drive_contratos_base_folder_id()
    if not doc_id:
        raise ValueError("Falta el ID del documento de Google Docs.")
    if not root_folder_id:
        raise ValueError("Falta la carpeta raiz de resguardo.")

    payload = {
        **_drive_storage_payload(),
        'root_folder_id': root_folder_id,
        'parent_folder': root_folder_id,
        'doc_id': str(doc_id).strip(),
        'formatos_folder_id': formatos_folder_id,
        'pdfs_folder_id': pdfs_folder_id,
        'contratos_base_folder_id': contratos_base_folder_id,
        'move_doc_to': DRIVE_FORMATOS_FOLDER_NAME,
        'pdf_target_folder': DRIVE_PDFS_FOLDER_NAME,
    }
    response = tracked_post(N8N_WEBHOOK_PREPARAR_DIR, json=payload, timeout=20)
    n8n_error = _n8n_response_error(response)
    if n8n_error:
        raise ValueError(f"Fallo al preparar Drive: {n8n_error}")

    try:
        response_data = _primer_dict_json(response.json())
    except ValueError:
        response_data = {}

    if response_data.get('status') and response_data.get('status') != 'success':
        raise ValueError(response_data.get('error') or 'N8N no pudo preparar la estructura de Drive.')

    formatos_folder_id = (
        _drive_formatos_folder_id()
        or response_data.get('formatos_folder_id')
        or response_data.get('formatos_id')
        or response_data.get('templates_folder_id')
        or response_data.get('drive_folder_id')
        or root_folder_id
    )
    pdfs_folder_id = (
        _drive_pdfs_folder_id()
        or response_data.get('pdfs_folder_id')
        or response_data.get('pdf_folder_id')
        or response_data.get('firmados_folder_id')
        or response_data.get('carpeta_firmados_id')
        or _drive_pdfs_folder_id()
    )
    return {
        'root_folder_id': root_folder_id,
        'formatos_folder_id': str(formatos_folder_id or root_folder_id).strip(),
        'pdfs_folder_id': str(pdfs_folder_id or root_folder_id).strip(),
        'n8n_response': response_data,
    }


def _n8n_storage_data_for_proceso(proceso):
    exec_mode = str(getattr(proceso, 'exec_mode', '') or '').lower()
    folder_id = str(getattr(proceso, 'dir_drive', '') or '').strip()
    if exec_mode == 'form':
        pdfs_folder_id = _drive_configured_pdfs_folder_id() or folder_id or _drive_pdfs_folder_id()
        return {
            **_drive_storage_payload(),
            'folder_id': pdfs_folder_id,
            'pdfs_folder_id': pdfs_folder_id,
        }
    if exec_mode in ('normal', 'api'):
        api_folder_id = folder_id or _drive_api_pdfs_folder_id()
        return {
            **_drive_storage_payload(),
            'folder_id': api_folder_id,
            'pdfs_folder_id': api_folder_id,
        }
    return {'folder_id': folder_id}


def _safe_pdf_filename(filename, fallback='documento.pdf'):
    name = os.path.basename(str(filename or fallback)).strip() or fallback
    name = re.sub(r'[^A-Za-z0-9_.-]+', '_', name)
    if not name.lower().endswith('.pdf'):
        name = f"{name}.pdf"
    return name


def _guardar_pdf_temporal_media(pdf_bytes, filename):
    rel_dir = 'descargas'
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    safe_name = _safe_pdf_filename(filename)
    rel_path = os.path.join(rel_dir, f"{uuid.uuid4().hex}_{safe_name}").replace(os.sep, '/')
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
    with open(abs_path, 'wb') as destination:
        destination.write(pdf_bytes)
    return rel_path, abs_path


def _media_abs_path(path):
    raw_path = str(path or '').strip()
    if not raw_path:
        return ''

    media_root = os.path.abspath(settings.MEDIA_ROOT)
    abs_path = os.path.abspath(raw_path if os.path.isabs(raw_path) else os.path.join(media_root, raw_path))
    try:
        if os.path.commonpath([media_root, abs_path]) != media_root:
            return ''
    except ValueError:
        return ''
    return abs_path


def _eliminar_archivo_media(path):
    abs_path = _media_abs_path(path)
    if not abs_path or not os.path.exists(abs_path):
        return False
    try:
        os.remove(abs_path)
        return True
    except OSError as exc:
        print(f"No se pudo eliminar archivo temporal {abs_path}: {exc}")
        return False


def _media_path_exists(path):
    abs_path = _media_abs_path(path)
    return bool(abs_path and os.path.exists(abs_path))


def _pdf_path_existente_para_firma(path):
    abs_path = _media_abs_path(path)
    if abs_path and os.path.exists(abs_path):
        return abs_path

    raw_path = str(path or '').strip()
    if raw_path and os.path.isabs(raw_path) and os.path.exists(raw_path):
        return os.path.abspath(raw_path)

    return ''


def _media_url_if_exists(path):
    return _media_url_for_path(path) if _media_path_exists(path) else ''


def _proceso_pdf_url(proceso):
    token = getattr(proceso, 'token_acceso', '')
    return f"/documento-pdf/{token}/" if token else ''


def _proceso_pdf_puede_servirse(proceso):
    if _media_path_exists(getattr(proceso, 'pdf_path', '')):
        return True

    summary_data = getattr(proceso, 'summary_data', {}) or {}
    for key in (
        'firmx_file_url',
        'firmx_download_file_url',
        'firmx_certificate_url',
        'firmx_download_certificate_url',
        'firmx_archivo_url',
    ):
        url = summary_data.get(key)
        if isinstance(url, str) and url.strip() and not _url_firmada_expirada(url):
            return True

    for key in ('drive_file_id', 'file_id', 'pdf_file_id', 'source_drive_file_id', 'original_drive_file_id'):
        if summary_data.get(key):
            return True

    return bool(_inferir_pdf_libre_origen(proceso))


def _fecha_documento_label(value):
    value = _datetime_for_compare(value)
    return timezone.localtime(value).strftime('%d/%m/%Y %H:%M') if value else ''


def _documento_firmado_relacion_payload(proceso):
    pdf_url = _proceso_pdf_url(proceso)
    return {
        'token': str(getattr(proceso, 'token_acceso', '') or ''),
        'reference_id': getattr(proceso, 'reference_id', '') or 'Documento firmado',
        'title': getattr(proceso, 'reference_id', '') or 'Documento firmado',
        'owner_email': getattr(proceso, 'owner_email', '') or '',
        'fecha': _fecha_documento_label(getattr(proceso, 'created_at', None)),
        'pdf_url': pdf_url,
        'pdf_available': bool(pdf_url and _proceso_pdf_puede_servirse(proceso)),
    }


def _documentos_firmados_usuario(owner_email):
    owner_email = _normalizar_email(owner_email)
    documentos = _mongo_find(
        ProcesoFirma,
        {'owner_email': owner_email, 'status': 'COMPLETED'},
        [('created_at', -1)],
    )
    return [
        _documento_firmado_relacion_payload(proceso)
        for proceso in documentos
    ]


def _normalizar_dimension_referencia(value, default=0.0, min_value=0.0, max_value=1.0):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))


def _normalizar_referencias_documento(raw_refs, owner_email):
    refs = _json_or_default(raw_refs, [])
    if not isinstance(refs, list):
        return []

    owner_email = _normalizar_email(owner_email)
    referencias = []
    for index, item in enumerate(refs[:20], start=1):
        if not isinstance(item, dict):
            continue

        related_token = str(item.get('related_token') or '').strip()
        if not related_token:
            raise ValueError("Cada referencia debe tener un documento firmado ligado.")

        related_doc = _mongo_find_proceso_by_token(related_token)
        if not related_doc:
            raise ValueError("El documento relacionado no existe.")
        if _normalizar_email(getattr(related_doc, 'owner_email', '')) != owner_email:
            raise ValueError("No puedes relacionar documentos de otro usuario.")
        if str(getattr(related_doc, 'status', '') or '').upper() != 'COMPLETED':
            raise ValueError("Solo puedes relacionar documentos firmados.")
        if not _proceso_pdf_puede_servirse(related_doc):
            raise ValueError("El PDF del documento relacionado no está disponible.")

        try:
            page = max(int(item.get('page') or 1), 1)
        except (TypeError, ValueError):
            page = 1

        x = _normalizar_dimension_referencia(item.get('x'), 0.0)
        y = _normalizar_dimension_referencia(item.get('y'), 0.0)
        width = _normalizar_dimension_referencia(item.get('width'), 0.1, min_value=0.01)
        height = _normalizar_dimension_referencia(item.get('height'), 0.06, min_value=0.01)
        width = min(width, 1.0 - x)
        height = min(height, 1.0 - y)

        snippet_image = str(item.get('snippet_image') or '').strip()
        if snippet_image and not snippet_image.startswith('data:image/png;base64,'):
            snippet_image = ''
        if len(snippet_image) > 500000:
            snippet_image = ''

        referencias.append({
            'id': str(item.get('id') or f'ref-{index}'),
            'page': page,
            'x': x,
            'y': y,
            'width': width,
            'height': height,
            'snippet_image': snippet_image,
            'related_token': str(getattr(related_doc, 'token_acceso', '') or ''),
            'related_reference_id': getattr(related_doc, 'reference_id', '') or 'Documento relacionado',
            'related_title': getattr(related_doc, 'reference_id', '') or 'Documento relacionado',
            'related_owner_email': getattr(related_doc, 'owner_email', '') or '',
            'related_pdf_url': _proceso_pdf_url(related_doc),
        })

    return referencias


def _firmantes_por_email(firmantes):
    emails = {}
    for firmante in _normalizar_firmantes(firmantes):
        email = _normalizar_email(firmante.get('email'))
        if email:
            emails[email] = firmante
    return emails


def _normalizar_key_campo_llenado(value, index):
    key = str(value or '').strip().lower()
    key = re.sub(r'[^a-z0-9_]+', '_', key)
    key = re.sub(r'_+', '_', key).strip('_')
    return key or f'campo_libre_{index}'


def _normalizar_campos_llenado(raw_fields, firmantes):
    fields = _json_or_default(raw_fields, [])
    if not isinstance(fields, list):
        return []

    firmantes_email = _firmantes_por_email(firmantes)
    campos = []
    used_keys = set()
    for index, item in enumerate(fields[:100], start=1):
        if not isinstance(item, dict):
            continue

        signer_email = _normalizar_email(item.get('signer_email') or item.get('email'))
        if not signer_email or signer_email not in firmantes_email:
            raise ValueError("Cada campo de llenado debe estar ligado a un firmante existente.")

        label = str(item.get('label') or '').strip()
        if not label:
            raise ValueError("Cada campo de llenado debe tener un label.")

        key = _normalizar_key_campo_llenado(item.get('key'), index)
        while key in used_keys:
            key = f"{key}_{index}"
        used_keys.add(key)

        try:
            page = max(int(item.get('page') or 1), 1)
        except (TypeError, ValueError):
            page = 1

        x = _normalizar_dimension_referencia(item.get('x'), 0.0)
        y = _normalizar_dimension_referencia(item.get('y'), 0.0)
        width = _normalizar_dimension_referencia(item.get('width'), 0.18, min_value=0.03)
        height = _normalizar_dimension_referencia(item.get('height'), 0.04, min_value=0.015)
        width = min(width, 1.0 - x)
        height = min(height, 1.0 - y)

        firmante = firmantes_email[signer_email]
        campos.append({
            'id': str(item.get('id') or key),
            'key': key,
            'label': label,
            'signer_email': signer_email,
            'signer_name': firmante.get('nombre') or '',
            'page': page,
            'x': x,
            'y': y,
            'width': width,
            'height': height,
            'type': 'text',
        })

    return campos


def _document_variables_desde_campos_llenado(campos):
    return {
        campo['key']: campo['signer_email']
        for campo in campos
        if isinstance(campo, dict) and campo.get('key') and campo.get('signer_email')
    }


def _campos_llenado_libre(summary_data, signer_email='', valores_capturados=None, excluir_capturados=True):
    signer_email = _normalizar_email(signer_email)
    valores_capturados = _json_or_default(valores_capturados or {}, {})
    campos = _json_or_default((summary_data or {}).get('fill_fields', []), [])
    result = []
    for campo in campos:
        if not isinstance(campo, dict):
            continue
        key = str(campo.get('key') or '').strip()
        if not key:
            continue
        if signer_email and _normalizar_email(campo.get('signer_email')) != signer_email:
            continue
        if excluir_capturados and key in valores_capturados:
            continue
        result.append({
            'key': key,
            'label': campo.get('label') or key,
            'options': None,
            'page': campo.get('page'),
            'x': campo.get('x'),
            'y': campo.get('y'),
            'width': campo.get('width'),
            'height': campo.get('height'),
        })
    return result


def _tipo_proceso_relacion(proceso):
    summary_data = getattr(proceso, 'summary_data', {}) or {}
    if summary_data.get('firmx_id'):
        return 'firmx', 'FIRMX'

    exec_mode = str(getattr(proceso, 'exec_mode', '') or '').lower()
    if exec_mode == 'libre':
        return 'libre', 'Libre'
    if exec_mode == 'form':
        return 'formulario', 'Formulario'
    if exec_mode == 'api':
        return 'api', 'API'
    return exec_mode or 'normal', 'Documento'


def _firmx_pdf_url_trazabilidad(proceso):
    summary_data = getattr(proceso, 'summary_data', {}) or {}
    firmx_id = summary_data.get('firmx_id')
    if not firmx_id:
        return ''

    if str(getattr(proceso, 'status', '') or '').upper() != 'CANCELLED':
        success, _ = _firmx_sync_status(firmx_id, force=True)
        if success:
            proceso = _get_proceso_por_token_or_404(getattr(proceso, 'token_acceso', ''))
            summary_data = getattr(proceso, 'summary_data', {}) or {}

    firmx_file_url = str(summary_data.get('firmx_file_url') or '').strip()
    if firmx_file_url and not _url_firmada_expirada(firmx_file_url):
        return firmx_file_url

    return _proceso_pdf_url(proceso) if getattr(proceso, 'token_acceso', '') else ''


def _relaciones_documento_firma(proceso, pdf_url):
    summary_data = _json_or_default(getattr(proceso, 'summary_data', {}) or {}, {})
    referencias = _json_or_default(summary_data.get('document_references', []), [])
    if not referencias:
        return {}

    referencias_context = []
    for ref in referencias:
        if not isinstance(ref, dict):
            continue

        ref_context = dict(ref)
        related_token = str(ref.get('related_token') or '').strip()
        related_pdf_url = ''
        if related_token:
            related_doc = _mongo_find_proceso_by_token(related_token)
            if related_doc:
                related_type, related_type_label = _tipo_proceso_relacion(related_doc)
                if related_type == 'firmx':
                    related_pdf_url = _firmx_pdf_url_trazabilidad(related_doc)
                else:
                    related_pdf_url = _proceso_pdf_url(related_doc)
                ref_context['related_pdf_url'] = related_pdf_url
                ref_context['related_type'] = related_type
                ref_context['related_type_label'] = related_type_label
                ref_context['related_reference_id'] = getattr(related_doc, 'reference_id', '') or ref_context.get('related_reference_id', '')
                ref_context['related_title'] = getattr(related_doc, 'reference_id', '') or ref_context.get('related_title', '')

        if related_pdf_url:
            referencias_context.append(ref_context)

    if not referencias_context:
        return {}

    base_type, base_type_label = _tipo_proceso_relacion(proceso)
    return {
        'base': {
            'reference_id': getattr(proceso, 'reference_id', '') or 'Documento base',
            'title': getattr(proceso, 'reference_id', '') or 'Documento base',
            'pdf_url': pdf_url,
            'type': 'original',
            'document_type': base_type,
            'document_type_label': base_type_label,
        },
        'references': referencias_context,
    }


def _media_url_for_path(path):
    raw_path = str(path or '').replace('\\', '/').strip()
    if not raw_path:
        return ''

    media_root = os.path.abspath(settings.MEDIA_ROOT)
    if os.path.isabs(raw_path):
        abs_path = os.path.abspath(raw_path)
        try:
            rel_path = os.path.relpath(abs_path, media_root)
            if not rel_path.startswith('..') and not os.path.isabs(rel_path):
                return f"{settings.MEDIA_URL}{rel_path.replace(os.sep, '/')}"
        except ValueError:
            pass
        return f"{settings.MEDIA_URL}{os.path.basename(abs_path)}"

    return f"{settings.MEDIA_URL}{raw_path.lstrip('/')}"


def _descargar_pdf_drive_a_media(file_id, filename, owner_email='', folder_id=''):
    file_id = str(file_id or '').strip()
    if not file_id:
        raise ValueError("No hay ID de archivo Drive para descargar.")

    response = tracked_post(
        N8N_WEBHOOK_DESCARGAR_PDF_DRIVE,
        json={
            'file_id': file_id,
            'filename': _safe_pdf_filename(filename),
            'owner_email': owner_email,
            'folder_id': folder_id,
        },
        timeout=30,
    )
    n8n_error = _n8n_response_error(response)
    if n8n_error:
        raise ValueError(f"N8N no pudo descargar el PDF de Drive: {n8n_error}")

    content_type = response.headers.get('content-type', '').lower()
    if 'application/pdf' in content_type:
        return _guardar_pdf_temporal_media(response.content, filename)

    try:
        data = _primer_dict_json(response.json())
    except ValueError:
        data = {}

    pdf_base64 = ''
    for key in ('pdf_base64', 'file_base64', 'document_base64', 'base64'):
        if data.get(key):
            pdf_base64 = str(data.get(key))
            break
    if pdf_base64:
        if ',' in pdf_base64:
            pdf_base64 = pdf_base64.split(',', 1)[1]
        return _guardar_pdf_temporal_media(base64.b64decode(pdf_base64), data.get('filename') or filename)

    download_url = data.get('download_url') or data.get('pdf_url') or data.get('url')
    if download_url:
        download = requests.get(download_url, timeout=30)
        if not 200 <= download.status_code < 300:
            raise ValueError(f"No se pudo bajar el PDF devuelto por N8N ({download.status_code}).")
        return _guardar_pdf_temporal_media(download.content, data.get('filename') or filename)

    raise ValueError("N8N no devolvio PDF, base64 ni URL de descarga.")


def _registrar_pdf_final_drive_id(proceso, response):
    try:
        data = _primer_dict_json(response.json())
    except ValueError:
        return

    candidates = [data]
    for key in ('data', 'file', 'pdf'):
        nested = _primer_dict_json(data.get(key))
        if nested:
            candidates.append(nested)

    drive_file_id = ''
    filename = ''
    web_view_link = ''
    for item in candidates:
        drive_file_id = (
            item.get('drive_file_id')
            or item.get('file_id')
            or item.get('pdf_file_id')
            or item.get('id_archivo')
            or item.get('id')
            or ''
        )
        filename = item.get('filename') or item.get('name') or filename
        web_view_link = item.get('webViewLink') or item.get('web_view_link') or item.get('url') or web_view_link
        if drive_file_id:
            break

    if not drive_file_id:
        return

    summary_data = getattr(proceso, 'summary_data', {}) or {}
    summary_data.update({
        'drive_file_id': drive_file_id,
        'pdf_file_id': drive_file_id,
        'drive_final_file_id': drive_file_id,
    })
    if filename:
        summary_data['drive_final_filename'] = filename
    if web_view_link:
        summary_data['drive_final_webViewLink'] = web_view_link

    updates = {'summary_data': summary_data}
    pdf_path = str(getattr(proceso, 'pdf_path', '') or '')
    if _eliminar_archivo_media(pdf_path):
        summary_data['pdf_local_removed_after_drive_upload'] = True
        summary_data['pdf_local_removed_at'] = _datetime_for_mongo().isoformat()
        updates['pdf_path'] = ''

    _mongo_update_document(ProcesoFirma, proceso, updates)


def _asegurar_pdf_usuario_local(doc, owner_email):
    rel_path = str(getattr(doc, 'archivo_local', '') or '').replace('\\', '/')
    if rel_path:
        abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
        if os.path.exists(abs_path):
            return rel_path, abs_path

    rel_path, abs_path = _descargar_pdf_drive_a_media(
        getattr(doc, 'drive_file_id', ''),
        getattr(doc, 'nombre', 'documento.pdf'),
        owner_email=owner_email,
    )
    _mongo_update_document(DocumentoPDFUsuario, doc, {'archivo_local': rel_path})
    setattr(doc, 'archivo_local', rel_path)
    return rel_path, abs_path


def _proceso_tiene_firmas_capturadas(proceso):
    firmantes = _normalizar_firmantes(getattr(proceso, 'firmantes', []))
    return any(firmante.get('fecha_firma') for firmante in firmantes)


def _inferir_pdf_libre_origen(proceso):
    if str(getattr(proceso, 'exec_mode', '') or '').lower() != 'libre':
        return {}
    if _proceso_tiene_firmas_capturadas(proceso):
        return {}

    owner_email = getattr(proceso, 'owner_email', '') or ''
    proceso_fecha = _datetime_for_compare(getattr(proceso, 'created_at', None))
    if not owner_email or not proceso_fecha:
        return {}

    candidatos = []
    for doc in _mongo_find(DocumentoPDFUsuario, {'owner_email': owner_email, 'deleted': True, 'converted_to_master': True}):
        drive_file_id = str(getattr(doc, 'drive_file_id', '') or '').strip()
        doc_fecha = _datetime_for_compare(getattr(doc, 'created_at', None))
        if not drive_file_id or not doc_fecha:
            continue
        diff_seconds = abs((doc_fecha - proceso_fecha).total_seconds())
        if diff_seconds <= 120:
            candidatos.append((diff_seconds, doc))

    if len(candidatos) != 1:
        return {}

    doc = candidatos[0][1]
    return {
        'source_drive_file_id': str(getattr(doc, 'drive_file_id', '') or '').strip(),
        'source_pdf_filename': getattr(doc, 'nombre', '') or f"{getattr(proceso, 'reference_id', 'documento')}.pdf",
        'source_document_id': str(getattr(doc, 'id_documento', '') or ''),
    }


def _asegurar_proceso_pdf_local(proceso):
    summary_data = getattr(proceso, 'summary_data', {}) or {}
    if summary_data.get('firmx_id'):
        return
    pdf_path = str(getattr(proceso, 'pdf_path', '') or '')
    if pdf_path and os.path.exists(pdf_path):
        return

    drive_file_id = (
        summary_data.get('drive_file_id')
        or summary_data.get('file_id')
        or summary_data.get('pdf_file_id')
    )
    filename = f"{getattr(proceso, 'reference_id', 'documento')}.pdf"

    rehydrating_source = False
    if not drive_file_id:
        # Solo se intenta inferir el origen (emparejamiento por fecha) cuando el proceso
        # aún no está completado; el id de origen guardado en creación sirve en cualquier estado.
        if str(getattr(proceso, 'status', '') or '').upper() != 'COMPLETED':
            inferred_source = _inferir_pdf_libre_origen(proceso)
            if inferred_source:
                summary_data.update({k: v for k, v in inferred_source.items() if v})
        drive_file_id = summary_data.get('source_drive_file_id') or summary_data.get('original_drive_file_id')
        if drive_file_id:
            filename = summary_data.get('source_pdf_filename') or filename
            rehydrating_source = True

    if not drive_file_id:
        return

    rel_path, abs_path = _descargar_pdf_drive_a_media(
        drive_file_id,
        filename,
        owner_email=getattr(proceso, 'owner_email', ''),
        folder_id=getattr(proceso, 'dir_drive', ''),
    )

    target_path = abs_path
    if rehydrating_source:
        original_abs_path = _media_abs_path(pdf_path)
        if original_abs_path:
            os.makedirs(os.path.dirname(original_abs_path), exist_ok=True)
            shutil.move(abs_path, original_abs_path)
            target_path = original_abs_path
            summary_data['pdf_local_rehydrated_from_source'] = True
            summary_data['pdf_local_rehydrated_at'] = _datetime_for_mongo().isoformat()
        else:
            summary_data['pdf_local_temporal'] = rel_path
    else:
        summary_data['pdf_local_temporal'] = rel_path

    _mongo_update_document(ProcesoFirma, proceso, {'pdf_path': target_path})
    setattr(proceso, 'pdf_path', target_path)
    _mongo_update_document(ProcesoFirma, proceso, {'summary_data': summary_data})


def _normalizar_componente_etiqueta_documento(etiqueta):
    etiqueta = str(etiqueta or '').replace('/', ' ')
    etiqueta = re.sub(r'\s+', ' ', etiqueta.strip())
    return etiqueta


def _normalizar_etiqueta_documento(etiqueta):
    partes = [
        _normalizar_componente_etiqueta_documento(parte)
        for parte in str(etiqueta or '').split('/')
    ]
    partes = [parte for parte in partes if parte]
    if not partes:
        return ''
    if len(partes) == 1:
        return partes[0][:80]
    return f"{partes[0]}{PORTAL_LABEL_PATH_SEPARATOR}{partes[1]}"[:80]


def _partes_etiqueta_documento(etiqueta):
    etiqueta = _normalizar_etiqueta_documento(etiqueta)
    if not etiqueta:
        return '', ''
    partes = [parte.strip() for parte in etiqueta.split(PORTAL_LABEL_PATH_SEPARATOR, 1)]
    return partes[0], partes[1] if len(partes) > 1 else ''


def _ruta_etiqueta_documento(parent, child=''):
    parent = _normalizar_componente_etiqueta_documento(parent)
    child = _normalizar_componente_etiqueta_documento(child)
    if not parent:
        return ''
    return _normalizar_etiqueta_documento(f"{parent}/{child}" if child else parent)


def _es_subetiqueta_documento(etiqueta):
    _, child = _partes_etiqueta_documento(etiqueta)
    return bool(child)


def _etiqueta_documento_es_reservada(etiqueta):
    return _normalizar_etiqueta_documento(etiqueta).casefold() in PORTAL_LABEL_RESERVED_NAMES


def _query_sin_etiqueta_documento(owner_email=None):
    query = {
        '$or': [
            {'etiqueta': {'$exists': False}},
            {'etiqueta': None},
            {'etiqueta': ''},
        ]
    }
    if owner_email:
        query['owner_email'] = _normalizar_email(owner_email)
    return query


def _query_etiqueta_documento(owner_email, etiqueta):
    etiqueta = _normalizar_etiqueta_documento(etiqueta)
    parent, child = _partes_etiqueta_documento(etiqueta)
    if child:
        etiqueta_query = {'etiqueta': etiqueta}
    else:
        etiqueta_query = {
            '$or': [
                {'etiqueta': etiqueta},
                {'etiqueta': {'$regex': f"^{re.escape(parent + PORTAL_LABEL_PATH_SEPARATOR)}"}},
            ]
        }

    if owner_email:
        return {'$and': [{'owner_email': _normalizar_email(owner_email)}, etiqueta_query]}
    return etiqueta_query


def _agregar_etiqueta_unica(labels, etiqueta):
    etiqueta = _normalizar_etiqueta_documento(etiqueta)
    if not etiqueta:
        return
    existentes = {str(item).casefold() for item in labels}
    if etiqueta.casefold() not in existentes:
        labels.append(etiqueta)


def _etiquetas_documentos_usuario(owner_email):
    owner_email = _normalizar_email(owner_email)
    labels = []

    for etiqueta in _mongo_find(EtiquetaDocumento, {'owner_email': owner_email}, [('created_at', 1)]):
        _agregar_etiqueta_unica(labels, getattr(etiqueta, 'nombre', ''))

    colaborador = _mongo_find_one(DirectorioFirmas, {'email': owner_email})
    for etiqueta in _json_or_default(getattr(colaborador, 'etiquetas_documentos', []), []) if colaborador else []:
        _agregar_etiqueta_unica(labels, etiqueta)

    try:
        etiquetas_usadas = _mongo_collection(ProcesoFirma).distinct('etiqueta', {'owner_email': owner_email})
    except Exception:
        etiquetas_usadas = []
    for etiqueta in sorted([_normalizar_etiqueta_documento(e) for e in etiquetas_usadas if _normalizar_etiqueta_documento(e)], key=str.casefold):
        _agregar_etiqueta_unica(labels, etiqueta)

    labels_con_padres = []
    for etiqueta in labels:
        parent, child = _partes_etiqueta_documento(etiqueta)
        _agregar_etiqueta_unica(labels_con_padres, parent)
        if child:
            _agregar_etiqueta_unica(labels_con_padres, _ruta_etiqueta_documento(parent, child))
    return labels_con_padres


def _familias_destacadas_documentos_usuario(owner_email, etiquetas_disponibles=None):
    owner_email = _normalizar_email(owner_email)
    disponibles = etiquetas_disponibles if etiquetas_disponibles is not None else _etiquetas_documentos_usuario(owner_email)
    disponibles_por_fold = {item.casefold(): item for item in disponibles}

    colaborador = _mongo_find_one(DirectorioFirmas, {'email': owner_email})
    destacadas_raw = _json_or_default(getattr(colaborador, 'etiquetas_destacadas_documentos', []), []) if colaborador else []
    destacadas = []
    for item in destacadas_raw:
        parent, _ = _partes_etiqueta_documento(item)
        parent_fold = parent.casefold()
        if parent_fold in disponibles_por_fold:
            _agregar_etiqueta_unica(destacadas, disponibles_por_fold[parent_fold])
    return destacadas


def _etiquetas_destacadas_documentos_usuario(owner_email, etiquetas_disponibles=None):
    familias = _familias_destacadas_documentos_usuario(owner_email, etiquetas_disponibles)
    familias_fold = {item.casefold() for item in familias}
    destacadas = []
    for etiqueta in (etiquetas_disponibles if etiquetas_disponibles is not None else _etiquetas_documentos_usuario(owner_email)):
        parent, _ = _partes_etiqueta_documento(etiqueta)
        if parent.casefold() in familias_fold:
            _agregar_etiqueta_unica(destacadas, etiqueta)
    return destacadas


def _guardar_destacadas_documentos_usuario(owner_email, etiquetas):
    owner_email = _normalizar_email(owner_email)
    colaborador = _mongo_find_one(DirectorioFirmas, {'email': owner_email})
    if not colaborador:
        return []

    disponibles = _etiquetas_documentos_usuario(owner_email)
    disponibles_por_fold = {item.casefold(): item for item in disponibles}
    destacadas = []
    for item in etiquetas:
        parent, _ = _partes_etiqueta_documento(item)
        parent_fold = parent.casefold()
        if parent_fold in disponibles_por_fold:
            _agregar_etiqueta_unica(destacadas, disponibles_por_fold[parent_fold])

    _mongo_update_document(DirectorioFirmas, colaborador, {'etiquetas_destacadas_documentos': destacadas})
    return destacadas


def _guardar_etiqueta_documento_usuario(owner_email, etiqueta):
    owner_email = _normalizar_email(owner_email)
    etiqueta = _normalizar_etiqueta_documento(etiqueta)
    parent, child = _partes_etiqueta_documento(etiqueta)
    if not etiqueta:
        raise ValueError("La etiqueta no puede estar vacía.")
    if _etiqueta_documento_es_reservada(etiqueta) or _etiqueta_documento_es_reservada(parent):
        raise ValueError("Ese nombre está reservado para filtros del sistema.")

    existentes = _etiquetas_documentos_usuario(owner_email)
    for existente in existentes:
        if existente.casefold() == etiqueta.casefold():
            etiqueta = existente
            break
    else:
        _mongo_insert_model(EtiquetaDocumento, {
            'owner_email': owner_email,
            'nombre': etiqueta,
            'created_at': _datetime_for_mongo(),
        })

    if child and not _mongo_find_one(EtiquetaDocumento, {'owner_email': owner_email, 'nombre': parent}):
        _mongo_insert_model(EtiquetaDocumento, {
            'owner_email': owner_email,
            'nombre': parent,
            'created_at': _datetime_for_mongo(),
        })

    colaborador = _mongo_find_one(DirectorioFirmas, {'email': owner_email})
    if colaborador:
        labels = _json_or_default(getattr(colaborador, 'etiquetas_documentos', []), [])
        before_count = len(labels)
        if child:
            _agregar_etiqueta_unica(labels, parent)
        _agregar_etiqueta_unica(labels, etiqueta)
        if len(labels) != before_count:
            _mongo_update_document(DirectorioFirmas, colaborador, {'etiquetas_documentos': labels})

    return etiqueta


def _guardar_subetiqueta_documento_usuario(owner_email, etiqueta_padre, subetiqueta):
    owner_email = _normalizar_email(owner_email)
    parent = _resolver_etiqueta_documento_usuario(owner_email, etiqueta_padre)
    parent_name, parent_child = _partes_etiqueta_documento(parent)
    if not parent or parent_child:
        raise ValueError("Selecciona una carpeta principal válida.")

    child = _normalizar_componente_etiqueta_documento(subetiqueta)
    if not child:
        raise ValueError("La subcarpeta no puede estar vacía.")
    etiqueta = _ruta_etiqueta_documento(parent_name, child)
    return _guardar_etiqueta_documento_usuario(owner_email, etiqueta)


def _resolver_etiqueta_documento_usuario(owner_email, etiqueta):
    etiqueta = _normalizar_etiqueta_documento(etiqueta)
    if not etiqueta or _etiqueta_documento_es_reservada(etiqueta):
        return ''
    for existente in _etiquetas_documentos_usuario(owner_email):
        if existente.casefold() == etiqueta.casefold():
            return existente
    return ''


def _actualizar_catalogo_etiquetas_usuario(owner_email, etiqueta_actual, etiqueta_nueva=None):
    return _actualizar_catalogo_etiquetas_por_mapa(
        owner_email,
        {_normalizar_etiqueta_documento(etiqueta_actual): _normalizar_etiqueta_documento(etiqueta_nueva)}
        if etiqueta_nueva else {},
        [_normalizar_etiqueta_documento(etiqueta_actual)] if not etiqueta_nueva else [],
    )


def _actualizar_catalogo_etiquetas_por_mapa(owner_email, reemplazos=None, eliminadas=None):
    owner_email = _normalizar_email(owner_email)
    reemplazos = {
        _normalizar_etiqueta_documento(key): _normalizar_etiqueta_documento(value)
        for key, value in (reemplazos or {}).items()
        if _normalizar_etiqueta_documento(key)
    }
    eliminadas = {
        _normalizar_etiqueta_documento(value).casefold()
        for value in (eliminadas or [])
        if _normalizar_etiqueta_documento(value)
    }
    colaborador = _mongo_find_one(DirectorioFirmas, {'email': owner_email})
    if not colaborador:
        return []

    reemplazos_fold = {key.casefold(): value for key, value in reemplazos.items()}

    def aplicar(items):
        actualizadas = []
        for item in items:
            item_norm = _normalizar_etiqueta_documento(item)
            if not item_norm or item_norm.casefold() in eliminadas:
                continue
            item_norm = reemplazos_fold.get(item_norm.casefold(), item_norm)
            _agregar_etiqueta_unica(actualizadas, item_norm)
        for item_norm in reemplazos.values():
            _agregar_etiqueta_unica(actualizadas, item_norm)
        return actualizadas

    labels = _json_or_default(getattr(colaborador, 'etiquetas_documentos', []), [])
    actualizadas = aplicar(labels)
    destacadas = _json_or_default(getattr(colaborador, 'etiquetas_destacadas_documentos', []), [])
    destacadas_actualizadas = aplicar(destacadas)

    update_doc = {'etiquetas_documentos': actualizadas}
    if destacadas or destacadas_actualizadas:
        update_doc['etiquetas_destacadas_documentos'] = destacadas_actualizadas
    _mongo_update_document(DirectorioFirmas, colaborador, update_doc)
    return actualizadas


def _actualizar_destacado_etiqueta_documento_usuario(owner_email, etiqueta, destacado):
    owner_email = _normalizar_email(owner_email)
    etiqueta = _resolver_etiqueta_documento_usuario(owner_email, etiqueta)
    if not etiqueta:
        raise ValueError("Etiqueta no encontrada.")

    parent, _ = _partes_etiqueta_documento(etiqueta)
    destacadas = _familias_destacadas_documentos_usuario(owner_email)
    if destacado:
        _agregar_etiqueta_unica(destacadas, parent)
    else:
        parent_fold = parent.casefold()
        destacadas = [item for item in destacadas if item.casefold() != parent_fold]

    _guardar_destacadas_documentos_usuario(owner_email, destacadas)
    return etiqueta


def _etiquetas_subarbol_documento_usuario(owner_email, etiqueta_padre):
    parent, child = _partes_etiqueta_documento(etiqueta_padre)
    if child:
        return [_ruta_etiqueta_documento(parent, child)]

    etiquetas = []
    for etiqueta in _etiquetas_documentos_usuario(owner_email):
        item_parent, item_child = _partes_etiqueta_documento(etiqueta)
        if item_parent != parent:
            continue
        if item_child:
            _agregar_etiqueta_unica(etiquetas, _ruta_etiqueta_documento(item_parent, item_child))
        else:
            _agregar_etiqueta_unica(etiquetas, item_parent)
    return etiquetas


def _renombrar_etiqueta_documento_usuario(owner_email, etiqueta_actual, etiqueta_nueva):
    owner_email = _normalizar_email(owner_email)
    actual = _resolver_etiqueta_documento_usuario(owner_email, etiqueta_actual)
    if not actual:
        raise ValueError("Etiqueta no encontrada.")

    actual_parent, actual_child = _partes_etiqueta_documento(actual)
    nuevo_nombre = _normalizar_componente_etiqueta_documento(etiqueta_nueva)
    if not nuevo_nombre:
        raise ValueError("La etiqueta no puede estar vacía.")
    if _etiqueta_documento_es_reservada(nuevo_nombre):
        raise ValueError("Ese nombre está reservado para filtros del sistema.")

    if actual_child:
        nueva = _ruta_etiqueta_documento(actual_parent, nuevo_nombre)
        cambios = {actual: nueva}
    else:
        nueva = _ruta_etiqueta_documento(nuevo_nombre)
        cambios = {}
        for etiqueta in _etiquetas_subarbol_documento_usuario(owner_email, actual):
            parent, child = _partes_etiqueta_documento(etiqueta)
            cambios[etiqueta] = _ruta_etiqueta_documento(nuevo_nombre, child)

    cambios_fold = {key.casefold(): value for key, value in cambios.items()}
    for existente in _etiquetas_documentos_usuario(owner_email):
        existente_fold = existente.casefold()
        if existente_fold in cambios_fold:
            continue
        if cambios_fold and any(valor.casefold() == existente_fold for valor in cambios.values()):
            raise ValueError("Ya existe una etiqueta con ese nombre.")

    for anterior, posterior in cambios.items():
        _mongo_collection(ProcesoFirma).update_many(
            {'owner_email': owner_email, 'etiqueta': anterior},
            {'$set': {'etiqueta': posterior}},
        )
        _mongo_collection(EtiquetaDocumento).update_many(
            {'owner_email': owner_email, 'nombre': anterior},
            {'$set': {'nombre': posterior}},
        )

    for posterior in cambios.values():
        if not _mongo_find_one(EtiquetaDocumento, {'owner_email': owner_email, 'nombre': posterior}):
            _mongo_insert_model(EtiquetaDocumento, {
                'owner_email': owner_email,
                'nombre': posterior,
                'created_at': _datetime_for_mongo(),
            })

    _actualizar_catalogo_etiquetas_por_mapa(owner_email, cambios)
    return nueva


def _eliminar_etiqueta_documento_usuario(owner_email, etiqueta):
    owner_email = _normalizar_email(owner_email)
    actual = _resolver_etiqueta_documento_usuario(owner_email, etiqueta)
    if not actual:
        raise ValueError("Etiqueta no encontrada.")

    parent, child = _partes_etiqueta_documento(actual)
    if child:
        fallback = parent
        _mongo_collection(ProcesoFirma).update_many(
            {'owner_email': owner_email, 'etiqueta': actual},
            {'$set': {'etiqueta': parent}},
        )
        _mongo_collection(EtiquetaDocumento).delete_many({'owner_email': owner_email, 'nombre': actual})
        _actualizar_catalogo_etiquetas_por_mapa(owner_email, eliminadas=[actual])
        _guardar_etiqueta_documento_usuario(owner_email, parent)
        return {'deleted': actual, 'fallback': fallback}

    eliminadas = _etiquetas_subarbol_documento_usuario(owner_email, actual)
    for etiqueta_eliminada in eliminadas:
        _mongo_collection(ProcesoFirma).update_many(
            {'owner_email': owner_email, 'etiqueta': etiqueta_eliminada},
            {'$set': {'etiqueta': ''}},
        )
    _mongo_collection(EtiquetaDocumento).delete_many({'owner_email': owner_email, 'nombre': {'$in': eliminadas}})
    _actualizar_catalogo_etiquetas_por_mapa(owner_email, eliminadas=eliminadas)
    return {'deleted': actual, 'fallback': PORTAL_LABEL_UNTAGGED_VALUE}


def _portal_etiquetas_payload(owner_email):
    owner_email = _normalizar_email(owner_email)
    collection = _mongo_collection(ProcesoFirma)
    base_query = {'owner_email': owner_email}
    total = collection.count_documents(base_query)
    sin_etiqueta = collection.count_documents(_query_sin_etiqueta_documento(owner_email))

    labels = [
        {
            'value': PORTAL_LABEL_ALL_VALUE,
            'name': 'Todo',
            'count': total,
            'special': True,
            'icon': 'folder_open',
        },
        {
            'value': PORTAL_LABEL_UNTAGGED_VALUE,
            'name': 'Sin etiqueta',
            'count': sin_etiqueta,
            'special': True,
            'icon': 'folder_off',
        },
    ]

    etiquetas_usuario = _etiquetas_documentos_usuario(owner_email)
    destacadas = _etiquetas_destacadas_documentos_usuario(owner_email, etiquetas_usuario)
    destacadas_fold = {item.casefold() for item in destacadas}
    etiquetas_ordenadas = []
    for etiqueta in destacadas:
        _agregar_etiqueta_unica(etiquetas_ordenadas, etiqueta)
    for etiqueta in etiquetas_usuario:
        _agregar_etiqueta_unica(etiquetas_ordenadas, etiqueta)

    parents_con_hijos = set()
    for etiqueta in etiquetas_usuario:
        parent, child = _partes_etiqueta_documento(etiqueta)
        if child:
            parents_con_hijos.add(parent.casefold())

    for etiqueta in etiquetas_ordenadas:
        parent, child = _partes_etiqueta_documento(etiqueta)
        etiqueta_query = _query_etiqueta_documento(owner_email, etiqueta)
        labels.append({
            'value': etiqueta,
            'name': etiqueta,
            'short_name': child or parent,
            'parent': parent,
            'child': child,
            'depth': 1 if child else 0,
            'has_children': not child and parent.casefold() in parents_con_hijos,
            'count': collection.count_documents(etiqueta_query),
            'special': False,
            'featured': etiqueta.casefold() in destacadas_fold,
            'icon': 'folder',
        })

    return {'status': 'success', 'labels': labels}


def _dominio_de_email(email):
    email = _normalizar_email(email)
    return email.split('@', 1)[1] if '@' in email else ''


def _normalizar_hex_color(color, default=BRAND_DEFAULT_COLOR):
    color = str(color or '').strip()
    if not color:
        return default
    if not color.startswith('#'):
        color = f"#{color}"
    color = color.upper()
    if not re.fullmatch(r'#[0-9A-F]{6}', color):
        raise ValueError("El color debe tener formato HEX, por ejemplo #162839.")
    return color


def _normalizar_drive_folder_id(value, label):
    folder_id = str(value or '').strip()
    if not folder_id:
        raise ValueError(f"Falta el ID de {label}.")
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,200}', folder_id):
        raise ValueError(f"El ID de {label} no parece ser un ID valido de Google Drive.")
    return folder_id


def _rgb_from_hex(hex_color):
    color = _normalizar_hex_color(hex_color)
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _shade_hex_color(hex_color, factor):
    red, green, blue = _rgb_from_hex(hex_color)
    channels = []
    for channel in (red, green, blue):
        if factor < 0:
            value = channel * (1 + factor)
        else:
            value = channel + (255 - channel) * factor
        channels.append(max(0, min(255, int(round(value)))))
    return f"#{channels[0]:02X}{channels[1]:02X}{channels[2]:02X}"


def _on_color_for_hex(hex_color):
    red, green, blue = _rgb_from_hex(hex_color)
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return "#162839" if luminance > 0.68 else "#FFFFFF"


def _guardar_logo_dominio(logo_file, dominio):
    if not logo_file:
        return None

    extension = os.path.splitext(logo_file.name or '')[1].lower()
    if extension not in BRAND_LOGO_ALLOWED_EXTENSIONS:
        raise ValueError("El logo debe ser PNG, JPG, JPEG o WEBP.")

    content_type = str(getattr(logo_file, 'content_type', '') or '')
    if content_type and not content_type.startswith('image/'):
        raise ValueError("El archivo seleccionado no parece ser una imagen.")

    safe_domain = re.sub(r'[^a-z0-9.-]+', '-', _normalizar_dominio(dominio)).strip('.-') or 'dominio'
    rel_dir = os.path.join('branding', safe_domain)
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    filename = f"logo-{uuid.uuid4().hex[:12]}{extension}"
    rel_path = os.path.join(rel_dir, filename)
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
    with open(abs_path, 'wb+') as destination:
        for chunk in logo_file.chunks():
            destination.write(chunk)

    normalized_path = rel_path.replace(os.sep, '/')
    return {
        'logo_path': normalized_path,
        'logo_url': f"{settings.MEDIA_URL.rstrip('/')}/{normalized_path}",
    }


def _eliminar_logo_dominio(logo_path):
    logo_path = str(logo_path or '').replace('\\', '/')
    if not logo_path.startswith('branding/'):
        return
    full_path = os.path.abspath(os.path.join(settings.MEDIA_ROOT, logo_path))
    media_root = os.path.abspath(settings.MEDIA_ROOT)
    if not full_path.startswith(media_root):
        return
    try:
        if os.path.exists(full_path):
            os.remove(full_path)
    except OSError:
        pass


def _marca_payload(dominio='', carpeta=None):
    raw_color = getattr(carpeta, 'brand_color', '') if carpeta else ''
    try:
        color = _normalizar_hex_color(raw_color, BRAND_DEFAULT_COLOR)
    except ValueError:
        color = BRAND_DEFAULT_COLOR

    raw_logo_url = (getattr(carpeta, 'logo_url', '') if carpeta else '') or ''
    logo_url = raw_logo_url or BRAND_DEFAULT_LOGO_URL
    if logo_url == BRAND_LEGACY_INVERTED_LOGO_URL:
        logo_url = BRAND_DEFAULT_LOGO_URL
    dominio = _normalizar_dominio(dominio or getattr(carpeta, 'dominio', '') if carpeta else dominio)
    nombre = BRAND_DEFAULT_NAME if dominio == BRAND_DEFAULT_DOMAIN else (dominio.upper() if dominio else BRAND_DEFAULT_NAME)
    on_color = _on_color_for_hex(color)
    return {
        'dominio': dominio,
        'nombre': nombre,
        'color': color,
        'color_hover': _shade_hex_color(color, -0.16),
        'color_soft': _shade_hex_color(color, 0.82),
        'on_color': on_color,
        'on_color_muted': on_color,
        'logo_url': logo_url,
        'logo_is_default': logo_url == BRAND_DEFAULT_LOGO_URL,
    }


def _marca_por_email(email):
    dominio = _dominio_de_email(email)
    carpeta = _mongo_find_one(CarpetaDominio, {'dominio': dominio}) if dominio else None
    return _marca_payload(dominio, carpeta)


def _portal_context(owner_email, **extra):
    context = {
        'owner_email': owner_email,
        'marca_portal': _marca_por_email(owner_email),
    }
    context.update(extra)
    return context


def _carpeta_dominio_payload(carpeta):
    marca = _marca_payload(getattr(carpeta, 'dominio', ''), carpeta)
    return {
        'id': str(getattr(carpeta, 'id', '')),
        'dominio': getattr(carpeta, 'dominio', ''),
        'drive_folder_id': getattr(carpeta, 'drive_folder_id', ''),
        'brand_color': marca['color'],
        'logo_url': getattr(carpeta, 'logo_url', '') or '',
        'logo_preview_url': marca['logo_url'],
    }


def _asegurar_marca_raloy_actual():
    carpeta = _mongo_find_one(CarpetaDominio, {'dominio': BRAND_DEFAULT_DOMAIN})
    if not carpeta:
        return
    updates = {}
    if not getattr(carpeta, 'brand_color', ''):
        updates['brand_color'] = BRAND_DEFAULT_COLOR
    if not getattr(carpeta, 'logo_url', '') or getattr(carpeta, 'logo_url', '') == BRAND_LEGACY_INVERTED_LOGO_URL:
        updates['logo_url'] = BRAND_DEFAULT_LOGO_URL
        updates['logo_path'] = ''
    if updates:
        updates['updated_at'] = _datetime_for_mongo()
        _mongo_update_document(CarpetaDominio, carpeta, updates)


def _indice_actual_cero(proceso):
    try:
        return max(int(proceso.indice_actual or 1) - 1, 0)
    except (TypeError, ValueError):
        return 0


def _primer_indice_pendiente(firmantes, start_index=0):
    for idx in range(max(start_index, 0), len(firmantes)):
        if not firmantes[idx].get('fecha_firma'):
            return idx
    return None


def _indice_pendiente_actual(proceso, firmantes):
    start_index = _indice_actual_cero(proceso)
    pending = _primer_indice_pendiente(firmantes, start_index)
    if pending is not None:
        return pending
    return _primer_indice_pendiente(firmantes, 0)


def _indices_firmas_en_turno(firmantes, start_index):
    if start_index is None or start_index < 0 or start_index >= len(firmantes):
        return []

    correo_turno = _normalizar_email(firmantes[start_index].get('email'))
    if not correo_turno:
        return [start_index] if not firmantes[start_index].get('fecha_firma') else []

    indices = []
    for idx, firmante in enumerate(firmantes):
        if firmante.get('fecha_firma'):
            continue
        if _normalizar_email(firmante.get('email')) != correo_turno:
            continue
        indices.append(idx)
    return indices


def _indice_por_token(firmantes, firmante_token):
    if not firmante_token:
        return None
    for idx, firmante in enumerate(firmantes):
        if str(firmante.get('token_firmante', '')) == str(firmante_token):
            return idx
    return None


def _copiar_evidencia_firma(firmante, data, fecha_firma, ip_user, document_hash=None):
    firmante['fecha_firma'] = fecha_firma
    if ip_user:
        firmante['ip'] = ip_user
    if document_hash:
        firmante['hash'] = data.get('hash') or document_hash

    for field in ('registro', 'firma_digital', 'signature', 'signature_base64', 'device', 'metadata'):
        value = data.get(field)
        if value not in (None, ''):
            firmante[field] = value


def _marcar_notificaciones_firma(reference_id, email):
    email_norm = _normalizar_email(email)
    if not email_norm:
        return

    try:
        from .models import SignatureNotification, SignaturesMaster
        now = timezone.now().replace(tzinfo=None)

        _mongo_collection(SignatureNotification).update_many(
            {
                'reference_id': str(reference_id),
                'user_email': email_norm,
                'status': 'pending',
            },
            {'$set': {'status': 'signed', 'processed': True}},
        )

        _mongo_collection(SignaturesMaster).update_many(
            {
                'reference_id': str(reference_id),
                'user_email': email_norm,
            },
            {
                '$set': {
                    'status': 'signed',
                    'notification_enabled': False,
                    'notified_to_mobile': True,
                    'updated_at': now,
                }
            },
        )
    except Exception as e:
        print(f"Error marcando notificaciones firmadas para {email_norm} ({reference_id}): {e}")


def _uuid_text(value):
    if value in (None, ''):
        return ''
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        return value

    raw = None
    if hasattr(value, 'bytes'):
        raw = value.bytes
    elif isinstance(value, (bytes, bytearray)):
        raw = bytes(value)

    if raw and len(raw) == 16:
        try:
            return str(uuid.UUID(bytes=raw))
        except (TypeError, ValueError):
            pass
    return str(value)


def _mongo_database():
    global _MONGO_CLIENT
    db_conf = settings.DATABASES['default']
    if _MONGO_CLIENT is None:
        from pymongo import MongoClient
        _MONGO_CLIENT = MongoClient(
            db_conf['CLIENT']['host'],
            serverSelectionTimeoutMS=5000,
            uuidRepresentation='pythonLegacy',
        )
    return _MONGO_CLIENT[db_conf['NAME']]


def _mongo_collection(model):
    return _mongo_database()[model._meta.db_table]


def _n8n_monitor_global_collection():
    return _mongo_database()['n8n_monitor_events']


def _registrar_evento_global_n8n_monitor(event, request=None, owner_email=''):
    if not event:
        return
    try:
        actor = owner_email
        if not actor and request is not None:
            actor = request.session.get('owner_email') or request.session.get('admin_email') or ''
        global_event = {
            **event,
            'owner_email': _normalizar_email(actor),
            'global_event': True,
            'created_at': _datetime_for_mongo(),
        }
        _n8n_monitor_global_collection().insert_one(global_event)
    except Exception as exc:
        print(f"No se pudo registrar evento global n8n: {exc}")


def _eventos_globales_n8n_monitor(limit=80):
    try:
        cursor = _n8n_monitor_global_collection().find({}, {'_id': 0}).sort('timestamp', -1).limit(limit)
        return list(reversed(list(cursor)))
    except Exception as exc:
        print(f"No se pudieron cargar eventos globales n8n: {exc}")
        return []


def _combinar_eventos_n8n_monitor(*event_groups):
    combined = []
    seen = set()
    for group in event_groups:
        for event in group or []:
            event_id = str(event.get('id') or '')
            if event_id and event_id in seen:
                continue
            if event_id:
                seen.add(event_id)
            combined.append(event)
    combined.sort(key=lambda item: str(item.get('timestamp') or ''))
    return combined[-80:]


def _mongo_pk_query(document):
    if hasattr(document, '_id'):
        return {'_id': document._id}
    return {'id': getattr(document, 'id')}


def _mongo_update_document(model, document, fields):
    if not fields:
        return
    _mongo_collection(model).update_one(_mongo_pk_query(document), {'$set': fields})
    for key, value in fields.items():
        setattr(document, key, value)


def _mongo_delete_document(model, document):
    _mongo_collection(model).delete_one(_mongo_pk_query(document))


def _mongo_find_one_by_id(model, id_value, query=None):
    if id_value in (None, ''):
        return None

    base_query = dict(query or {})
    candidates = [id_value, str(id_value)]
    try:
        candidates.append(int(id_value))
    except (TypeError, ValueError):
        pass

    for candidate in candidates:
        document = _mongo_find_one(model, {**base_query, 'id': candidate})
        if document is not None:
            return document

    return _mongo_find_one_by_id_text(model, id_value, base_query)


def _mongo_insert_model(model, document):
    document.setdefault('id', _mongo_next_int_id(model))
    _mongo_collection(model).insert_one(document)
    return _mongo_to_namespace(document)


def _mongo_update_or_insert_by_query(model, query, defaults):
    collection = _mongo_collection(model)
    document = collection.find_one(query)
    if document:
        collection.update_one({'_id': document['_id']}, {'$set': defaults})
        document.update(defaults)
        return _mongo_to_namespace(document), False

    insert_doc = {**query, **defaults}
    insert_doc.setdefault('id', _mongo_next_int_id(model))
    collection.insert_one(insert_doc)
    return _mongo_to_namespace(insert_doc), True


def _mongo_count(model, query=None):
    return _mongo_collection(model).count_documents(query or {})


def _datetime_for_mongo(value=None):
    value = value or timezone.now()
    return value.replace(tzinfo=None) if timezone.is_aware(value) else value


def _datetime_for_compare(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _mongo_to_namespace(document):
    data = dict(document)
    data['id'] = data.get('id', data.get('_id'))
    for field in ('token_acceso', 'id_documento', 'reset_token'):
        if field in data:
            data[field] = _uuid_text(data[field])
    for field, default in {
        'firmantes': [],
        'summary_data': {},
        'document_variables': {},
        'valores_capturados': {},
        'variables': [],
        'firmantes_config': [],
        'usuarios_permitidos': [],
        'permisos_portal': [],
        'etiquetas_documentos': [],
        'etiquetas_destacadas_documentos': [],
        'configuracion_dashboard': {},
    }.items():
        if field in data:
            data[field] = _json_or_default(data[field], default)
    return SimpleNamespace(**data)


def _mongo_find(model, query=None, sort=None):
    cursor = _mongo_collection(model).find(query or {})
    if sort:
        cursor = cursor.sort(sort)
    return [_mongo_to_namespace(doc) for doc in cursor]


def _mongo_find_one(model, query=None):
    document = _mongo_collection(model).find_one(query or {})
    return _mongo_to_namespace(document) if document else None


def _mongo_find_one_by_uuid_field(model, uuid_field, uuid_value, query=None):
    expected = str(uuid_value)
    for document in _mongo_find(model, query or {}):
        if str(getattr(document, uuid_field, '')) == expected:
            return document
    return None


def _mongo_find_one_by_id_text(model, id_value, query=None):
    expected = str(id_value)
    for document in _mongo_find(model, query or {}):
        if str(getattr(document, 'id', '')) == expected:
            return document
    return None


def _mongo_find_proceso_by_token(token):
    try:
        token_uuid = token if isinstance(token, uuid.UUID) else uuid.UUID(str(token))
    except (TypeError, ValueError):
        token_uuid = None

    document = None
    if token_uuid is not None:
        document = _mongo_collection(ProcesoFirma).find_one({'token_acceso': token_uuid})

    if document:
        return _mongo_to_namespace(document)
    return _mongo_find_one_by_uuid_field(ProcesoFirma, 'token_acceso', token)


def _get_proceso_por_token_or_404(token):
    proceso = _mongo_find_proceso_by_token(token)
    if not proceso:
        raise Http404("Proceso de firma no encontrado")
    return proceso


def _crear_payload_qr_trazabilidad(proceso):
    signed_hash = signing.dumps(
        {
            'token': str(proceso.token_acceso),
            'reference_id': proceso.reference_id,
        },
        salt=QR_TRAZABILIDAD_SALT,
    )
    expires_at = timezone.now() + timedelta(seconds=QR_TRAZABILIDAD_MAX_AGE_SECONDS)
    qr_url = f"{PUBLIC_BASE_URL}/trazabilidad/qr/{quote(signed_hash, safe='')}/"
    return {
        'hash': signed_hash,
        'link': qr_url,
        'expires_at': expires_at,
        'expires_at_label': timezone.localtime(expires_at).strftime('%d/%m/%Y %H:%M'),
        'max_age_seconds': QR_TRAZABILIDAD_MAX_AGE_SECONDS,
    }


def _validar_acceso_owner(proceso, owner_email):
    return _normalizar_email(getattr(proceso, 'owner_email', '')) == _normalizar_email(owner_email)


def _admin_es_global(admin_obj):
    return bool(
        admin_obj
        and (getattr(admin_obj, 'es_superadmin', False) or _normalizar_email(getattr(admin_obj, 'email', '')) == 'pjimenezb@raloy.com.mx')
    )


def _admin_tiene_acceso_proceso(admin_obj, proceso):
    if not admin_obj or not proceso:
        return False
    admin_email = _normalizar_email(getattr(admin_obj, 'email', ''))
    owner_email = _normalizar_email(getattr(proceso, 'owner_email', ''))
    if _admin_es_global(admin_obj) or owner_email == admin_email:
        return True
    owner = _mongo_find_one(DirectorioFirmas, {'email': owner_email})
    return _normalizar_email(getattr(owner, 'tecnico_asignado', '')) == admin_email


def _admin_dashboard_base_query(admin_obj):
    if _admin_es_global(admin_obj):
        return {}

    admin_email = _normalizar_email(getattr(admin_obj, 'email', ''))
    usuarios_asignados = _mongo_find(DirectorioFirmas, {'tecnico_asignado': admin_email})
    emails_asignados = [_normalizar_email(getattr(u, 'email', '')) for u in usuarios_asignados if getattr(u, 'email', None)]
    owners_permitidos = [email for email in {admin_email, *emails_asignados} if email]
    return {'owner_email': {'$in': owners_permitidos}}


def _admin_dashboard_fecha_query(value, fin=False):
    try:
        fecha = datetime.strptime(str(value or '').strip(), '%Y-%m-%d')
    except (TypeError, ValueError):
        return None
    if fin:
        fecha = fecha.replace(hour=23, minute=59, second=59, microsecond=999999)
    return _datetime_for_mongo(fecha)


def _admin_dashboard_docs_query(admin_obj, filtros=None):
    filtros = filtros or {}
    condiciones = []
    base_query = _admin_dashboard_base_query(admin_obj)
    if base_query:
        condiciones.append(base_query)

    folio = str(filtros.get('filFolio') or '').strip()
    if folio:
        condiciones.append({'reference_id': {'$regex': re.escape(folio), '$options': 'i'}})

    dominio = str(filtros.get('filDominio') or '').strip().lower()
    if dominio and dominio != 'all':
        condiciones.append({'owner_email': {'$regex': f"@{re.escape(dominio)}$", '$options': 'i'}})

    estado = str(filtros.get('filEstado') or '').strip().upper()
    if estado and estado != 'ALL':
        condiciones.append({'status': estado})

    fecha_ini = _admin_dashboard_fecha_query(filtros.get('filFechaIni'))
    fecha_fin = _admin_dashboard_fecha_query(filtros.get('filFechaFin'), fin=True)
    fecha_query = {}
    if fecha_ini:
        fecha_query['$gte'] = fecha_ini
    if fecha_fin:
        fecha_query['$lte'] = fecha_fin
    if fecha_query:
        condiciones.append({'created_at': fecha_query})

    if not condiciones:
        return {}
    if len(condiciones) == 1:
        return condiciones[0]
    return {'$and': condiciones}


def _admin_dashboard_doc_payload(proceso):
    summary_data = _json_or_default(getattr(proceso, 'summary_data', {}) or {}, {})
    firmx_id = summary_data.get('firmx_id')
    firmantes = _normalizar_firmantes(getattr(proceso, 'firmantes', []))
    total_firmas = len(firmantes)
    firmas_hechas = sum(1 for f in firmantes if f.get('fecha_firma'))
    porcentaje = int((firmas_hechas / total_firmas) * 100) if total_firmas > 0 else 0
    owner_doc = getattr(proceso, 'owner_email', '') or ''
    created_at = getattr(proceso, 'created_at', None)
    status = getattr(proceso, 'status', 'UNKNOWN') or 'UNKNOWN'
    etiqueta = _normalizar_etiqueta_documento(getattr(proceso, 'etiqueta', ''))
    return {
        'reference_id': getattr(proceso, 'reference_id', 'N/A'),
        'token': str(getattr(proceso, 'token_acceso', '')),
        'owner_email': owner_doc or 'N/A',
        'dominio': owner_doc.split('@')[1] if '@' in owner_doc else 'N/A',
        'status': status,
        'fecha': created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else '',
        'progreso': f"{firmas_hechas}/{total_firmas}",
        'firmas_hechas': firmas_hechas,
        'total_firmas': total_firmas,
        'porcentaje': porcentaje,
        'etiqueta': etiqueta,
        'firmx_id': firmx_id or '',
        'can_adjust': status == 'COMPLETED' and not firmx_id,
    }


def _admin_dashboard_document_domains(base_query):
    dominios = set()
    try:
        owner_emails = _mongo_collection(ProcesoFirma).distinct('owner_email', base_query or {})
    except Exception:
        owner_emails = []
    for owner_email in owner_emails:
        owner_email = str(owner_email or '').strip().lower()
        if '@' in owner_email:
            dominios.add(owner_email.split('@', 1)[1])
    return sorted(dominios)


def _admin_dashboard_docs_page(admin_obj, filtros=None, sync_limit=5):
    filtros = filtros or {}
    default_page_size = 25
    try:
        page = int(filtros.get('page') or 1)
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)

    collection = _mongo_collection(ProcesoFirma)
    base_query = _admin_dashboard_base_query(admin_obj)
    query = _admin_dashboard_docs_query(admin_obj, filtros)
    total_global = collection.count_documents(base_query or {})
    total_filtered = collection.count_documents(query or {})
    try:
        page_size = int(filtros.get('page_size') or default_page_size)
    except (TypeError, ValueError):
        page_size = default_page_size
    page_size = max(1, page_size)
    total_pages = max(1, (total_filtered + page_size - 1) // page_size)
    page = min(page, total_pages)
    skip = (page - 1) * page_size

    cursor = (
        collection
        .find(query or {})
        .sort('created_at', -1)
        .skip(skip)
        .limit(page_size)
    )

    docs = []
    sync_count = 0
    for raw_doc in cursor:
        proceso = _mongo_to_namespace(raw_doc)
        summary_data = _json_or_default(getattr(proceso, 'summary_data', {}) or {}, {})
        firmx_id = summary_data.get('firmx_id')

        if _proceso_firmx_puede_sincronizar(proceso) and sync_count < sync_limit:
            success, _ = _firmx_sync_status(firmx_id)
            if success:
                proceso = _mongo_find_one(ProcesoFirma, {'_id': proceso._id}) or proceso
            sync_count += 1

        docs.append(_admin_dashboard_doc_payload(proceso))

    start = skip + 1 if total_filtered else 0
    end = min(skip + page_size, total_filtered)
    return {
        'status': 'success',
        'docs': docs,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
        'total_filtered': total_filtered,
        'total_global': total_global,
        'range_start': start,
        'range_end': end,
    }


def _portal_dashboard_docs_query(owner_email, filtros=None):
    filtros = filtros or {}
    condiciones = [{'owner_email': _normalizar_email(owner_email)}]

    folio = str(filtros.get('filFolio') or '').strip()
    if folio:
        condiciones.append({'reference_id': {'$regex': re.escape(folio), '$options': 'i'}})

    estado = str(filtros.get('filEstado') or '').strip().upper()
    if estado and estado != 'ALL':
        condiciones.append({'status': estado})

    fecha_ini = _admin_dashboard_fecha_query(filtros.get('filFechaIni'))
    fecha_fin = _admin_dashboard_fecha_query(filtros.get('filFechaFin'), fin=True)
    fecha_query = {}
    if fecha_ini:
        fecha_query['$gte'] = fecha_ini
    if fecha_fin:
        fecha_query['$lte'] = fecha_fin
    if fecha_query:
        condiciones.append({'created_at': fecha_query})

    etiqueta_filtro = str(filtros.get('filEtiqueta') or PORTAL_LABEL_ALL_VALUE).strip()
    if etiqueta_filtro == PORTAL_LABEL_UNTAGGED_VALUE:
        condiciones.append(_query_sin_etiqueta_documento())
    elif etiqueta_filtro and etiqueta_filtro.casefold() not in (PORTAL_LABEL_ALL_VALUE, 'todo'):
        etiqueta = _normalizar_etiqueta_documento(etiqueta_filtro)
        if etiqueta:
            condiciones.append(_query_etiqueta_documento(None, etiqueta))

    return condiciones[0] if len(condiciones) == 1 else {'$and': condiciones}


def _portal_dashboard_doc_payload(proceso):
    firmantes = _normalizar_firmantes(getattr(proceso, 'firmantes', []))
    total_firmas = len(firmantes)
    firmas_hechas = sum(1 for f in firmantes if f.get('fecha_firma'))
    porcentaje = int((firmas_hechas / total_firmas) * 100) if total_firmas > 0 else 0
    created_at = getattr(proceso, 'created_at', None)
    summary_data = _json_or_default(getattr(proceso, 'summary_data', {}) or {}, {})
    firmx_id = summary_data.get('firmx_id') or ''
    status = getattr(proceso, 'status', 'UNKNOWN') or 'UNKNOWN'
    etiqueta = _normalizar_etiqueta_documento(getattr(proceso, 'etiqueta', ''))
    return {
        'reference_id': getattr(proceso, 'reference_id', 'N/A'),
        'token': str(getattr(proceso, 'token_acceso', '')),
        'status': status,
        'fecha_iso': created_at.strftime('%Y-%m-%d') if created_at else '',
        'fecha_formato': created_at.strftime('%d/%m/%Y %H:%M') if created_at else '',
        'mes': created_at.strftime('%B %Y') if created_at else 'Sin fecha',
        'total_firmas': total_firmas,
        'firmas_hechas': firmas_hechas,
        'porcentaje': porcentaje,
        'can_adjust': status == 'COMPLETED' and not firmx_id,
        'firmx_id': firmx_id,
        'etiqueta': etiqueta,
    }


def _portal_dashboard_docs_page(owner_email, filtros=None, sync_limit=5):
    filtros = filtros or {}
    default_page_size = 25
    try:
        page = int(filtros.get('page') or 1)
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)

    collection = _mongo_collection(ProcesoFirma)
    base_query = {'owner_email': _normalizar_email(owner_email)}
    query = _portal_dashboard_docs_query(owner_email, filtros)
    total_global = collection.count_documents(base_query)
    total_filtered = collection.count_documents(query)
    try:
        page_size = int(filtros.get('page_size') or default_page_size)
    except (TypeError, ValueError):
        page_size = default_page_size
    page_size = max(1, page_size)
    if total_filtered:
        page_size = min(page_size, total_filtered)
    total_pages = max(1, (total_filtered + page_size - 1) // page_size)
    page = min(page, total_pages)
    skip = (page - 1) * page_size

    cursor = (
        collection
        .find(query)
        .sort('created_at', -1)
        .skip(skip)
        .limit(page_size)
    )

    docs = []
    sync_count = 0
    for raw_doc in cursor:
        proceso = _mongo_to_namespace(raw_doc)
        summary_data = _json_or_default(getattr(proceso, 'summary_data', {}) or {}, {})
        firmx_id = summary_data.get('firmx_id')
        if _proceso_firmx_puede_sincronizar(proceso) and sync_count < sync_limit:
            success, _ = _firmx_sync_status(firmx_id)
            if success:
                proceso = _mongo_find_one(ProcesoFirma, {'_id': proceso._id}) or proceso
            sync_count += 1
        docs.append(_portal_dashboard_doc_payload(proceso))

    start = skip + 1 if total_filtered else 0
    end = min(skip + page_size, total_filtered)
    return {
        'status': 'success',
        'docs': docs,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
        'total_filtered': total_filtered,
        'total_global': total_global,
        'range_start': start,
        'range_end': end,
    }


def _resolver_acceso_proceso(request, proceso, rol_requerido=None):
    if rol_requerido in (None, 'owner'):
        owner_email = request.session.get('owner_email')
        if owner_email and _validar_acceso_owner(proceso, owner_email):
            return {'rol': 'owner', 'email': _normalizar_email(owner_email)}

    if rol_requerido in (None, 'admin'):
        admin_email = request.session.get('admin_email')
        if admin_email:
            admin_obj = _mongo_find_one(AdministradorPortal, {'email': _normalizar_email(admin_email)})
            if _admin_tiene_acceso_proceso(admin_obj, proceso):
                return {'rol': 'admin', 'email': _normalizar_email(admin_email), 'admin': admin_obj}

    return None


def _valor_firma_base64(value):
    if isinstance(value, dict):
        for key in ('base64', 'firma_base64', 'signature_base64', 'data'):
            nested = _valor_firma_base64(value.get(key))
            if nested:
                return nested
        return ''
    if isinstance(value, str):
        value = value.strip()
        return value if len(value) > 40 else ''
    return ''


def _obtener_firma_base64_para_reestampado(firmante):
    for field in ('firma_capturada_base64', 'firma_base64', 'signature_base64', 'signature', 'firma_digital'):
        firma = _valor_firma_base64(firmante.get(field))
        if firma:
            return firma

    colaborador = _mongo_find_one(DirectorioFirmas, {'email': _normalizar_email(firmante.get('email'))})
    return _valor_firma_base64(getattr(colaborador, 'firma_base64', '')) if colaborador else ''


def _valor_hash_para_reestampado(value):
    if isinstance(value, dict):
        for key in ('hash', 'hash_documento', 'document_hash', 'sha256', 'checksum'):
            nested = _valor_hash_para_reestampado(value.get(key))
            if nested:
                return nested
        return ''
    if isinstance(value, str):
        value = value.strip()
        return value if len(value) >= 16 else ''
    return ''


def _obtener_hash_para_reestampado(firmante):
    for field in ('hash', 'hash_documento', 'document_hash', 'sha256', 'checksum', 'metadata'):
        hash_firma = _valor_hash_para_reestampado(firmante.get(field))
        if hash_firma:
            return hash_firma
    return ''


def _firmante_key(firmante, index):
    token = str(firmante.get('token_firmante') or '').strip()
    if token:
        return token
    return f"{_normalizar_email(firmante.get('email'))}::{index}"


def _posicion_base_firmante(firmante):
    for field in ('posicion_estampada', 'coordenadas_ajuste', 'coordenadas'):
        value = firmante.get(field)
        if isinstance(value, dict):
            return value
    correccion = firmante.get('correccion_firma')
    if isinstance(correccion, dict) and isinstance(correccion.get('posicion'), dict):
        return correccion.get('posicion')
    return {}


def _float_clamp(value, default=0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, 0.95))


def _coordenadas_ui_firmante(firmante, index):
    posicion = _posicion_base_firmante(firmante)
    page = posicion.get('page', 1)
    try:
        page = max(int(page), 1)
    except (TypeError, ValueError):
        page = 1
    return {
        'page': page,
        'x': _float_clamp(posicion.get('x'), 0.08),
        'y': _float_clamp(posicion.get('y'), min(0.08 + (index * 0.08), 0.76)),
    }


def _orden_firmante(firmante, index):
    try:
        return max(int(firmante.get('orden', index + 1)), 1)
    except (TypeError, ValueError):
        return index + 1


def _etiqueta_firmante(firmante, fallback=''):
    for field in ('label', 'etiqueta', 'rol', 'puesto_firma', 'firma_label', 'key', 'llave'):
        value = str(firmante.get(field) or '').strip()
        if value:
            return value
    return fallback


def _datos_ajuste_firmantes(firmantes):
    datos = []
    for index, firmante in enumerate(firmantes):
        coords = _coordenadas_ui_firmante(firmante, index)
        firma_b64 = _obtener_firma_base64_para_reestampado(firmante)
        hash_firma = _obtener_hash_para_reestampado(firmante)
        firmado = bool(firmante.get('fecha_firma'))
        tipo_reestampado = ''
        if firmado and firma_b64:
            tipo_reestampado = 'firma'
        elif firmado and hash_firma:
            tipo_reestampado = 'hash'
        datos.append({
            'key': _firmante_key(firmante, index),
            'token_firmante': str(firmante.get('token_firmante') or ''),
            'original_index': index,
            'orden': _orden_firmante(firmante, index),
            'nombre': firmante.get('nombre') or 'Firmante',
            'email': firmante.get('email') or '',
            'etiqueta': _etiqueta_firmante(firmante),
            'fecha_firma': firmante.get('fecha_firma') or '',
            'page': coords['page'],
            'x': coords['x'],
            'y': coords['y'],
            'puede_reestampar': bool(firmado and (firma_b64 or hash_firma)),
            'tipo_reestampado': tipo_reestampado,
        })
    return datos


def _sincronizar_pdf_finalizado(proceso):
    link_trazabilidad = f"{PUBLIC_BASE_URL}/trazabilidad/{proceso.token_acceso}/"
    firmantes = _normalizar_firmantes(getattr(proceso, 'firmantes', []))
    todos_los_correos = [f.get('email') for f in firmantes if f.get('email')]
    if getattr(proceso, 'owner_email', None):
        todos_los_correos.append(proceso.owner_email)

    dominio_creador = proceso.owner_email.split('@')[1] if proceso.owner_email and '@' in proceso.owner_email else 'raloy.com.mx'
    dominios_permitidos = {dominio_creador, 'raloy.com.mx', 'consorcionova.com'}
    correos_internos = [
        email for email in set(todos_los_correos)
        if email and any(str(email).endswith(dominio) for dominio in dominios_permitidos)
    ]

    try:
        with open(proceso.pdf_path, 'rb') as f:
            response = tracked_post(
                N8N_WEBHOOK_FINALIZAR_PROCESO,
                data={
                    "reference_id": proceso.reference_id,
                    "status": "COMPLETED",
                    "correos_destino": ",".join(correos_internos),
                    **_n8n_storage_data_for_proceso(proceso),
                    "link": link_trazabilidad,
                    "ajuste_firmas": "true",
                },
                files={"pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")},
                timeout=30,
            )
        n8n_error = _n8n_response_error(response)
        if n8n_error:
            if _n8n_error_respond_webhook_sin_usar(n8n_error):
                _registrar_advertencia_finalizacion_n8n(proceso, n8n_error)
                return ''
            return f"N8N respondió con error: {n8n_error}"
        _registrar_pdf_final_drive_id(proceso, response)
    except Exception as e:
        return str(e)
    return ''


def _parse_email_list(value):
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r'[\s,;]+', str(value or ''))

    emails = []
    for item in raw_items:
        email = _normalizar_email(item)
        if not email:
            continue
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            continue
        if email not in emails:
            emails.append(email)
    return emails


def _firmx_headers(base_url=None):
    api_key = _firmx_api_key(base_url=base_url)
    return {
        'X-Api-Key': api_key,
        'Content-Type': 'application/json',
    }


def _firmx_api_key(base_url=None):
    try:
        config_urls = _firmx_configuracion_urls(include_secrets=True)
        config = config_urls['config']
    except Exception as exc:
        print(f"No se pudo cargar ConfiguracionFirmex; usando settings.FIRMX_API_KEY: {exc}")
        config_urls = {'base_urls': []}
        config = None

    target_url = ''
    if base_url:
        try:
            target_url = _normalizar_firmx_base_url(base_url)
        except ValueError:
            target_url = ''

    if target_url:
        for endpoint in config_urls.get('base_urls', []):
            if endpoint.get('url') == target_url and endpoint.get('api_key'):
                return endpoint['api_key']

    if config and getattr(config, 'api_key', None):
        api_key = config.api_key
    else:
        api_key = getattr(settings, 'FIRMX_API_KEY', '')

    if not api_key:
        raise ValueError("FIRMX_API_KEY no está configurada.")
    return api_key


def _normalizar_firmx_base_url(base_url):
    clean_url = str(base_url or '').strip().rstrip('/')
    parsed = urlparse(clean_url)
    if not clean_url or parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError("La Base FIRMX debe ser una URL http(s) válida.")
    return clean_url


def _firmx_base_url_default():
    return _normalizar_firmx_base_url(getattr(settings, 'FIRMX_API_BASE_URL', ''))


def _firmx_configuracion_urls(include_secrets=False):
    try:
        config = _mongo_find_one(ConfiguracionFirmex)
    except Exception as exc:
        print(f"No se pudo cargar ConfiguracionFirmex; usando FIRMX_API_BASE_URL: {exc}")
        config = None
    default_url = _firmx_base_url_default()

    active_url = ''
    for field in ('firmx_base_url', 'base_url', 'active_base_url'):
        raw_value = getattr(config, field, '') if config else ''
        if raw_value:
            try:
                active_url = _normalizar_firmx_base_url(raw_value)
                break
            except ValueError:
                active_url = ''

    if not active_url:
        active_url = default_url

    raw_urls = _json_or_default(getattr(config, 'base_urls', []), []) if config else []
    endpoints = []
    seen = set()

    def add_endpoint(raw_url, created_at='', updated_at='', api_key=''):
        try:
            clean_url = _normalizar_firmx_base_url(raw_url)
        except ValueError:
            return
        if clean_url in seen:
            return
        seen.add(clean_url)
        endpoints.append({
            'url': clean_url,
            'created_at': str(created_at or ''),
            'updated_at': str(updated_at or ''),
            'active': clean_url == active_url,
            'has_api_key': bool(api_key),
        })
        if include_secrets:
            endpoints[-1]['api_key'] = str(api_key or '')

    for item in raw_urls:
        if isinstance(item, dict):
            add_endpoint(item.get('url'), item.get('created_at'), item.get('updated_at'), item.get('api_key'))
        else:
            add_endpoint(item)

    add_endpoint(active_url)

    return {
        'active_base_url': active_url,
        'base_urls': endpoints,
        'config': config,
    }


def _firmx_base_url_actual():
    return _firmx_configuracion_urls()['active_base_url']


def _firmx_base_url_desde_summary(summary_data):
    summary_data = _json_or_default(summary_data, {})
    for field in ('firmx_base_url', 'base_url', 'active_base_url'):
        try:
            if summary_data.get(field):
                return _normalizar_firmx_base_url(summary_data.get(field))
        except ValueError:
            pass

    qrs = _json_or_default(summary_data.get('qrs', []), [])
    candidates = []
    for item in qrs:
        if isinstance(item, dict):
            candidates.append(item.get('url_qr_code'))
    candidates.append(summary_data.get('url_qr_code'))

    for raw_url in candidates:
        parsed = urlparse(str(raw_url or '').strip())
        if parsed.scheme in ('http', 'https') and parsed.netloc:
            try:
                return _normalizar_firmx_base_url(f"{parsed.scheme}://{parsed.netloc}/digisign/api/v1")
            except ValueError:
                pass
    return ''


def _firmx_base_url_desde_api_url(raw_url):
    parsed = urlparse(str(raw_url or '').strip())
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return ''
    api_prefix = '/digisign/api/v1'
    if api_prefix not in parsed.path:
        return ''
    prefix = parsed.path.split(api_prefix, 1)[0] + api_prefix
    try:
        return _normalizar_firmx_base_url(f"{parsed.scheme}://{parsed.netloc}{prefix}")
    except ValueError:
        return ''


def _firmx_url(path, base_url=None):
    base_url = _normalizar_firmx_base_url(base_url) if base_url else _firmx_base_url_actual()
    return f"{base_url}/{path.lstrip('/')}"


def _firmx_timeout():
    return int(getattr(settings, 'FIRMX_REQUEST_TIMEOUT', 45))


def _firmx_sanitize_payload_for_curl(payload):
    safe_payload = json.loads(json.dumps(payload, ensure_ascii=False))
    if isinstance(safe_payload, dict) and 'document_base64' in safe_payload:
        base64_len = len(str(safe_payload.get('document_base64') or ''))
        safe_payload['document_base64'] = f"<base64_pdf_omitido:{base64_len} caracteres>"
    return safe_payload


def _firmx_curl_preview(method, path, payload=None):
    lines = [
        f"curl --request {method.upper()} \\",
        f"  --url {shlex.quote(_firmx_url(path))} \\",
        "  --header 'X-Api-Key: <FIRMX_API_KEY>' \\",
        "  --header 'Content-Type: application/json'",
    ]
    if payload is not None:
        lines[-1] += " \\"
        body = json.dumps(_firmx_sanitize_payload_for_curl(payload), ensure_ascii=False, indent=2)
        lines.append(f"  --data {shlex.quote(body)}")
    return "\n".join(lines)


def _json_response_from_requests(response):
    content_type = response.headers.get('content-type', '')
    if 'application/json' in content_type.lower():
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}
    return {"raw": response.text}


def _extract_firmx_document_id(data):
    if isinstance(data, dict):
        # 1. Buscar campos directos conocidos
        for key in ('document_id', 'documentId', 'id', 'document', 'document_pk', 'pk'):
            value = data.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()

        # 2. Buscar en URLs dentro de 'data' (Estructura observada en FIRMX v1)
        data_obj = data.get('data')
        if isinstance(data_obj, dict):
            for url_key in ('document_url', 'qrcode_url', 'url'):
                url = data_obj.get(url_key)
                if isinstance(url, str):
                    # El ID numérico suele estar al final de la URL, e.g. .../api/1565
                    match = re.search(r'/(\d+)(?:/|$)[\w-]*$', url)
                    if match:
                        return match.group(1)

        # 3. Búsqueda recursiva genérica
        for key, value in data.items():
            if key == 'data': continue  # Evitar doble procesamiento si ya se hizo arriba
            nested = _extract_firmx_document_id(value)
            if nested:
                return nested

    if isinstance(data, list):
        for item in data:
            nested = _extract_firmx_document_id(item)
            if nested:
                return nested
    return ''


def _parse_json_field(raw_value, default):
    if raw_value in (None, ''):
        return _default_json_value(default)
    if isinstance(raw_value, (list, dict)):
        return raw_value
    try:
        return json.loads(raw_value)
    except (TypeError, ValueError):
        return _default_json_value(default)


def _usuario_tiene_permiso(owner_email, permiso):
    email = _normalizar_email(owner_email)
    # Superadmins tienen todos los permisos
    admin_obj = _mongo_find_one(AdministradorPortal, {'email': email})
    if _admin_es_global(admin_obj):
        return True

    colaborador = _mongo_find_one(DirectorioFirmas, {'email': email})
    permisos = getattr(colaborador, 'permisos_portal', []) if colaborador else []
    permisos = _json_or_default(permisos, [])
    return permiso in permisos


def _mongo_next_int_id(model):
    document = _mongo_collection(model).find_one(
        {'id': {'$exists': True}},
        sort=[('id', -1)],
        projection={'id': True},
    )
    try:
        return int(document.get('id', 0)) + 1 if document else 1
    except (TypeError, ValueError):
        return 1


def _mongo_json_field(value, default):
    return _json_or_default(value, default)


def _actualizar_proceso_firma_mongo(proceso, **fields):
    json_defaults = {
        'firmantes': [],
        'summary_data': {},
        'document_variables': {},
        'valores_capturados': {},
    }
    update_doc = {}
    for key, value in fields.items():
        if key in json_defaults:
            update_doc[key] = _mongo_json_field(value, json_defaults[key])
        else:
            update_doc[key] = value
        setattr(proceso, key, value)

    if update_doc:
        _mongo_collection(ProcesoFirma).update_one({'_id': proceso._id}, {'$set': update_doc})


def _status_terminal_firmx(status):
    return str(status or '').upper() in FIRMX_TERMINAL_STATUSES


def _proceso_firmx_puede_sincronizar(proceso):
    summary_data = getattr(proceso, 'summary_data', {}) or {}
    return bool(summary_data.get('firmx_id')) and not _status_terminal_firmx(getattr(proceso, 'status', ''))


def _crear_proceso_firma_mongo(
        reference_id, pdf_path, firmantes, indice_actual=1, status='PROCESSING',
        view_info='file', summary_data=None, dir_drive='', exec_mode='normal',
        document_variables=None, valores_capturados=None, owner_email=''):
    token_acceso = uuid.uuid4()
    document = {
        'id': _mongo_next_int_id(ProcesoFirma),
        'reference_id': reference_id,
        'token_acceso': token_acceso,
        'pdf_path': pdf_path,
        'firmantes': _mongo_json_field(firmantes, []),
        'indice_actual': indice_actual,
        'status': status,
        'view_info': view_info,
        'summary_data': _mongo_json_field(summary_data, {}),
        'dir_drive': dir_drive,
        'exec_mode': exec_mode,
        'document_variables': _mongo_json_field(document_variables, {}),
        'valores_capturados': _mongo_json_field(valores_capturados, {}),
        'owner_email': owner_email,
        'etiqueta': '',
        'created_at': timezone.now().replace(tzinfo=None),
    }
    _mongo_collection(ProcesoFirma).insert_one(document)
    return _mongo_to_namespace(document)


def _generar_folio_firmx(test_mode=True):
    prefix = "FXP" if test_mode else "FX"
    try:
        db = _mongo_database()
        # Usar find_one_and_update para asegurar atomicidad de la secuencia
        # return_document=True equivale a ReturnDocument.AFTER
        res = db.secuencias.find_one_and_update(
            {'_id': 'folio_firmx'},
            {'$inc': {'valor': 1}},
            upsert=True,
            return_document=True
        )
        valor = res.get('valor', 1)
    except Exception as e:
        print(f"Error generando folio FIRMX: {e}")
        # Fallback simple basado en timestamp si falla la secuencia atómica
        valor = int(timezone.now().timestamp())
    
    return f"{prefix}-{str(valor).zfill(10)}"


def _check_pin_colaborador(colaborador, pin):
    return bool(colaborador and check_password(pin or '', getattr(colaborador, 'pin_hash', '')))


def _otp_es_valido(otp_record, code_ingresado):
    expires_at = _datetime_for_compare(getattr(otp_record, 'expires_at', None))
    return bool(
        otp_record
        and getattr(otp_record, 'otp_code', '') == str(code_ingresado or '')
        and expires_at is not None
        and timezone.now() <= expires_at
    )


def home_redirect(request):
    if request.session.get('owner_email'):
        return redirect('portal_dashboard')
    return redirect('portal_login')


def _generar_otp_mongo(email):
    otp_code = str(uuid.uuid4().int)[-6:]
    otp_record, _ = _mongo_update_or_insert_by_query(
        OTPLogin,
        {'email': email},
        {
            'otp_code': otp_code,
            'expires_at': _datetime_for_mongo(timezone.now() + timedelta(minutes=15)),
        },
    )
    return otp_record


def _asegurar_admin_maestro():
    admin = _mongo_find_one(AdministradorPortal, {'email': 'pjimenezb@raloy.com.mx'})
    if admin is None:
        return _mongo_insert_model(
            AdministradorPortal,
            {
                'email': 'pjimenezb@raloy.com.mx',
                'configuracion_dashboard': {},
                'es_superadmin': True,
            },
        )

    if not getattr(admin, 'es_superadmin', False):
        _mongo_update_document(AdministradorPortal, admin, {'es_superadmin': True})
    return admin


@csrf_exempt
def recibir_documento_n8n(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)

    pdf_file = request.FILES.get('pdf_file')
    if not pdf_file:
        return JsonResponse({"error": "Archivo PDF requerido."}, status=400)

    if request.method == 'POST':
        try:
            data = json.loads(request.POST.get('data') or '{}')
            ref_id = data['reference_id']
            firmantes = _normalizar_firmantes(data.get('firmantes'))
            if not firmantes:
                return JsonResponse({"error": "Se requiere al menos un firmante."}, status=400)
            view_info = data.get('view_info', 'file')
            summary_data = _json_or_default(data.get('summary_data', {}), {})
            owner_email = data.get('owner', '')
            exec_mode = str(data.get('exec', 'normal') or 'normal').lower()
            dir_drive = str(data.get('dir') or data.get('folder_id') or '').strip()
            if exec_mode == 'form':
                dir_drive = str(data.get('pdfs_folder_id') or dir_drive or _drive_pdfs_folder_id()).strip()
                summary_data.setdefault('formatos_folder_id', data.get('formatos_folder_id') or _drive_formatos_folder_id())
                summary_data.setdefault('pdfs_folder_id', dir_drive)
            elif not dir_drive:
                dir_drive = str(data.get('api_pdfs_folder_id') or _drive_api_pdfs_folder_id()).strip()
                summary_data.setdefault('api_pdfs_folder_id', dir_drive)
            summary_data.setdefault('drive_storage_policy', data.get('storage_policy') or DRIVE_STORAGE_POLICY)

            # Persistir el id de Drive del PDF de origen que ya subió n8n, para poder
            # rehidratar el archivo siempre aunque se pierda el temporal local.
            source_drive_file_id = str(
                data.get('source_drive_file_id')
                or data.get('drive_file_id')
                or data.get('file_id')
                or data.get('pdf_file_id')
                or summary_data.get('source_drive_file_id')
                or ''
            ).strip()
            if source_drive_file_id:
                summary_data.setdefault('source_drive_file_id', source_drive_file_id)
                summary_data.setdefault(
                    'source_pdf_filename',
                    data.get('source_pdf_filename') or data.get('filename') or f"{ref_id}.pdf",
                )

            document_variables = _json_or_default(data.get('variables_asignadas', data.get('document_variables', {})), {})

            for f in firmantes:
                if 'token_firmante' not in f: f['token_firmante'] = str(uuid.uuid4())

            original_ref_id = ref_id
            match = re.search(r'^(.*?-)(\d+)$', ref_id)
            if match:
                base_name, num_str = match.group(1), match.group(2)
                num_len, current_num = len(num_str), int(num_str)
                while _mongo_find_one(ProcesoFirma, {'reference_id': ref_id}) is not None:
                    current_num += 1
                    ref_id = f"{base_name}{str(current_num).zfill(num_len)}"
            else:
                counter = 1
                while _mongo_find_one(ProcesoFirma, {'reference_id': ref_id}) is not None:
                    ref_id = f"{original_ref_id}-{counter}"
                    counter += 1

            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
            file_path = os.path.join(settings.MEDIA_ROOT, f"{ref_id}.pdf")
            with open(file_path, 'wb+') as destination:
                for chunk in pdf_file.chunks(): destination.write(chunk)

            proceso = _crear_proceso_firma_mongo(
                reference_id=ref_id, pdf_path=file_path, firmantes=firmantes,
                indice_actual=1, view_info=view_info, summary_data=summary_data,
                owner_email=owner_email, dir_drive=dir_drive, exec_mode=exec_mode,
                document_variables=document_variables
            )

            primer_firmante = firmantes[0]
            link_firma = f"https://dsign.raloy.com.mx/firmar/{proceso.token_acceso}/{primer_firmante.get('token_firmante', '')}/"
            try:
                tracked_post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                              json={"email": primer_firmante.get('email'), "nombre": primer_firmante.get('nombre'),
                                    "link": link_firma,
                                    "mensaje": f"Raloy solicita tu firma electrónica para el documento {ref_id}."},
                              timeout=20)
            except Exception as e:
                print(f"Error en N8N_WEBHOOK_NOTIFICAR_CORREO: {e}")
            crear_notificacion_firma(primer_firmante.get('email'), ref_id, f"Raloy solicita tu firma electrónica para el documento {ref_id}.")

            if owner_email:
                link_trazabilidad = f"https://dsign.raloy.com.mx/trazabilidad/{proceso.token_acceso}/"
                try:
                    tracked_post(N8N_WEBHOOK_NOTIFICAR_OWNER,
                                  json={"email": owner_email, "reference_id": ref_id, "link": link_trazabilidad},
                                  timeout=20)
                except Exception as e:
                    print(f"Error en N8N_WEBHOOK_NOTIFICAR_OWNER: {e}")
                crear_notificacion_firma(owner_email, ref_id, f"Has iniciado el proceso de firma para {ref_id}.")

            return JsonResponse({"status": "success", "msg": "Documento recibido.", "folio_asignado": ref_id})
        except Exception as e:
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=400)


def vista_firma_ui(request, token, firmante_token=None):
    proceso = _get_proceso_por_token_or_404(token)
    firmantes = _normalizar_firmantes(proceso.firmantes)
    summary_data = _json_or_default(proceso.summary_data, {})
    valores_capturados = _json_or_default(proceso.valores_capturados, {})
    indice_turno = _indice_pendiente_actual(proceso, firmantes)
    if not summary_data.get('firmx_id'):
        try:
            _asegurar_proceso_pdf_local(proceso)
            summary_data = _json_or_default(proceso.summary_data, {})
        except Exception as e:
            return HttpResponse(f"<h1>No se pudo preparar el PDF.</h1><p>{e}</p>", status=500)

    pdf_available = _proceso_pdf_puede_servirse(proceso)
    pdf_url = _proceso_pdf_url(proceso) if pdf_available else ''
    document_relations = _relaciones_documento_firma(proceso, pdf_url) if pdf_url else {}
    message_context = {'token': token, 'view_info': proceso.view_info, 'summary_data': summary_data,
                       'pdf_url': pdf_url, 'pdf_available': pdf_available, 'is_message_view': True,
                       'document_relations': json.dumps(document_relations)}

    if proceso.status == 'CANCELLED':
        message_context.update(
            {'message_icon': '⚠️', 'message_color': '#e74c3c', 'message_title': 'Documento Cancelado',
             'message_body': 'El proceso ha sido cancelado.'})
        return render(request, 'motor_firmas/firma_ui.html', message_context)

    if proceso.status == 'COMPLETED':
        message_context.update({'message_icon': '✅', 'message_color': '#10b981', 'message_title': 'Proceso Completado',
                                'message_body': 'Documento firmado en su totalidad.'})
        return render(request, 'motor_firmas/firma_ui.html', message_context)

    if not firmantes or indice_turno is None:
        message_context.update({'message_icon': '✅', 'message_color': '#10b981', 'message_title': 'Proceso Completado',
                                'message_body': 'No hay firmas pendientes para este documento.'})
        return render(request, 'motor_firmas/firma_ui.html', message_context)

    indices_turno = _indices_firmas_en_turno(firmantes, indice_turno)

    if firmante_token:
        indice_token = _indice_por_token(firmantes, firmante_token)
        if indice_token is None: return HttpResponse("<h1>Enlace inválido.</h1>")
        firmante_actual = firmantes[indice_token]
        if firmante_actual.get('fecha_firma'):
            message_context.update({'message_icon': '✓', 'message_color': '#10b981', 'message_title': 'Ya has firmado',
                                    'message_body': 'Tu firma ya ha sido capturada.'})
            return render(request, 'motor_firmas/firma_ui.html', message_context)

        if indice_token not in indices_turno:
            message_context.update(
                {'message_icon': '⏳', 'message_color': '#f39c12', 'message_title': 'Aún no es tu turno',
                 'message_body': 'Te notificaremos cuando sea tu turno.'})
            return render(request, 'motor_firmas/firma_ui.html', message_context)
    else:
        firmante_actual = firmantes[indice_turno]

    colaborador = _mongo_find_one(DirectorioFirmas, {'email': firmante_actual.get('email')})
    
    content_option = {}
    labels_map = {}
    
    # Extraer opciones directo de la Plantilla original cruzando con dir_drive
    if proceso.exec_mode == 'form' and proceso.dir_drive:
        plantillas = _mongo_find(PlantillaFormulario, {'drive_folder_id': proceso.dir_drive})
        if not plantillas:
            plantillas = _mongo_find(PlantillaFormulario, {'carpeta_firmados_id': proceso.dir_drive})
            
        plantilla_encontrada = None
        for p in plantillas:
            formato_folio = getattr(p, 'formato_folio', '')
            prefix = formato_folio.split('-0')[0] if formato_folio else ''
            if prefix and proceso.reference_id.startswith(prefix):
                plantilla_encontrada = p
                break
        if not plantilla_encontrada and plantillas:
            plantilla_encontrada = plantillas[0]
            
        plantilla_variables = getattr(plantilla_encontrada, 'variables', []) if plantilla_encontrada else []
        if plantilla_variables:
            vars_list = _json_or_default(plantilla_variables, [])
                    
            for v in vars_list:
                if isinstance(v, dict):
                    key = v.get('key')
                    if not key:
                        continue
                    labels_map[key] = v.get('label', key)
                    if v.get('type') in ('option', 'seleccionable'):
                        if 'content-option' in v:
                            content_option[key] = v['content-option']
                        elif 'content_options' in v:
                            content_option[key] = v['content_options']
                        elif 'content_option' in v:
                            content_option[key] = v['content_option']
                    
    # Fallback por si N8N lo mandó de otra forma en summary_data (Legacy)
    if not content_option and summary_data:
        co_raw = summary_data.get('content-option', summary_data.get('content_option', {}))
        if isinstance(co_raw, dict):
            content_option = co_raw
        elif isinstance(co_raw, list):
            for item in co_raw:
                if isinstance(item, dict):
                    content_option.update(item)

    campos_a_llenar = []
    if proceso.exec_mode == 'form':
        doc_vars = _json_or_default(proceso.document_variables, {})
            
        for key, em in doc_vars.items():
            if _normalizar_email(em) == _normalizar_email(firmante_actual.get('email')) and key not in valores_capturados:
                opciones = content_option.get(key)
                if isinstance(opciones, str):
                     opciones = [o.strip() for o in opciones.split(',') if o.strip()]
                elif not isinstance(opciones, list):
                     opciones = None
                
                campos_a_llenar.append({
                    'key': key,
                    'label': labels_map.get(key, key),
                    'options': opciones
                })
    campos_a_llenar.extend(
        _campos_llenado_libre(summary_data, firmante_actual.get('email'), valores_capturados)
    )

    cant_firmas = len(indices_turno)

    context = {'token': token, 'firmante_token': firmante_token or '',
               'nombre_firmante': firmante_actual.get('nombre', 'Firmante'),
               'email_firmante': firmante_actual.get('email', ''), 'view_info': proceso.view_info,
               'summary_data': summary_data,
               'pdf_url': pdf_url,
               'pdf_available': pdf_available,
               'document_relations': json.dumps(document_relations),
               'is_registered': bool(colaborador), 'campos_a_llenar': campos_a_llenar, 'is_message_view': False,
               'cant_firmas': cant_firmas}
    return render(request, 'motor_firmas/firma_ui.html', context)


@csrf_exempt
def procesar_firma(request, token, firmante_token=None):
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    ip_user = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))
    proceso = _get_proceso_por_token_or_404(token)
    if proceso.status == 'CANCELLED':
        return JsonResponse({"error": "Documento cancelado."}, status=403)

    firmantes_lista = _normalizar_firmantes(proceso.firmantes)
    indice_turno = _indice_pendiente_actual(proceso, firmantes_lista)
    if not firmantes_lista or indice_turno is None:
        _actualizar_proceso_firma_mongo(
            proceso,
            firmantes=firmantes_lista,
            indice_actual=len(firmantes_lista) + 1,
            status='COMPLETED',
        )
        return JsonResponse({"status": "success", "msg": "El proceso ya estaba completo."})

    indices_turno = _indices_firmas_en_turno(firmantes_lista, indice_turno)
    if firmante_token:
        indice_token = _indice_por_token(firmantes_lista, firmante_token)
        if indice_token not in indices_turno:
            return JsonResponse({"error": "No es tu turno."}, status=403)

    firmante_esperado = firmantes_lista[indice_turno]
    email_firmante = _normalizar_email(firmante_esperado.get('email'))
    if not email_firmante:
        return JsonResponse({"error": "El firmante actual no tiene correo configurado."}, status=400)

    variables = _json_or_default(data.get('variables', {}), {})
    campos_libres_requeridos = _campos_llenado_libre(
        _json_or_default(getattr(proceso, 'summary_data', {}) or {}, {}),
        email_firmante,
        _json_or_default(getattr(proceso, 'valores_capturados', {}) or {}, {}),
    )
    campos_faltantes = [
        campo.get('label') or campo.get('key')
        for campo in campos_libres_requeridos
        if not str(variables.get(campo.get('key')) or '').strip()
    ]
    if campos_faltantes:
        return JsonResponse({
            "error": "Completa todos los campos obligatorios antes de firmar.",
            "missing_fields": campos_faltantes,
        }, status=400)

    backup_path = None
    try:
        pin_ingresado = data.get('pin')
        if pin_ingresado:
            colaborador = _mongo_find_one(DirectorioFirmas, {'email': email_firmante})
            if not colaborador or not check_password(pin_ingresado, getattr(colaborador, 'pin_hash', '')):
                return JsonResponse({"error": "PIN incorrecto."}, status=403)
            firma_b64 = colaborador.firma_base64
        else:
            firma_b64 = data.get('firma_base64')
            if not firma_b64:
                return JsonResponse({"error": "Firma o PIN requerido."}, status=400)

        pdf_abs_path = _pdf_path_existente_para_firma(getattr(proceso, 'pdf_path', ''))
        if not pdf_abs_path:
            try:
                _asegurar_proceso_pdf_local(proceso)
            except Exception as e:
                return JsonResponse({"error": f"No se pudo preparar el PDF para certificar: {e}"}, status=400)

        pdf_abs_path = _pdf_path_existente_para_firma(getattr(proceso, 'pdf_path', ''))
        if not pdf_abs_path:
            return JsonResponse({
                "error": "No se pudo preparar el PDF para certificar. La firma no fue aplicada porque el documento de origen no está disponible."
            }, status=400)
        proceso.pdf_path = pdf_abs_path

        backup_path = f"{proceso.pdf_path}.{uuid.uuid4().hex}.bak"
        shutil.copyfile(proceso.pdf_path, backup_path)

        if variables:
            valores_capturados = _json_or_default(proceso.valores_capturados, {})
            valores_capturados.update(variables)
            proceso.valores_capturados = valores_capturados
            estampar_variables_en_pdf(proceso.pdf_path, variables)
            estampar_campos_posicionados_en_pdf(proceso.pdf_path, variables, campos_libres_requeridos)

        fecha_firma = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
        for idx in indices_turno:
            firmante = firmantes_lista[idx]
            coords = firmante.get('coordenadas')
            nombre = firmante.get('nombre') or firmante_esperado.get('nombre') or 'Firmante'
            stamp_result = estampar_firma_en_pdf(
                proceso.pdf_path,
                firma_b64,
                idx + 1,
                email_firmante,
                nombre,
                ip_user,
                coords,
                registro=data.get('registro'),
                fecha_firma=fecha_firma,
                hash_documento=data.get('hash'),
                return_metadata=True,
            )
            document_hash = stamp_result.get('hash') if isinstance(stamp_result, dict) else stamp_result
            if isinstance(stamp_result, dict) and stamp_result.get('posicion_estampada'):
                firmante['posicion_estampada'] = stamp_result['posicion_estampada']
            if firma_b64:
                firmante['firma_capturada_base64'] = firma_b64
            _copiar_evidencia_firma(firmante, data, fecha_firma, ip_user, document_hash)

        _marcar_notificaciones_firma(proceso.reference_id, email_firmante)

        siguiente_idx = _primer_indice_pendiente(firmantes_lista, 0)
        indice_actual = siguiente_idx + 1 if siguiente_idx is not None else len(firmantes_lista) + 1

        if siguiente_idx is not None:
            _actualizar_proceso_firma_mongo(
                proceso,
                firmantes=firmantes_lista,
                valores_capturados=_json_or_default(proceso.valores_capturados, {}),
                indice_actual=indice_actual,
            )
            siguiente = firmantes_lista[siguiente_idx]
            link_firma = f"https://dsign.raloy.com.mx/firmar/{proceso.token_acceso}/{siguiente.get('token_firmante', '')}/"
            try:
                tracked_post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                              json={"email": siguiente.get('email'), "nombre": siguiente.get('nombre'), "link": link_firma,
                                    "mensaje": "Es tu turno de firmar."},
                              timeout=20)
            except Exception as e:
                print(f"Error en N8N_WEBHOOK_NOTIFICAR_CORREO: {e}")
            crear_notificacion_firma(siguiente.get('email'), proceso.reference_id, "Es tu turno de firmar.")
            return JsonResponse({"status": "success", "msg": "Firma guardada."})

        _actualizar_proceso_firma_mongo(
            proceso,
            firmantes=firmantes_lista,
            valores_capturados=_json_or_default(proceso.valores_capturados, {}),
            indice_actual=indice_actual,
            status='COMPLETED',
        )

        link_trazabilidad = f"https://dsign.raloy.com.mx/trazabilidad/{proceso.token_acceso}/"

        todos_los_correos = [f.get('email') for f in firmantes_lista if f.get('email')]
        if proceso.owner_email:
            todos_los_correos.append(proceso.owner_email)

            try:
                tracked_post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                              json={"email": proceso.owner_email, "nombre": "Propietario", "link": link_trazabilidad,
                                    "mensaje": "El documento que iniciaste ha sido firmado por todos y finalizado."},
                              timeout=20)
            except Exception as e:
                print(f"Error notificando al owner por correo: {e}")
            crear_notificacion_firma(proceso.owner_email, proceso.reference_id, "El documento que iniciaste ha sido firmado por todos.")

        dominio_creador = proceso.owner_email.split('@')[1] if proceso.owner_email and '@' in proceso.owner_email else 'raloy.com.mx'
        dominios_permitidos = {dominio_creador, 'raloy.com.mx', 'consorcionova.com'}

        correos_internos = [email for email in set(todos_los_correos) if any(email.endswith(d) for d in dominios_permitidos)]
        correos = ",".join(correos_internos)

        n8n_finalization_warning = None
        with open(proceso.pdf_path, 'rb') as f:
            try:
                resp_n8n = tracked_post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                              data={"reference_id": proceso.reference_id, "status": "COMPLETED",
                                    "correos_destino": correos,
                                    **_n8n_storage_data_for_proceso(proceso),
                                    "link": link_trazabilidad}, files={
                        "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")}, timeout=30)

                n8n_error = _n8n_response_error(resp_n8n)
                if n8n_error:
                    if _n8n_error_respond_webhook_sin_usar(n8n_error):
                        n8n_finalization_warning = _registrar_advertencia_finalizacion_n8n(proceso, n8n_error)
                    else:
                        return JsonResponse({"error": f"N8N no pudo finalizar el PDF: {n8n_error}"}, status=502)
                else:
                    _registrar_pdf_final_drive_id(proceso, resp_n8n)
            except Exception as e:
                if _n8n_error_respond_webhook_sin_usar(e):
                    n8n_finalization_warning = _registrar_advertencia_finalizacion_n8n(proceso, e)
                else:
                    return JsonResponse({"error": f"Error en N8N_WEBHOOK_FINALIZAR_PROCESO: {e}"}, status=502)

        if n8n_finalization_warning:
            return JsonResponse({
                "status": "success",
                "warning": "El PDF fue firmado y finalizado localmente, pero N8N devolvio una advertencia de configuracion.",
                "n8n_warning": n8n_finalization_warning,
            })

        return JsonResponse({"status": "success"})
    except Exception as e:
        if backup_path and os.path.exists(backup_path):
            try:
                shutil.copyfile(backup_path, proceso.pdf_path)
            except Exception as restore_error:
                print(f"Error restaurando PDF tras fallo de firma: {restore_error}")
        error_details = traceback.format_exc()
        print(error_details)
        return JsonResponse({"error": f"Error interno en el sistema al certificar: {str(e)}"}, status=500)
    finally:
        if backup_path and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass


def _firmx_sync_status(clean_id, force=False):
    """
    Sincroniza el estado de un documento con FIRMX y actualiza la base de datos local.
    Retorna (success, data_or_error_message).
    """
    try:
        clean_id = str(clean_id or '').strip()
        db = _mongo_database()
        proceso_actual = db.motor_firmas_procesofirma.find_one({"summary_data.firmx_id": clean_id})
        proceso_summary_data = _json_or_default(proceso_actual.get('summary_data', {}), {}) if proceso_actual else {}
        local_status = str(proceso_actual.get('status') or '').upper() if proceso_actual else ''
        if proceso_actual and local_status == 'CANCELLED':
            return True, {
                "skipped": True,
                "reason": "Documento FIRMX cancelado localmente; no se consulta al proveedor.",
                "local_status": proceso_actual.get('status'),
                "firmx_response": proceso_summary_data.get('firmx_response', {}),
            }
        if proceso_actual and local_status == 'COMPLETED' and not force:
            return True, {
                "skipped": True,
                "reason": "Documento FIRMX completado; la sincronización automática no consulta al proveedor.",
                "local_status": proceso_actual.get('status'),
                "firmx_response": proceso_summary_data.get('firmx_response', {}),
            }

        firmx_base_url = _firmx_base_url_desde_summary(proceso_summary_data) or None
        url = _firmx_url(
            f'/documents/api/{clean_id}',
            base_url=firmx_base_url,
        )
        headers = _firmx_headers(base_url=firmx_base_url)
        response = requests.get(url, headers=headers, timeout=_firmx_timeout())
        response_data = _json_response_from_requests(response)
        
        if not 200 <= response.status_code < 300:
            return False, f"FIRMX Error {response.status_code}: {response_data.get('error') or 'Error desconocido'}"

        # FIRMX puede devolver la data directamente, en un campo 'data', o en 'data' como lista
        firmx_data = response_data.get('data', response_data)
        if isinstance(firmx_data, list) and len(firmx_data) > 0:
            firmx_data = firmx_data[0]
            
        if not isinstance(firmx_data, dict):
            return False, "Estructura de datos de FIRMX inesperada (no es un objeto)."

        # Intentar encontrar el objeto documento si está anidado
        doc_obj = firmx_data.get('document') if isinstance(firmx_data.get('document'), dict) else firmx_data

        # Mapear estado del documento
        status_key = 'document_status' if 'document_status' in doc_obj else ('status' if 'status' in doc_obj else 'state')
        firmx_status_raw = str(doc_obj.get(status_key) or 'waiting_for_signatures').lower()
        
        local_status = 'FIRMX_WAITING'
        if firmx_status_raw in ['completed', 'signed', 'finalized', 'finalizado', 'completado', 'firmado']:
            local_status = 'COMPLETED'
        elif firmx_status_raw in ['cancelled', 'rejected', 'deleted', 'cancelado', 'rechazado', 'eliminado']:
            local_status = 'CANCELLED'
            
        # Sincronizar firmantes - Búsqueda robusta
        firmantes_firmx = (
            doc_obj.get('document_signers') or 
            doc_obj.get('signers') or 
            doc_obj.get('signatures') or 
            doc_obj.get('documents_signers') or 
            []
        )
        if not firmantes_firmx and 'data' in firmx_data and isinstance(firmx_data['data'], dict):
            # Probar un nivel más profundo
            d2 = firmx_data['data']
            firmantes_firmx = (
                d2.get('document_signers') or 
                d2.get('signers') or 
                d2.get('signatures') or 
                d2.get('documents_signers') or 
                []
            )

        # URLs de documentos firmados y certificados (FIRMX a veces los entrega con espacios)
        def _clean_url(u):
            return u.strip() if isinstance(u, str) else u
        file_url = _clean_url(doc_obj.get('file_url'))
        cert_url = _clean_url(doc_obj.get('file_url_certificate'))
        download_file_url = _clean_url(doc_obj.get('download_file_url'))
        download_cert_url = _clean_url(doc_obj.get('download_certificate_url'))
        archivo_url = _clean_url(doc_obj.get('archivo') or doc_obj.get('file'))

        # Actualizar en DB
        update_fields = {
            "status": local_status,
            "summary_data.firmx_status_raw": firmx_status_raw,
            "summary_data.firmx_response": response_data,
            "updated_at": _datetime_for_mongo()
        }
        if file_url:
            update_fields["summary_data.firmx_file_url"] = file_url
        if cert_url:
            update_fields["summary_data.firmx_certificate_url"] = cert_url
        if download_file_url:
            update_fields["summary_data.firmx_download_file_url"] = download_file_url
        if download_cert_url:
            update_fields["summary_data.firmx_download_certificate_url"] = download_cert_url
        if archivo_url:
            update_fields["summary_data.firmx_archivo_url"] = archivo_url

        db.motor_firmas_procesofirma.update_one(
            {"summary_data.firmx_id": clean_id},
            {"$set": update_fields}
        )

        if firmantes_firmx:
            proceso_doc = db.motor_firmas_procesofirma.find_one({"summary_data.firmx_id": clean_id})
            if proceso_doc:
                firmantes_locales = _normalizar_firmantes(proceso_doc.get('firmantes', []))
                hubo_cambio = False
                for f_fx in firmantes_firmx:
                    email_fx = f_fx.get('email')
                    nombre_fx = f_fx.get('name')
                    if not email_fx: continue
                    
                    f_status = str(f_fx.get('status') or f_fx.get('state') or '').lower()
                    # Mapeo flexible de estado de firma
                    esta_firmado = (
                        f_status in ['signed', 'completed', 'finalized', 'firmado', 'firmada', 'completada'] or 
                        f_fx.get('signed_at') or 
                        f_fx.get('signed') is True
                    )
                    
                    for f_loc in firmantes_locales:
                        if _normalizar_email(f_loc.get('email')) == _normalizar_email(email_fx):
                            # Sincronizar nombre si viene de FIRMX
                            if nombre_fx and f_loc.get('nombre') != nombre_fx:
                                f_loc['nombre'] = nombre_fx
                                hubo_cambio = True

                            if esta_firmado:
                                # Intentar obtener la fecha real de FIRMX
                                fecha_real = f_fx.get('signed_at') or f_fx.get('updated_at')
                                if not fecha_real:
                                    # Fallback a digital_fingerprints
                                    fps = doc_obj.get('digital_fingerprints') or []
                                    for fp in fps:
                                        if email_fx in fp and ("firmó" in fp.lower() or "signed" in fp.lower()):
                                            import re
                                            match_f = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2})', fp)
                                            if match_f:
                                                fecha_real = match_f.group(1)
                                                break
                                
                                if not fecha_real:
                                    fecha_real = _datetime_for_mongo().isoformat()
                                
                                if not f_loc.get('fecha_firma'):
                                    f_loc['fecha_firma'] = fecha_real
                                    hubo_cambio = True
                
                if hubo_cambio:
                    db.motor_firmas_procesofirma.update_one(
                        {"_id": proceso_doc['_id']},
                        {"$set": {"firmantes": firmantes_locales}}
                    )

        return True, response_data

    except Exception as e:
        return False, str(e)


def vista_trazabilidad(request, token):
    proceso = _get_proceso_por_token_or_404(token)
    summary_data = getattr(proceso, 'summary_data', {})
    
    # La trazabilidad es una acción explícita del usuario: aquí sí refrescamos
    # FIRMX para renovar URLs firmadas vencidas en documentos completados.
    # Cancelados siguen sin consultar al proveedor.
    es_firmx = bool(summary_data.get('firmx_id'))
    sync_error = None
    pdf_error = None
    if es_firmx and str(getattr(proceso, 'status', '') or '').upper() != 'CANCELLED':
        firmx_id = summary_data.get('firmx_id')
        success, error_msg = _firmx_sync_status(
            firmx_id,
            force=str(getattr(proceso, 'status', '') or '').upper() == 'COMPLETED',
        )
        if success:
            # Refrescar el objeto proceso tras la actualización en DB
            proceso = _get_proceso_por_token_or_404(token)
            summary_data = getattr(proceso, 'summary_data', {})
        else:
            sync_error = error_msg

    firmantes = _normalizar_firmantes(getattr(proceso, 'firmantes', []))
    if es_firmx:
        # Ordenar dinámicamente: firmados primero (por fecha), luego pendientes
        firmantes.sort(key=lambda x: (0 if x.get('fecha_firma') else 1, str(x.get('fecha_firma') or '')))
        proceso.firmantes = firmantes

    total_firmas = len(firmantes)
    firmas_hechas = sum(1 for firmante in firmantes if firmante.get('fecha_firma'))
    admin_email = request.session.get('admin_email')
    admin_obj = _mongo_find_one(AdministradorPortal, {'email': _normalizar_email(admin_email)}) if admin_email else None
    admin_tiene_acceso = _admin_tiene_acceso_proceso(admin_obj, proceso)

    owner_email = request.session.get('owner_email')
    owner_tiene_acceso = _validar_acceso_owner(proceso, owner_email) if owner_email else False
    can_send_reminders = bool(
        (admin_obj is not None or owner_tiene_acceso)
        and proceso.status in ['PROCESSING', 'FIRMX_WAITING']
    )

    es_firmx = bool(summary_data.get('firmx_id'))
    qr_firmx_url = ""
    qrs_firmx = []
    qrs_raw = summary_data.get('qrs', [])
    if es_firmx:
        if summary_data.get('qr_local_path'):
            qr_firmx_url = f"{settings.MEDIA_URL}{summary_data['qr_local_path']}"
        
        if qrs_raw:
            for q in qrs_raw:
                qrs_firmx.append({
                    'email': q.get('email', 'Firmante'),
                    'url': f"{settings.MEDIA_URL}{q['qr_local_path']}" if q.get('qr_local_path') else "",
                    'link': q.get('url_qr_code', '')
                })

    # URLs FIRMX para visualizar documento original y certificado
    firmx_file_url = summary_data.get('firmx_file_url') or ''
    firmx_certificate_url = summary_data.get('firmx_certificate_url') or ''
    firmx_download_file_url = summary_data.get('firmx_download_file_url') or ''
    firmx_download_certificate_url = summary_data.get('firmx_download_certificate_url') or ''

    if not es_firmx:
        try:
            _asegurar_proceso_pdf_local(proceso)
        except Exception as e:
            pdf_error = str(e)

    pdf_url_local = _proceso_pdf_url(proceso) if _proceso_pdf_puede_servirse(proceso) else ''
    # En modo FIRMX, el documento original a mostrar es el devuelto por FIRMX (file_url);
    # el certificado/final es file_url_certificate.
    pdf_url_original = firmx_file_url if es_firmx and firmx_file_url else pdf_url_local
    pdf_url_certificate = firmx_certificate_url if es_firmx and firmx_certificate_url else pdf_url_local
    pdf_available = bool(pdf_url_original or pdf_url_certificate or pdf_url_local)

    return render(request, 'motor_firmas/trazabilidad.html',
                  {
                      'proceso': proceso,
                      'pdf_url': pdf_url_local,
                      'pdf_url_original': pdf_url_original,
                      'pdf_url_certificate': pdf_url_certificate,
                      'pdf_available': pdf_available,
                      'firmx_file_url': firmx_file_url,
                      'firmx_certificate_url': firmx_certificate_url,
                      'firmx_download_file_url': firmx_download_file_url,
                      'firmx_download_certificate_url': firmx_download_certificate_url,
                      'pdf_error': pdf_error,
                      'total_firmas': total_firmas,
                      'firmas_hechas': firmas_hechas,
                      'can_send_reminders': can_send_reminders,
                      'admin_can_adjust': bool(admin_tiene_acceso and proceso.status == 'COMPLETED' and not es_firmx),
                      'es_firmx': es_firmx,
                      'qr_firmx_url': qr_firmx_url,
                      'qrs_firmx': qrs_firmx,
                      'sync_error': sync_error,
                  })


def vista_trazabilidad_qr(request, codigo):
    try:
        payload = signing.loads(
            codigo,
            salt=QR_TRAZABILIDAD_SALT,
            max_age=QR_TRAZABILIDAD_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired:
        return HttpResponse("El codigo QR de trazabilidad ha expirado.", status=410)
    except signing.BadSignature:
        return HttpResponse("El codigo QR de trazabilidad no es valido.", status=403)

    token = payload.get('token')
    if not token:
        return HttpResponse("El codigo QR de trazabilidad no contiene un proceso valido.", status=403)
    return redirect('vista_trazabilidad', token=token)


def ver_pdf_proceso(request, token):
    proceso = _get_proceso_por_token_or_404(token)
    summary_data = getattr(proceso, 'summary_data', {}) or {}

    firmx_id = summary_data.get('firmx_id')
    if firmx_id:
        response = _firmx_pdf_response(proceso, token=token)
        if response:
            return response

    try:
        _asegurar_proceso_pdf_local(proceso)
    except Exception as exc:
        return HttpResponse(f"No se pudo preparar el PDF: {exc}", status=502)

    abs_path = _media_abs_path(getattr(proceso, 'pdf_path', ''))
    if not abs_path or not os.path.exists(abs_path):
        return HttpResponse("El PDF no esta disponible localmente y no hay ID de Drive para recuperarlo.", status=404)

    filename = _safe_pdf_filename(f"{getattr(proceso, 'reference_id', 'documento')}.pdf")
    return FileResponse(open(abs_path, 'rb'), content_type='application/pdf', filename=filename)


def _url_firmada_expirada(url, now=None):
    try:
        query = parse_qs(urlparse(str(url or '')).query)
    except Exception:
        return False

    now = now or timezone.now()
    amz_date = (query.get('X-Amz-Date') or query.get('x-amz-date') or [''])[0]
    amz_expires = (query.get('X-Amz-Expires') or query.get('x-amz-expires') or [''])[0]
    if amz_date and amz_expires:
        try:
            issued_at = datetime.strptime(amz_date, '%Y%m%dT%H%M%SZ').replace(tzinfo=datetime_timezone.utc)
            expires_at = issued_at + timedelta(seconds=int(amz_expires))
            return now >= expires_at
        except (TypeError, ValueError):
            return False

    expires = (query.get('Expires') or query.get('expires') or [''])[0]
    if expires:
        try:
            expires_at = datetime.fromtimestamp(int(expires), tz=datetime_timezone.utc)
            return now >= expires_at
        except (TypeError, ValueError, OSError):
            return False

    return False


def _proceso_pdf_local_response(proceso):
    abs_path = _media_abs_path(getattr(proceso, 'pdf_path', ''))
    if not abs_path or not os.path.exists(abs_path):
        return None

    filename = _safe_pdf_filename(f"{getattr(proceso, 'reference_id', 'documento')}.pdf")
    response = FileResponse(open(abs_path, 'rb'), content_type='application/pdf', filename=filename)
    response['Cache-Control'] = 'no-store, max-age=0'
    return response


def _firmx_pdf_response(proceso, token=None):
    summary_data = getattr(proceso, 'summary_data', {}) or {}
    firmx_id = summary_data.get('firmx_id')
    if not firmx_id:
        return None

    success, _ = _firmx_sync_status(firmx_id, force=True)
    if success:
        proceso = _get_proceso_por_token_or_404(token or getattr(proceso, 'token_acceso', ''))
        summary_data = getattr(proceso, 'summary_data', {}) or {}
        firmx_id = summary_data.get('firmx_id') or firmx_id

    local_response = _proceso_pdf_local_response(proceso)
    url = _firmx_url_documento_visible(proceso)
    if not url or not str(url).lower().startswith(('http://', 'https://')):
        return local_response

    last_error = ''
    try:
        download = requests.get(url, timeout=_firmx_timeout(), allow_redirects=True)
        content = download.content or b''
        content_type = download.headers.get('content-type', '').lower()
        looks_pdf = content.startswith(b'%PDF') or 'application/pdf' in content_type
        if download.status_code in (401, 403) or not looks_pdf:
            firmx_base_url = _firmx_base_url_desde_summary(summary_data) or _firmx_base_url_desde_api_url(url)
            download = requests.get(url, headers=_firmx_headers(base_url=firmx_base_url), timeout=_firmx_timeout(), allow_redirects=True)
            content = download.content or b''
            content_type = download.headers.get('content-type', '').lower()
            looks_pdf = content.startswith(b'%PDF') or 'application/pdf' in content_type
    except Exception as exc:
        last_error = str(exc)
        download = None
        content = b''
        looks_pdf = False

    if download is not None and 200 <= download.status_code < 300 and looks_pdf:
        filename = _safe_pdf_filename(f"{getattr(proceso, 'reference_id', 'documento')}.pdf")
        response = HttpResponse(content, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Cache-Control'] = 'no-store, max-age=0'
        return response

    if local_response:
        return local_response

    if download is not None:
        detail = ''
        try:
            detail = download.text[:300].strip()
        except Exception:
            detail = ''
        base_url = _firmx_base_url_desde_summary(summary_data) or 'endpoint FIRMX configurado'
        reference_id = getattr(proceso, 'reference_id', '') or 'documento'
        message = (
            f"No se pudo obtener el PDF FIRMX vigente para {reference_id} "
            f"(ID FIRMX: {firmx_id}) desde {base_url}: HTTP {download.status_code}."
        )
        if detail:
            message = f"{message} {detail}"
        else:
            message = f"{message} FIRMX no devolvio detalle del error."
        if download.status_code in (401, 403):
            message = f"{message} Revisa que la API Key guardada corresponda a ese endpoint FIRMX."
        response = HttpResponse(message, status=502)
        response['Cache-Control'] = 'no-store, max-age=0'
        return response

    response = HttpResponse(f"No se pudo obtener el PDF FIRMX por API: {last_error}", status=502)
    response['Cache-Control'] = 'no-store, max-age=0'
    return response


def _firmx_url_documento_visible(proceso):
    summary_data = getattr(proceso, 'summary_data', {}) or {}
    for key in (
        'firmx_file_url',
        'firmx_download_file_url',
        'firmx_certificate_url',
        'firmx_download_certificate_url',
        'firmx_archivo_url',
    ):
        url = summary_data.get(key)
        if isinstance(url, str) and url.strip() and not _url_firmada_expirada(url):
            return url.strip()
    return _media_url_for_path(proceso.pdf_path)


def portal_ver_documento(request, token):
    proceso = _get_proceso_por_token_or_404(token)
    acceso = _resolver_acceso_proceso(request, proceso)
    if not acceso:
        if request.session.get('owner_email') or request.session.get('admin_email'):
            return HttpResponse("<h1>No tienes acceso a este documento.</h1>", status=403)
        return redirect('portal_login')

    summary_data = getattr(proceso, 'summary_data', {}) or {}
    firmx_id = summary_data.get('firmx_id')
    if not firmx_id or proceso.status != 'COMPLETED':
        return redirect('vista_trazabilidad', token=token)

    success, _ = _firmx_sync_status(firmx_id, force=True)
    if success:
        proceso = _get_proceso_por_token_or_404(token)

    return redirect(_firmx_url_documento_visible(proceso))


def generar_qr_trazabilidad(request, token):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "Sesion no valida."}, status=403)

    proceso = _get_proceso_por_token_or_404(token)
    if not _validar_acceso_owner(proceso, owner_email):
        return JsonResponse({"error": "No tienes acceso a este documento."}, status=403)

    qr_payload = _crear_payload_qr_trazabilidad(proceso)
    return JsonResponse({
        "status": "success",
        "reference_id": proceso.reference_id,
        "link": qr_payload['link'],
        "hash": qr_payload['hash'],
        "expires_at": qr_payload['expires_at'].isoformat(),
        "expires_at_label": qr_payload['expires_at_label'],
        "max_age_seconds": qr_payload['max_age_seconds'],
    })


def enviar_qr_trazabilidad(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Metodo no permitido."}, status=405)

    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "Sesion no valida."}, status=403)

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON invalido."}, status=400)

    token = data.get('token')
    proceso = _get_proceso_por_token_or_404(token)
    if not _validar_acceso_owner(proceso, owner_email):
        return JsonResponse({"error": "No tienes acceso a este documento."}, status=403)

    correos = _parse_email_list(data.get('correos'))
    if not correos:
        return JsonResponse({"error": "Agrega al menos un correo valido."}, status=400)

    qr_payload = _crear_payload_qr_trazabilidad(proceso)
    payload_n8n = {
        "correos_destino": ",".join(correos),
        "reference_id": proceso.reference_id,
        "status": proceso.status,
        "owner_email": owner_email,
        "link": qr_payload['link'],
        "hash": qr_payload['hash'],
        "expires_at": qr_payload['expires_at_label'],
        "qr_image": data.get('qr_image', ''),
    }

    try:
        response = tracked_post(N8N_WEBHOOK_ENVIAR_QR, json=payload_n8n, timeout=20)
        n8n_error = _n8n_response_error(response)
        if n8n_error:
            return JsonResponse({
                "error": "N8N no pudo enviar el correo del QR.",
                "detail": n8n_error,
            }, status=502)
    except Exception as e:
        return JsonResponse({"error": f"Error contactando N8N: {e}"}, status=502)

    return JsonResponse({"status": "success", "sent_to": correos, "n8n_status": response.status_code})


@csrf_exempt
def reenviar_firma_trazabilidad(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Metodo no permitido."}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON invalido."}, status=400)

    doc = _mongo_find_proceso_by_token(data.get('token'))
    if not doc:
        return JsonResponse({"error": "Documento no encontrado."}, status=404)

    admin_email = _normalizar_email(request.session.get('admin_email'))
    admin_actual = _mongo_find_one(AdministradorPortal, {'email': admin_email}) if admin_email else None
    owner_email = _normalizar_email(request.session.get('owner_email'))
    owner_tiene_acceso = _validar_acceso_owner(doc, owner_email) if owner_email else False
    if admin_actual is None and not owner_tiene_acceso:
        return JsonResponse({"error": "No tienes permiso sobre este documento."}, status=403)

    summary_data = getattr(doc, 'summary_data', {}) or {}
    es_firmx = bool(summary_data.get('firmx_id'))
    estado = str(getattr(doc, 'status', '') or '').upper()
    if es_firmx:
        if estado not in ('PROCESSING', 'FIRMX_WAITING'):
            return JsonResponse({"error": "Solo se puede reenviar en documentos FIRMX pendientes."}, status=400)
    elif estado != 'PROCESSING':
        return JsonResponse({"error": "Solo se puede reenviar en documentos en proceso."}, status=400)

    firmantes = _normalizar_firmantes(getattr(doc, 'firmantes', []))
    firmante_token = str(data.get('firmante_token') or '').strip()
    email = _normalizar_email(data.get('email'))
    idx = _indice_por_token(firmantes, firmante_token) if firmante_token else None
    if idx is None and email:
        for i, firmante_item in enumerate(firmantes):
            if _normalizar_email(firmante_item.get('email')) == email and not firmante_item.get('fecha_firma'):
                idx = i
                break
    if idx is None or idx < 0 or idx >= len(firmantes):
        return JsonResponse({"error": "Firmante pendiente no encontrado."}, status=404)

    firmante = firmantes[idx]
    if firmante.get('fecha_firma'):
        return JsonResponse({"error": "Ese firmante ya completo su firma."}, status=400)

    actor_email = admin_email if admin_actual is not None else owner_email
    if es_firmx:
        qrs_map = {
            _normalizar_email(q.get('email')): q.get('url_qr_code')
            for q in summary_data.get('qrs', [])
            if q.get('email')
        }
        url_firma = qrs_map.get(_normalizar_email(firmante.get('email'))) or summary_data.get('url_qr_code') or ''
        if not url_firma:
            return JsonResponse({"error": "No hay enlace de firma FIRMX disponible para este firmante."}, status=400)

        payload_n8n = {
            "correos_destino": firmante.get('email'),
            "reference_id": getattr(doc, 'reference_id', 'N/A'),
            "url_firma": url_firma,
            "subject": "Firma Digital Raloy - FIRMX",
            "titulo": "Firma Digital Raloy - FIRMX",
            "texto_boton": "IR A FIRMA",
            "mensaje": "Se requiere su firma para el documento: " + summary_data.get('document_name', 'Documento FIRMX'),
        }
        webhook_url = N8N_WEBHOOK_NOTIFICAR_FIRMX
    else:
        if not firmante.get('token_firmante'):
            firmante['token_firmante'] = str(uuid.uuid4())
        link_firma = f"{PUBLIC_BASE_URL}/firmar/{doc.token_acceso}/{firmante.get('token_firmante')}/"
        payload_n8n = {
            "email": firmante.get('email'),
            "nombre": firmante.get('nombre'),
            "link": link_firma,
            "mensaje": f"Reenvio de solicitud de firma para el documento {doc.reference_id}.",
            "reenviado": True,
        }
        webhook_url = N8N_WEBHOOK_NOTIFICAR_CORREO

    try:
        response = tracked_post(webhook_url, json=payload_n8n, timeout=20)
        n8n_error = _n8n_response_error(response)
        if n8n_error:
            return JsonResponse({"error": f"N8N no confirmo el envio: {n8n_error}"}, status=502)
    except Exception as e:
        return JsonResponse({"error": f"No se pudo reenviar el correo: {e}"}, status=502)

    fecha_reenvio = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
    reenvios = _json_or_default(firmante.get('reenvios_correo', []), [])
    reenvios.append({
        'fecha': fecha_reenvio,
        'por': actor_email,
        'email': firmante.get('email'),
        'origen': 'trazabilidad',
        'tipo_documento': 'firmx' if es_firmx else 'normal',
    })
    firmante['reenvios_correo'] = reenvios
    firmante['ultimo_reenvio_correo'] = fecha_reenvio
    firmante['ultimo_reenvio_por'] = actor_email
    firmante['ultimo_reenvio_tipo'] = 'correo'

    if es_firmx:
        api_steps = _json_or_default(summary_data.get('api_steps', []), [])
        api_steps.append({
            "step": "Reenvio de correo desde trazabilidad",
            "timestamp": _datetime_for_mongo().isoformat(),
            "status": "success",
            "details": f"Correo reenviado a {firmante.get('email')} por {actor_email}",
        })
        summary_data['api_steps'] = api_steps
        _actualizar_proceso_firma_mongo(doc, firmantes=firmantes, summary_data=summary_data)
    else:
        _actualizar_proceso_firma_mongo(doc, firmantes=firmantes)

    crear_notificacion_firma(
        firmante.get('email'),
        doc.reference_id,
        f"Reenvio de solicitud de firma para {doc.reference_id}."
    )
    return JsonResponse({"status": "success", "msg": "Solicitud de firma reenviada.", "fecha": fecha_reenvio})


def _vista_ajustar_firmas(request, token, rol_requerido):
    proceso = _get_proceso_por_token_or_404(token)
    acceso = _resolver_acceso_proceso(request, proceso, rol_requerido)
    if not acceso:
        if rol_requerido == 'admin' and request.session.get('admin_email'):
            return HttpResponse("<h1>No tienes acceso a este documento.</h1>", status=403)
        if rol_requerido == 'owner' and request.session.get('owner_email'):
            return HttpResponse("<h1>No tienes acceso a este documento.</h1>", status=403)
        if rol_requerido == 'admin':
            return redirect('admin_login')
        return redirect('portal_login')

    if proceso.status != 'COMPLETED':
        return HttpResponse("<h1>El documento debe estar cerrado para ajustar firmas.</h1>", status=403)

    if (getattr(proceso, 'summary_data', {}) or {}).get('firmx_id'):
        return HttpResponse("<h1>Los documentos FIRMX finalizados se visualizan directamente desde FIRMX y no permiten ajuste de firmas.</h1>", status=403)

    try:
        _asegurar_proceso_pdf_local(proceso)
    except Exception as e:
        return HttpResponse(f"<h1>No se pudo preparar el PDF.</h1><p>{e}</p>", status=500)

    firmantes = _normalizar_firmantes(getattr(proceso, 'firmantes', []))
    return_url = '/admin-portal/dashboard/' if rol_requerido == 'admin' else '/portal/dashboard/'
    context = {
        'proceso': proceso,
        'rol': rol_requerido,
        'actor_email': acceso['email'],
        'return_url': return_url,
        'pdf_url': f"{_media_url_for_path(proceso.pdf_path)}?v={int(timezone.now().timestamp())}",
        'firmantes_json': json.dumps(_datos_ajuste_firmantes(firmantes), ensure_ascii=False),
    }
    if rol_requerido == 'owner':
        context['marca_portal'] = _marca_por_email(acceso['email'])
    return render(request, 'motor_firmas/ajustar_firmas.html', context)


@ensure_csrf_cookie
def portal_ajustar_firmas(request, token):
    return _vista_ajustar_firmas(request, token, 'owner')


@ensure_csrf_cookie
def admin_ajustar_firmas(request, token):
    return _vista_ajustar_firmas(request, token, 'admin')


@csrf_exempt
def guardar_ajuste_firmas(request, token):
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    proceso = _get_proceso_por_token_or_404(token)
    acceso = _resolver_acceso_proceso(request, proceso)
    if not acceso:
        return JsonResponse({"error": "No tienes acceso a este documento."}, status=403)

    if proceso.status != 'COMPLETED':
        return JsonResponse({"error": "El documento debe estar cerrado para ajustar firmas."}, status=400)

    if (getattr(proceso, 'summary_data', {}) or {}).get('firmx_id'):
        return JsonResponse({"error": "Los documentos FIRMX finalizados no permiten ajuste de firmas."}, status=400)

    firmantes_actuales = _normalizar_firmantes(getattr(proceso, 'firmantes', []))
    ajustes_recibidos = data.get('firmantes')
    if not isinstance(ajustes_recibidos, list) or not ajustes_recibidos:
        return JsonResponse({"error": "No se recibieron firmantes para ajustar."}, status=400)

    keys_actuales = [_firmante_key(firmante, index) for index, firmante in enumerate(firmantes_actuales)]
    recibidos_por_key = {}
    for item in ajustes_recibidos:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or item.get('token_firmante') or '').strip()
        if not key and item.get('original_index') is not None:
            try:
                key = keys_actuales[int(item.get('original_index'))]
            except (TypeError, ValueError, IndexError):
                key = ''
        if key in recibidos_por_key:
            return JsonResponse({"error": "Hay firmantes duplicados en el ajuste."}, status=400)
        if key:
            recibidos_por_key[key] = item

    if set(recibidos_por_key.keys()) != set(keys_actuales):
        return JsonResponse({"error": "No se puede agregar ni borrar firmantes; solo cambiar el orden."}, status=400)

    registros = []
    errores = []
    for index, firmante in enumerate(firmantes_actuales):
        key = keys_actuales[index]
        item = recibidos_por_key[key]
        try:
            orden = max(int(item.get('orden', index + 1)), 1)
        except (TypeError, ValueError):
            errores.append(f"Orden inválido para {firmante.get('nombre') or firmante.get('email')}.")
            continue
        coords = item.get('coordenadas') if isinstance(item.get('coordenadas'), dict) else {}
        page = 1
        try:
            page = max(int(coords.get('page', 1)), 1)
        except (TypeError, ValueError):
            page = 1
        x = _float_clamp(coords.get('x'), 0.08)
        y = _float_clamp(coords.get('y'), 0.08)

        firmado = bool(firmante.get('fecha_firma'))
        firma_b64 = _obtener_firma_base64_para_reestampado(firmante) if firmado else ''
        hash_firma = _obtener_hash_para_reestampado(firmante) if firmado else ''
        if firmado and not (firma_b64 or hash_firma):
            errores.append(f"No hay firma ni hash recuperable para {firmante.get('nombre') or firmante.get('email')}.")
            continue

        registros.append({
            'key': key,
            'index': index,
            'firmante': firmante,
            'orden': orden,
            'coordenadas': {'page': page, 'x': x, 'y': y},
            'firma_base64': firma_b64,
            'hash_firma': hash_firma,
            'metodo_reestampado': 'firma' if firma_b64 else ('hash' if hash_firma else ''),
        })

    if errores:
        return JsonResponse({"error": " ".join(errores)}, status=400)

    ajustes_pdf = []
    for registro in registros:
        firmante = registro['firmante']
        if not firmante.get('fecha_firma'):
            continue
        ajustes_pdf.append({
            'key': registro['key'],
            'nombre': firmante.get('nombre') or 'Firmante',
            'email': firmante.get('email') or '',
            'etiqueta': _etiqueta_firmante(firmante, registro['key']),
            'fecha_firma': firmante.get('fecha_firma') or '',
            'firma_base64': registro['firma_base64'],
            'hash_firma': registro['hash_firma'],
            'metodo_reestampado': registro['metodo_reestampado'],
            'posicion_anterior': _posicion_base_firmante(firmante),
            'coordenadas': registro['coordenadas'],
            'orden_anterior': _orden_firmante(firmante, registro['index']),
            'orden_nuevo': registro['orden'],
        })

    backup_path = f"{proceso.pdf_path}.{uuid.uuid4().hex}.ajuste.bak"
    try:
        shutil.copyfile(proceso.pdf_path, backup_path)
        resultado_pdf = reubicar_firmas_en_pdf(
            proceso.pdf_path,
            ajustes_pdf,
            actor_email=acceso['email'],
            actor_role=acceso['rol'],
        )

        posiciones = resultado_pdf.get('posiciones', {})
        fecha_ajuste = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
        nueva_lista = []
        for registro in registros:
            firmante = dict(registro['firmante'])
            posicion = posiciones.get(registro['key'])
            firmante['orden'] = registro['orden']
            firmante['coordenadas'] = registro['coordenadas']
            if posicion:
                firmante['posicion_estampada'] = posicion

            correccion = {
                'fecha': fecha_ajuste,
                'por': acceso['email'],
                'rol': acceso['rol'],
                'orden': registro['orden'],
                'coordenadas': registro['coordenadas'],
                'metodo_ajuste': 'hoja_correccion',
                'metodo_reestampado': registro['metodo_reestampado'],
                'hash_documento': resultado_pdf.get('hash'),
            }
            if registro['metodo_reestampado'] == 'hash':
                correccion['hash_reestampado'] = registro['hash_firma']
            historial = _json_or_default(firmante.get('correcciones_firma', []), [])
            historial.append(correccion)
            firmante['correccion_firma'] = correccion
            firmante['correcciones_firma'] = historial
            nueva_lista.append((registro['orden'], registro['index'], firmante))

        nueva_lista = [item[2] for item in sorted(nueva_lista, key=lambda item: (item[0], item[1]))]
        _actualizar_proceso_firma_mongo(proceso, firmantes=nueva_lista)
        _mongo_collection(ProcesoFirma).update_one(
            _mongo_pk_query(proceso),
            {
                '$set': {
                    'firma_ajustada_en': _datetime_for_mongo(),
                    'firma_ajustada_por': acceso['email'],
                    'firma_ajustada_rol': acceso['rol'],
                    'firma_ajustada_hash': resultado_pdf.get('hash'),
                }
            },
        )

        proceso.firmantes = nueva_lista
        advertencia = _sincronizar_pdf_finalizado(proceso)
        return JsonResponse({
            "status": "success",
            "msg": "Firmas ajustadas correctamente.",
            "pdf_url": f"{_media_url_for_path(proceso.pdf_path)}?v={int(timezone.now().timestamp())}",
            "warning": advertencia,
        })
    except Exception as e:
        if os.path.exists(backup_path):
            try:
                shutil.copyfile(backup_path, proceso.pdf_path)
            except Exception as restore_error:
                print(f"Error restaurando PDF tras ajuste fallido: {restore_error}")
        print(traceback.format_exc())
        return JsonResponse({"error": f"No se pudo ajustar el documento: {e}"}, status=500)
    finally:
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass


@csrf_exempt
def registro_firmas(request):
    if request.method == 'POST':
        email = _normalizar_email(request.POST.get('email'))
        if _mongo_find_one(DirectorioFirmas, {'email': email}) is not None: return render(request,
                                                                                'motor_firmas/registro_firmas.html',
                                                                                {"error": "Correo registrado."})
        _mongo_insert_model(DirectorioFirmas, {
            'nombre': str(request.POST.get('nombre') or '').strip().upper(),
            'email': email,
            'puesto': str(request.POST.get('puesto') or '').strip().upper(),
            'iniciales': str(request.POST.get('iniciales') or '').strip().upper(),
            'firma_base64': request.POST.get('firma_base64'),
            'pin_hash': make_password(request.POST.get('pin')),
            'acepto_terminos': True,
            'fecha_registro': _datetime_for_mongo(),
            'reset_token': None,
            'reset_token_expires': None,
            'tecnico_asignado': None,
            'permisos_portal': [],
            'ultima_actividad': None,
            'notificar_celular': False,
        })
        return HttpResponse("<h1 style='text-align:center; margin-top:50px;'>Registro exitoso.</h1>")
    return render(request, 'motor_firmas/registro_firmas.html')


@csrf_exempt
def solicitar_recuperacion(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON inválido."}, status=400)
    colaborador = _mongo_find_one(DirectorioFirmas, {'email': _normalizar_email(data.get('email'))})
    if colaborador:
        reset_token = uuid.uuid4()
        _mongo_update_document(DirectorioFirmas, colaborador, {
            'reset_token': reset_token,
            'reset_token_expires': _datetime_for_mongo(timezone.now() + timedelta(hours=1)),
        })
        try:
            tracked_post(N8N_WEBHOOK_RECUPERAR_PIN, json={"email": colaborador.email, "nombre": colaborador.nombre,
                                                           "link": f"https://dsign.raloy.com.mx/recuperar-pin/{reset_token}/"},
                          timeout=20)
        except Exception as e:
            print(f"Error en N8N_WEBHOOK_RECUPERAR_PIN: {e}")
    return JsonResponse({"status": "success"})


@csrf_exempt
def resetear_pin(request, token):
    colaborador = _mongo_find_one_by_uuid_field(DirectorioFirmas, 'reset_token', token)
    if not colaborador:
        raise Http404("Colaborador no encontrado")
    reset_expires = _datetime_for_compare(getattr(colaborador, 'reset_token_expires', None))
    if not reset_expires or reset_expires < timezone.now(): return HttpResponse("<h1>Enlace expirado.</h1>")
    if request.method == 'POST':
        _mongo_update_document(DirectorioFirmas, colaborador, {
            'pin_hash': make_password(request.POST.get('nuevo_pin')),
            'reset_token': None,
            'reset_token_expires': None,
        })
        return HttpResponse("<h1 style='text-align:center; margin-top:50px;'>PIN actualizado.</h1>")
    return render(request, 'motor_firmas/resetear_pin.html', {'token': token})


@csrf_exempt
def portal_login(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body or '{}')
        except ValueError:
            return JsonResponse({"error": "JSON inválido."}, status=400)
        email, pin_ingresado = _normalizar_email(data.get('email')), data.get('pin')
        colaborador = _mongo_find_one(DirectorioFirmas, {'email': email})
        otp_record = _mongo_find_one(OTPLogin, {'email': email})
        if _check_pin_colaborador(colaborador, pin_ingresado) or _otp_es_valido(otp_record, pin_ingresado):
            if otp_record:
                _mongo_delete_document(OTPLogin, otp_record)
            request.session['owner_email'] = email
            # Si es administrador, también marcamos sesión de admin
            if _mongo_find_one(AdministradorPortal, {'email': email}):
                request.session['admin_email'] = email
            return JsonResponse({"status": "success"})
        return JsonResponse({"error": "PIN incorrecto."}, status=403)
    if request.session.get('owner_email'): return redirect('portal_dashboard')
    return render(request, 'motor_firmas/portal_login.html')


@csrf_exempt
def solicitar_otp(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON inválido."}, status=400)
    email = _normalizar_email(data.get('email'))
    if not email: return JsonResponse({"error": "Correo requerido"}, status=400)
    otp_record = _generar_otp_mongo(email)
    try:
        tracked_post(N8N_WEBHOOK_ENVIAR_OTP, json={"email": email, "otp": otp_record.otp_code}, timeout=20)
    except Exception as e:
        print(f"Error en N8N_WEBHOOK_ENVIAR_OTP: {e}")
    return JsonResponse({"status": "success", "msg": "PIN temporal enviado."})


@ensure_csrf_cookie
def portal_dashboard(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')

    dominio = _dominio_de_email(owner_email)
    tiene_carpeta_dominio = _mongo_find_one(CarpetaDominio, {'dominio': dominio}) is not None

    colaborador = _mongo_find_one(DirectorioFirmas, {'email': owner_email})
    permisos = _json_or_default(getattr(colaborador, 'permisos_portal', []), [])

    admin_obj = _mongo_find_one(AdministradorPortal, {'email': owner_email})
    es_admin = _admin_es_global(admin_obj)
    if es_admin:
        for p in ['api_tester', 'plantillas', 'firmx']:
            if p not in permisos: permisos.append(p)

    plantillas_api = []
    if 'api_tester' in permisos:
        todas = _mongo_find(PlantillaFormulario, {}, [('created_at', -1)])
        for p in todas:
            permitidos = _json_or_default(getattr(p, 'usuarios_permitidos', []), [])
            if es_admin or owner_email in permitidos or getattr(p, 'owner_email', '') == owner_email:
                plantillas_api.append({
                    'id': str(p.id),
                    'nombre': p.nombre,
                    'doc_id': getattr(p, 'doc_id', ''),
                    'drive_folder_id': getattr(p, 'drive_folder_id', ''),
                    'carpeta_firmados_id': getattr(p, 'carpeta_firmados_id', ''),
                    'variables': _json_or_default(getattr(p, 'variables', []), []),
                    'firmantes_config': _json_or_default(getattr(p, 'firmantes_config', []), [])
                })

    return render(request, 'motor_firmas/portal_dashboard.html', _portal_context(
        owner_email,
        tiene_carpeta_dominio=tiene_carpeta_dominio,
        permisos=permisos,
        es_admin=es_admin,
        plantillas_api=plantillas_api,
        drive_archive_root_folder_id=_drive_root_folder_id(),
        drive_formatos_folder_id=_drive_formatos_folder_id(),
        drive_pdfs_folder_id=_drive_pdfs_folder_id(),
        drive_api_pdfs_folder_id=_drive_api_pdfs_folder_id(),
        drive_pdfs_folder_name=DRIVE_PDFS_FOLDER_NAME,
        api_keys=_json_or_default(getattr(colaborador, 'api_keys', []), []) if colaborador else []
    ))

@csrf_exempt
def portal_api_action(request, accion):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "No autorizado"}, status=403)
    
    colaborador = _mongo_find_one(DirectorioFirmas, {'email': owner_email})
    if not colaborador:
        return JsonResponse({"error": "Usuario no encontrado"}, status=404)
        
    permisos = _json_or_default(getattr(colaborador, 'permisos_portal', []), [])
    if 'api_tester' not in permisos:
        return JsonResponse({"error": "No tienes permiso de API Tester"}, status=403)

    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    if accion == 'generar_api_key':
        api_keys = _json_or_default(getattr(colaborador, 'api_keys', []), [])
        if len(api_keys) >= 10:
            return JsonResponse({"error": "Límite de 10 API Keys alcanzado. Elimina una antes de generar otra."}, status=400)
            
        import secrets
        import string
        raw_key = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        full_key = f"rtk_{raw_key}"
        masked_key = f"rtk_{'*' * 24}{raw_key[-4:]}"
        
        new_key = {
            'id': str(uuid.uuid4()),
            'masked': masked_key,
            'hashed': make_password(full_key),
            'created_at': _datetime_for_mongo().strftime("%d/%m/%Y %H:%M:%S")
        }
        api_keys.append(new_key)
        _mongo_update_document(DirectorioFirmas, colaborador, {'api_keys': api_keys})
        
        return JsonResponse({
            "status": "success", 
            "api_key": full_key,
            "masked": masked_key,
            "id": new_key['id'],
            "created_at": new_key['created_at']
        })
        
    return JsonResponse({"error": "Acción no válida"}, status=400)


@csrf_exempt
def portal_dashboard_docs_api(request):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "No autorizado"}, status=403)
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON inválido."}, status=400)
    return JsonResponse(_portal_dashboard_docs_page(owner_email, data))


@csrf_exempt
def portal_etiquetas_api(request):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "No autorizado"}, status=403)

    if request.method == 'GET':
        return JsonResponse(_portal_etiquetas_payload(owner_email))

    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    try:
        accion = str(data.get('accion') or 'crear').strip().lower()
        if accion == 'renombrar':
            etiqueta = _renombrar_etiqueta_documento_usuario(
                owner_email,
                data.get('etiqueta_actual'),
                data.get('nombre'),
            )
        elif accion == 'eliminar':
            etiqueta = _eliminar_etiqueta_documento_usuario(owner_email, data.get('etiqueta'))
        elif accion == 'destacar':
            etiqueta = _actualizar_destacado_etiqueta_documento_usuario(
                owner_email,
                data.get('etiqueta'),
                bool(data.get('destacado')),
            )
        elif accion == 'crear_hija':
            etiqueta = _guardar_subetiqueta_documento_usuario(
                owner_email,
                data.get('etiqueta_padre'),
                data.get('nombre'),
            )
        else:
            accion = 'crear'
            etiqueta = _guardar_etiqueta_documento_usuario(owner_email, data.get('nombre'))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    payload = _portal_etiquetas_payload(owner_email)
    payload['accion'] = accion
    if isinstance(etiqueta, dict):
        payload['label'] = etiqueta.get('deleted', '')
        payload['fallback_label'] = etiqueta.get('fallback', PORTAL_LABEL_UNTAGGED_VALUE)
    else:
        payload['label'] = etiqueta
    return JsonResponse(payload)


@csrf_exempt
def portal_documento_etiqueta_api(request):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "No autorizado"}, status=403)
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    proceso = _mongo_find_proceso_by_token(data.get('token'))
    if not proceso:
        return JsonResponse({"error": "Documento no encontrado."}, status=404)
    if not _validar_acceso_owner(proceso, owner_email):
        return JsonResponse({"error": "No tienes permiso sobre este documento."}, status=403)

    raw_etiqueta = data.get('etiqueta', '')
    if str(raw_etiqueta or '').strip() == PORTAL_LABEL_UNTAGGED_VALUE:
        raw_etiqueta = ''

    etiqueta = _normalizar_etiqueta_documento(raw_etiqueta)
    if etiqueta:
        try:
            etiqueta = _guardar_etiqueta_documento_usuario(owner_email, etiqueta)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    _actualizar_proceso_firma_mongo(proceso, etiqueta=etiqueta)
    payload = _portal_etiquetas_payload(owner_email)
    payload['documento'] = {
        'token': str(getattr(proceso, 'token_acceso', '')),
        'etiqueta': etiqueta,
    }
    return JsonResponse(payload)


def portal_firmx(request):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return redirect('portal_login')
    if not _usuario_tiene_permiso(owner_email, 'firmx'):
        return HttpResponse("<h1>No tienes permisos para usar el módulo FIRMX.</h1>", status=403)

    empresas = _mongo_find(CarpetaDominio, sort=[('dominio', 1)])
    areas = _mongo_find(AreaFirmex, sort=[('nombre', 1)])

    is_admin = bool(request.session.get('admin_email'))
    if not is_admin:
        is_admin = _mongo_find_one(AdministradorPortal, {'email': owner_email}) is not None

    api_key = ""
    if is_admin:
        config = _mongo_find_one(ConfiguracionFirmex)
        if config:
            api_key = getattr(config, 'api_key', '')
        else:
            api_key = getattr(settings, 'FIRMX_API_KEY', '')
    firmx_url_config = _firmx_configuracion_urls()

    return render(request, 'motor_firmas/portal_firmx.html', _portal_context(
        owner_email,
        firmx_base_url=firmx_url_config['active_base_url'],
        firmx_base_urls=firmx_url_config['base_urls'],
        es_admin_firmx=is_admin,
        firmx_api_key=api_key,
        empresas=empresas,
        areas=areas,
    ))


@csrf_exempt
def firmx_guardar_config(request):
    if not request.session.get('admin_email'):
        return JsonResponse({"error": "No autorizado"}, status=403)

    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body)
        api_key = data.get('api_key')
        base_url_action = data.get('base_url_action')
        updates = {}

        if api_key is not None:
            updates['api_key'] = api_key.strip()

        if base_url_action:
            config_urls = _firmx_configuracion_urls(include_secrets=True)
            active_url = config_urls['active_base_url']
            endpoints = [
                {
                    'url': item['url'],
                    'created_at': item.get('created_at') or _datetime_for_mongo().isoformat(),
                    'updated_at': item.get('updated_at') or '',
                    'api_key': item.get('api_key') or '',
                }
                for item in config_urls['base_urls']
            ]

            def find_endpoint(url):
                for endpoint in endpoints:
                    if endpoint['url'] == url:
                        return endpoint
                return None

            if base_url_action == 'save_base_url':
                clean_url = _normalizar_firmx_base_url(data.get('base_url'))
                endpoint = find_endpoint(clean_url)
                now_label = _datetime_for_mongo().isoformat()
                if endpoint:
                    endpoint['updated_at'] = now_label
                else:
                    endpoints.append({'url': clean_url, 'created_at': now_label, 'updated_at': now_label, 'api_key': ''})
                active_url = clean_url
            elif base_url_action == 'activate_base_url':
                clean_url = _normalizar_firmx_base_url(data.get('base_url'))
                endpoint = find_endpoint(clean_url)
                if not endpoint:
                    return JsonResponse({"error": "Ese endpoint no existe en el historial."}, status=404)
                endpoint['updated_at'] = _datetime_for_mongo().isoformat()
                active_url = clean_url
            elif base_url_action == 'delete_base_url':
                clean_url = _normalizar_firmx_base_url(data.get('base_url'))
                if clean_url == active_url:
                    return JsonResponse({"error": "No puedes eliminar la Base FIRMX activa. Activa otra antes de eliminarla."}, status=400)
                endpoints = [endpoint for endpoint in endpoints if endpoint['url'] != clean_url]
            elif base_url_action == 'save_endpoint_api_key':
                clean_url = _normalizar_firmx_base_url(data.get('base_url'))
                endpoint_api_key = str(data.get('endpoint_api_key') or '').strip()
                if not endpoint_api_key:
                    return JsonResponse({"error": "Captura una API Key para ese endpoint FIRMX."}, status=400)
                endpoint = find_endpoint(clean_url)
                now_label = _datetime_for_mongo().isoformat()
                if not endpoint:
                    endpoint = {'url': clean_url, 'created_at': now_label, 'updated_at': now_label, 'api_key': ''}
                    endpoints.append(endpoint)
                endpoint['api_key'] = endpoint_api_key
                endpoint['updated_at'] = now_label
            else:
                return JsonResponse({"error": "Acción de Base FIRMX inválida."}, status=400)

            updates['firmx_base_url'] = active_url
            updates['base_urls'] = endpoints

        if not updates:
            return JsonResponse({"error": "No se recibió configuración para guardar."}, status=400)

        updates['updated_at'] = _datetime_for_mongo()
        _mongo_update_or_insert_by_query(ConfiguracionFirmex, {}, updates)
        response_config = _firmx_configuracion_urls()
        return JsonResponse({
            "status": "success",
            "message": "Configuración FIRMX guardada correctamente.",
            "active_base_url": response_config['active_base_url'],
            "base_urls": response_config['base_urls'],
        })
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def firmx_registrar_documento(request):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "No autenticado"}, status=403)
    if not _usuario_tiene_permiso(owner_email, 'firmx'):
        return JsonResponse({"error": "No tienes permiso para usar FIRMX."}, status=403)
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)

    pdf_file = request.FILES.get('pdf_file')
    if not pdf_file:
        return JsonResponse({"error": "Archivo PDF requerido."}, status=400)
    if getattr(pdf_file, 'content_type', '') != 'application/pdf' and not str(pdf_file.name).lower().endswith('.pdf'):
        return JsonResponse({"error": "Solo se permiten archivos PDF."}, status=400)

    signers = _parse_json_field(request.POST.get('signers_json'), [])
    viewers = _parse_json_field(request.POST.get('viewers_json'), [])
    tags = _parse_json_field(request.POST.get('tags_json'), [])
    if not isinstance(signers, list) or not signers:
        return JsonResponse({"error": "Agrega al menos un firmante."}, status=400)

    firmantes_limpios = []
    for signer in signers:
        if not isinstance(signer, dict):
            continue
        name = str(signer.get('name') or '').strip()
        email = _normalizar_email(signer.get('email'))
        if name and re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            firmantes_limpios.append({"name": name, "email": email})
    if not firmantes_limpios:
        return JsonResponse({"error": "Agrega firmantes con nombre y correo válido."}, status=400)

    viewers_limpios = []
    for viewer in viewers if isinstance(viewers, list) else []:
        if not isinstance(viewer, dict):
            continue
        name = str(viewer.get('name') or '').strip()
        email = _normalizar_email(viewer.get('email'))
        if name and re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            viewers_limpios.append({"name": name, "email": email})

    tags_limpios = []
    for tag in tags if isinstance(tags, list) else []:
        if isinstance(tag, dict):
            value = str(tag.get('tag') or '').strip()
        else:
            value = str(tag or '').strip()
        if value:
            tags_limpios.append({"tag": value})

    document_name = str(request.POST.get('document_name') or pdf_file.name).strip()
    deadline = str(request.POST.get('dead_line_to_sign') or '').strip()
    if not deadline:
        return JsonResponse({"error": "Fecha límite de firma requerida."}, status=400)

    document_base64 = base64.b64encode(pdf_file.read()).decode('ascii')
    firmx_payload = {
        "document_name": document_name,
        "document_base64": document_base64,
        "signature_type": request.POST.get('signature_type') or 'SIMPLE_BIOMETRIC',
        "dead_line_to_sign": deadline,
        "remeber_me_every": request.POST.get('remeber_me_every') or '',
        "tags": tags_limpios,
        "notify_signers": str(request.POST.get('notify_signers', 'true')).lower() == 'true',
        "notify_viewers": str(request.POST.get('notify_viewers', 'true')).lower() == 'true',
        "signers": firmantes_limpios,
        "viewers": viewers_limpios,
        "message_for_request": request.POST.get('message_for_request') or 'Favor de revisar y firmar el documento.',
    }
    firmx_debug = {}
    firmx_base_url = _firmx_base_url_actual()
    if request.session.get('admin_email'):
        firmx_debug["firmx_curl"] = _firmx_curl_preview('POST', '/documents/register/', firmx_payload)

    try:
        response = tracked_post(
            _firmx_url('/documents/register/', base_url=firmx_base_url),
            headers=_firmx_headers(base_url=firmx_base_url),
            json=firmx_payload,
            timeout=_firmx_timeout(),
        )
        response_data = _json_response_from_requests(response)
    except Exception as e:
        return JsonResponse({"error": f"Error contactando FIRMX: {e}", **firmx_debug}, status=502)

    if not 200 <= response.status_code < 300:
        return JsonResponse({
            "error": "FIRMX no pudo registrar el documento.",
            "firmx_status": response.status_code,
            "firmx_response": response_data,
            **firmx_debug,
        }, status=502)

    document_id = _extract_firmx_document_id(response_data)
    ref_id = None

    # Trazabilidad: Guardar registro local si se obtuvo el ID
    if document_id:
        try:
            # Generar folio secuencial (FXP para pruebas conforme a solicitud)
            ref_id = _generar_folio_firmx(test_mode=True)

            # Asegurar directorio y guardar PDF local
            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
            file_path = os.path.join(settings.MEDIA_ROOT, f"{ref_id}.pdf")
            pdf_file.seek(0)
            with open(file_path, 'wb+') as destination:
                for chunk in pdf_file.chunks():
                    destination.write(chunk)

            # Extraer estado de FIRMX si está disponible
            firmx_data = response_data.get('data', {})
            firmx_status_raw = firmx_data.get('document_status', 'waiting_for_signatures')
            
            # Mapear estado de FIRMX a nuestro sistema
            local_status = 'FIRMX_WAITING'
            if firmx_status_raw == 'completed':
                local_status = 'COMPLETED'
            elif firmx_status_raw == 'cancelled':
                local_status = 'CANCELLED'

            # Crear proceso en MongoDB para trazabilidad en el dashboard
            _crear_proceso_firma_mongo(
                reference_id=ref_id,
                pdf_path=file_path,
                firmantes=firmantes_limpios,
                indice_actual=1,
                status=local_status,
                view_info='firmx',
                summary_data={
                    "firmx_id": document_id,
                    "firmx_base_url": firmx_base_url,
                    "document_name": document_name,
                    "firmx_response": response_data,
                    "firmx_status_raw": firmx_status_raw,
                    "api_steps": [
                        {
                            "step": "Registro de Documento",
                            "timestamp": _datetime_for_mongo().isoformat(),
                            "status": "success",
                            "details": f"ID FIRMX: {document_id}"
                        }
                    ]
                },
                owner_email=owner_email,
                exec_mode='firmx'
            )
        except Exception as e:
            print(f"Error guardando trazabilidad FIRMX: {e}")

    return JsonResponse({
        "status": "success",
        "firmx_status": response.status_code,
        "document_id": document_id,
        "folio": ref_id,
        "firmx_response": response_data,
        **firmx_debug,
    })


@csrf_exempt
def firmx_ejecutar_curl_manual(request):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "No autenticado"}, status=403)
    if not _usuario_tiene_permiso(owner_email, 'firmx'):
        return JsonResponse({"error": "No tienes permiso para usar FIRMX."}, status=403)
    es_admin_firmx = bool(request.session.get('admin_email')) or _mongo_find_one(
        AdministradorPortal, {'email': _normalizar_email(owner_email)}
    ) is not None
    if not es_admin_firmx:
        return JsonResponse({"error": "No autorizado para ejecutar cURL manual."}, status=403)
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)

    try:
        content_length = int(request.META.get('CONTENT_LENGTH') or 0)
        max_manual_bytes = int(getattr(settings, 'FIRMX_MANUAL_CURL_MAX_BYTES', 60 * 1024 * 1024))
        if content_length and content_length > max_manual_bytes:
            return JsonResponse({"error": "El payload manual excede el tamaño permitido."}, status=413)

        raw_body = request.read().decode(request.encoding or 'utf-8')
        data = json.loads(raw_body or '{}')
        method = str(data.get('method') or 'POST').upper()
        if method != 'POST':
            return JsonResponse({"error": "El envío manual solo ejecuta POST de registro."}, status=400)

        base_url = _normalizar_firmx_base_url(data.get('base_url') or _firmx_base_url_actual())
        url = str(data.get('url') or '').strip()
        if not url:
            url = f"{base_url}/documents/register/"
        parsed_url = urlparse(url)
        parsed_base = urlparse(base_url)
        if parsed_url.scheme not in ('http', 'https') or parsed_url.netloc != parsed_base.netloc:
            return JsonResponse({"error": "La URL del cURL no coincide con la Base FIRMX indicada."}, status=400)
        if not url.startswith(f"{base_url}/"):
            return JsonResponse({"error": "La URL del cURL debe pertenecer a la Base FIRMX indicada."}, status=400)
        if parsed_url.path.rstrip('/') != f"{parsed_base.path.rstrip('/')}/documents/register".rstrip('/'):
            return JsonResponse({"error": "Este ejecutor manual solo permite /documents/register/."}, status=400)

        headers = data.get('headers') if isinstance(data.get('headers'), dict) else {}
        api_key = str(headers.get('X-Api-Key') or headers.get('x-api-key') or '').strip()
        if not api_key:
            return JsonResponse({"error": "El cURL debe incluir X-Api-Key."}, status=400)

        payload = data.get('payload')
        if not isinstance(payload, dict):
            return JsonResponse({"error": "El payload debe ser un objeto JSON."}, status=400)

        response = tracked_post(
            url,
            headers={
                'X-Api-Key': api_key,
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=_firmx_timeout(),
        )
        response_data = _json_response_from_requests(response)
        ok = 200 <= response.status_code < 300
        document_id = _extract_firmx_document_id(response_data) if ok else ''

        return JsonResponse({
            "status": "success" if ok else "firmx_error",
            "ok": ok,
            "manual": True,
            "message": "cURL ejecutado contra FIRMX." if ok else "FIRMX respondió con error.",
            "firmx_status": response.status_code,
            "document_id": document_id,
            "firmx_response": response_data,
            "executed_request": {
                "method": method,
                "url": url,
                "headers": {
                    "X-Api-Key": api_key,
                    "Content-Type": "application/json",
                },
            },
        }, status=200 if ok else 502)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Error ejecutando cURL manual: {e}"}, status=502)


def admin_config_firmex(request):
    admin_email = request.session.get('admin_email')
    if not admin_email:
        return redirect('admin_login')

    if request.method == 'POST':
        nombre_area = request.POST.get('nombre_area')
        if nombre_area:
            nombre_area = nombre_area.strip()
            # Usar ayudante de MongoDB para evitar fallos del ORM Djongo
            _mongo_update_or_insert_by_query(AreaFirmex, {'nombre': nombre_area}, {
                'created_at': _datetime_for_mongo()
            })

        delete_id = request.POST.get('delete_id')
        if delete_id:
            # Buscar y eliminar usando el ID
            area_to_del = _mongo_find_one_by_id(AreaFirmex, delete_id)
            if area_to_del:
                _mongo_delete_document(AreaFirmex, area_to_del)

        return redirect('admin_config_firmex')

    areas = _mongo_find(AreaFirmex, sort=[('nombre', 1)])
    return render(request, 'motor_firmas/admin_config_firmex.html', {
        'admin_email': admin_email,
        'areas': areas
    })


@csrf_exempt
def firmx_obtener_qr(request, document_id):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "No autenticado"}, status=403)
    if not _usuario_tiene_permiso(owner_email, 'firmx'):
        return JsonResponse({"error": "No tienes permiso para usar FIRMX."}, status=403)
    if request.method != 'GET':
        return JsonResponse({"error": "Método no permitido."}, status=405)

    clean_id = str(document_id or '').strip()
    if not re.match(r'^[A-Za-z0-9_-]+$', clean_id):
        return JsonResponse({"error": "ID de documento FIRMX inválido."}, status=400)

    proceso_pre = None
    firmantes_locales_orden = []
    try:
        db_pre = _mongo_database()
        proceso_pre = db_pre.motor_firmas_procesofirma.find_one({"summary_data.firmx_id": clean_id})
        if proceso_pre:
            firmantes_locales_orden = _normalizar_firmantes(proceso_pre.get('firmantes', [])) or []
    except Exception as _e:
        proceso_pre = None
        firmantes_locales_orden = []

    firmx_base_url = _firmx_base_url_desde_summary(proceso_pre.get('summary_data', {}) if proceso_pre else {}) or _firmx_base_url_actual()
    firmx_debug = {}
    if request.session.get('admin_email'):
        firmx_debug["firmx_curl"] = _firmx_curl_preview('GET', f'/documents/api/{clean_id}/sign_qr')

    try:
        response = requests.get(
            _firmx_url(f'/documents/api/{clean_id}/sign_qr', base_url=firmx_base_url),
            headers=_firmx_headers(base_url=firmx_base_url),
            timeout=_firmx_timeout(),
        )
        response_data = _json_response_from_requests(response)
    except Exception as e:
        return JsonResponse({"error": f"Error contactando FIRMX: {e}", **firmx_debug}, status=502)

    if not 200 <= response.status_code < 300:
        return JsonResponse({
            "error": "FIRMX no pudo obtener el QR.",
            "firmx_status": response.status_code,
            "firmx_response": response_data,
            **firmx_debug,
        }, status=502)

    content_type = response.headers.get('content-type', '')
    qrs_descargados = []

    def _extraer_email_item(item, idx):
        """Extrae el correo del firmante del item de FIRMX probando múltiples
        claves conocidas; si no hay, mapea por orden con los firmantes locales."""
        if not isinstance(item, dict):
            email_fallback = None
        else:
            email_fallback = None
            # Claves planas posibles
            for k in ('email', 'signer_email', 'correo', 'correo_electronico',
                      'mail', 'user_email'):
                v = item.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            # Objetos anidados posibles
            for k in ('signer', 'firmante', 'user', 'usuario'):
                sub = item.get(k)
                if isinstance(sub, dict):
                    for kk in ('email', 'correo', 'correo_electronico', 'mail'):
                        vv = sub.get(kk)
                        if isinstance(vv, str) and vv.strip():
                            return vv.strip()
        # Fallback: mapear por índice contra firmantes locales
        if idx < len(firmantes_locales_orden):
            f = firmantes_locales_orden[idx] or {}
            em = f.get('email') if isinstance(f, dict) else None
            if isinstance(em, str) and em.strip():
                return em.strip()
        return email_fallback or 'Sin Email'

    if content_type.lower().startswith('image/'):
        qr_b64 = base64.b64encode(response.content).decode('ascii')
        qrs_descargados.append({
            'email': 'Documento',
            'qr_base64': qr_b64,
            'url_qr_code': None
        })
    else:
        data_list = response_data.get('data', [])
        if isinstance(data_list, list):
            for idx, item in enumerate(data_list):
                qr_b64 = item.get('qr_code') if isinstance(item, dict) else None
                if qr_b64:
                    qrs_descargados.append({
                        'email': _extraer_email_item(item, idx),
                        'qr_base64': qr_b64,
                        'url_qr_code': item.get('url_qr_code') if isinstance(item, dict) else None
                    })

    api_steps = []
    if qrs_descargados:
        # Trazabilidad y guardado local
        try:
            db = _mongo_database()
            proceso_doc = db.motor_firmas_procesofirma.find_one({"summary_data.firmx_id": clean_id})
            
            if proceso_doc:
                ref_id = proceso_doc.get('reference_id')
                summary_data = proceso_doc.get('summary_data', {})
                lista_qrs_local = []
                
                os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
                
                for i, qr_info in enumerate(qrs_descargados):
                    email_slug = re.sub(r'[^a-zA-Z0-9]', '_', qr_info['email'])
                    qr_filename = f"{ref_id}_qr_{i}_{email_slug}.png"
                    qr_path = os.path.join(settings.MEDIA_ROOT, qr_filename)
                    
                    with open(qr_path, "wb") as f:
                        f.write(base64.b64decode(qr_info['qr_base64']))
                    
                    item_qr = {
                        'email': qr_info['email'],
                        'qr_local_path': qr_filename,
                        'url_qr_code': qr_info['url_qr_code']
                    }
                    lista_qrs_local.append(item_qr)
                    
                    # Compatibilidad con lógica anterior (primer QR)
                    if i == 0:
                        summary_data['qr_local_path'] = qr_filename
                        summary_data['url_qr_code'] = qr_info['url_qr_code']
                
                summary_data['qrs'] = lista_qrs_local
                summary_data['firmx_base_url'] = firmx_base_url

                api_steps = summary_data.get('api_steps', [])
                api_steps.append({
                    "step": "Obtención de QR",
                    "timestamp": _datetime_for_mongo().isoformat(),
                    "status": "success",
                    "details": f"Se obtuvieron {len(qrs_descargados)} códigos QR."
                })
                summary_data['api_steps'] = api_steps
                
                db.motor_firmas_procesofirma.update_one(
                    {"_id": proceso_doc['_id']},
                    {"$set": {"summary_data": summary_data}}
                )
                
                return JsonResponse({
                    "status": "success",
                    "firmx_status": response.status_code,
                    "qr_image": f"data:image/png;base64,{qrs_descargados[0]['qr_base64']}",
                    "qrs": [{
                        'email': q['email'],
                        'qr_image': f"data:image/png;base64,{q['qr_base64']}",
                        'url_qr_code': q['url_qr_code']
                    } for q in qrs_descargados],
                    "api_steps": api_steps,
                    **firmx_debug,
                })
        except Exception as e:
            print(f"Error procesando guardado de QR: {e}")

    return JsonResponse({
        "status": "success",
        "firmx_status": response.status_code,
        "content_type": content_type,
        "firmx_response": response_data,
        "qr_image": f"data:image/png;base64,{qrs_descargados[0]['qr_base64']}" if qrs_descargados else None,
        "qrs": [{
            'email': q['email'],
            'qr_image': f"data:image/png;base64,{q['qr_base64']}",
            'url_qr_code': q['url_qr_code']
        } for q in qrs_descargados],
        "api_steps": api_steps,
        **firmx_debug,
    })
@csrf_exempt
def firmx_enviar_notificaciones(request, document_id):
    owner_email = request.session.get('owner_email')
    admin_email = request.session.get('admin_email')
    
    if not owner_email and not admin_email:
        return JsonResponse({"error": "No autenticado"}, status=403)
        
    usuario_verificador = owner_email or admin_email
    if not _usuario_tiene_permiso(usuario_verificador, 'firmx'):
        return JsonResponse({"error": "No tienes permiso para usar FIRMX."}, status=403)
    
    clean_id = str(document_id or '').strip()
    db = _mongo_database()
    proceso_doc = db.motor_firmas_procesofirma.find_one({"summary_data.firmx_id": clean_id})
    if not proceso_doc:
        return JsonResponse({"error": "No se encontró el proceso relacionado en el sistema."}, status=404)
    
    # Obtener correos de los firmantes
    firmantes = _normalizar_firmantes(proceso_doc.get('firmantes', []))
    
    email_filter = request.GET.get('email')
    if email_filter:
        emails = [f.get('email') for f in firmantes if _normalizar_email(f.get('email')) == _normalizar_email(email_filter)]
    else:
        emails = [f.get('email') for f in firmantes if f.get('email')]
    
    if not emails:
        return JsonResponse({"error": "No se encontraron correos de firmantes para notificar."}, status=400)
    
    # Recuperar URL de firma
    summary_data = proceso_doc.get('summary_data', {})
    
    # Mapeo de URLs por email si existen múltiples QRs (normalizando email)
    qrs_map = {_normalizar_email(q.get('email')): q.get('url_qr_code') for q in summary_data.get('qrs', []) if q.get('email')}
    
    url_firma = summary_data.get('url_qr_code') # Fallback al primero
    
    # Enviar notificaciones individuales para asegurar que cada uno reciba su URL de firma correcta
    api_steps = summary_data.get('api_steps', [])
    notificados_con_exito = []
    errores = []
    
    for email in emails:
        # Buscar URL específica para este correo, fallback a la general (primera obtenida)
        url_especifica = qrs_map.get(_normalizar_email(email)) or url_firma
        
        payload_n8n = {
            "correos_destino": email,
            "reference_id": proceso_doc.get('reference_id', 'N/A'),
            "url_firma": url_especifica,
            "subject": "Firma Digital Raloy - FIRMX",
            "titulo": "Firma Digital Raloy - FIRMX",
            "texto_boton": "IR A FIRMA",
            "mensaje": "Se requiere su firma para el documento: " + summary_data.get('document_name', 'Documento FIRMX')
        }
        
        try:
            response_n8n = tracked_post(N8N_WEBHOOK_NOTIFICAR_FIRMX, json=payload_n8n, timeout=20)
            n8n_error = _n8n_response_error(response_n8n)
            if not n8n_error:
                notificados_con_exito.append(email)
            else:
                errores.append(f"{email} ({n8n_error})")
        except Exception as e:
            errores.append(f"{email} (Error: {str(e)})")

    # Registrar en trazabilidad
    hubo_exito = len(notificados_con_exito) > 0
    api_steps.append({
        "step": "Envío de Notificaciones",
        "timestamp": _datetime_for_mongo().isoformat(),
        "status": "success" if not errores else ("partial" if hubo_exito else "error"),
        "details": f"Notificados: {', '.join(notificados_con_exito)}. Errores: {', '.join(errores)}" if errores else f"Notificación enviada a: {', '.join(notificados_con_exito)}"
    })
    
    try:
        db.motor_firmas_procesofirma.update_one(
            {"_id": proceso_doc['_id']},
            {"$set": {"summary_data.api_steps": api_steps}}
        )
        
        if not notificados_con_exito and errores:
            return JsonResponse({
                "error": "No se pudo enviar ninguna notificación a través de N8N.",
                "detalles": errores,
                "api_steps": api_steps
            }, status=502)
            
        return JsonResponse({
            "status": "success" if not errores else "partial",
            "sent_to": notificados_con_exito,
            "errors": errores,
            "api_steps": api_steps
        })
        
    except Exception as e:
        return JsonResponse({"error": f"Error actualizando trazabilidad: {e}"}, status=502)


@csrf_exempt
def firmx_obtener_status(request, document_id):
    owner_email = request.session.get('owner_email')
    admin_email = request.session.get('admin_email')
    
    if not owner_email and not admin_email:
        return JsonResponse({"error": "No autenticado"}, status=403)
        
    usuario_verificador = owner_email or admin_email
    if not _usuario_tiene_permiso(usuario_verificador, 'firmx'):
        return JsonResponse({"error": "No tienes permiso para usar FIRMX."}, status=403)
    
    clean_id = str(document_id or '').strip()
    if not clean_id:
        return JsonResponse({"error": "ID de documento FIRMX inválido."}, status=400)

    firmx_debug = {
        "firmx_curl": _firmx_curl_preview('GET', f'/documents/api/{clean_id}/')
    }
    
    success, result = _firmx_sync_status(clean_id)
    
    if success:
        return JsonResponse({
            "status": "success",
            "firmx_response": result,
            **firmx_debug
        })
    else:
        return JsonResponse({
            "error": f"Error contactando FIRMX: {result}",
            **firmx_debug
        }, status=502)


def portal_logout(request):
    request.session.flush()
    return redirect('portal_login')


@csrf_exempt
def n8n_monitor_events(request):
    if not session_can_view_monitor(request):
        return JsonResponse({"error": "No autenticado"}, status=403)

    if request.method == 'GET':
        return JsonResponse({"events": _combinar_eventos_n8n_monitor(
            _eventos_globales_n8n_monitor(),
            get_session_events(request),
        )})

    if request.method == 'POST':
        try:
            data = json.loads(request.body or '{}')
        except ValueError:
            return JsonResponse({"error": "JSON invalido."}, status=400)

        event = record_client_event(request, data)
        if event is None:
            return JsonResponse({"status": "ignored", "events": _combinar_eventos_n8n_monitor(
                _eventos_globales_n8n_monitor(),
                get_session_events(request),
            )})
        return JsonResponse({"status": "success", "event": event, "events": _combinar_eventos_n8n_monitor(
            _eventos_globales_n8n_monitor(),
            get_session_events(request),
        )})

    return JsonResponse({"error": "Metodo no permitido."}, status=405)


def portal_plantillas(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    todas = _mongo_find(PlantillaFormulario, {}, [('created_at', -1)])
    permitidas = []
    for p in todas:
        usuarios_permitidos = _json_or_default(getattr(p, 'usuarios_permitidos', []), [])
        if owner_email in usuarios_permitidos or getattr(p, 'owner_email', '') == owner_email:
            p.usuarios_permitidos = usuarios_permitidos
            p.variables = _json_or_default(getattr(p, 'variables', []), [])
            p.firmantes_config = _json_or_default(getattr(p, 'firmantes_config', []), [])
            permitidas.append(p)
    return render(
        request,
        'motor_firmas/portal_plantillas.html',
        _portal_context(owner_email, plantillas=permitidas),
    )


def portal_usar_plantilla(request, plantilla_id):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    plantilla = _mongo_find_one_by_id(PlantillaFormulario, plantilla_id)
    if not plantilla:
        raise Http404("Plantilla no encontrada")
    plantilla.variables = _json_or_default(plantilla.variables, [])
    plantilla.firmantes_config = _json_or_default(plantilla.firmantes_config, [])
    plantilla.usuarios_permitidos = _json_or_default(plantilla.usuarios_permitidos, [])
    return render(
        request,
        'motor_firmas/portal_usar_plantilla.html',
        _portal_context(owner_email, plantilla=plantilla),
    )


@csrf_exempt
def solicitar_firma_plantilla(request, plantilla_id):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return JsonResponse({"error": "No autenticado"}, status=403)
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)

    plantilla = _mongo_find_one_by_id(PlantillaFormulario, plantilla_id)
    if not plantilla:
        return JsonResponse({"error": "Plantilla no encontrada."}, status=404)

    permitidos = _json_or_default(getattr(plantilla, 'usuarios_permitidos', []), [])
    admin_obj = _mongo_find_one(AdministradorPortal, {'email': owner_email})
    if (
        not _admin_es_global(admin_obj)
        and owner_email not in permitidos
        and getattr(plantilla, 'owner_email', '') != owner_email
    ):
        return JsonResponse({"error": "No tienes permiso para usar esta plantilla."}, status=403)

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    reference_id = str(data.get('reference_id') or '').strip()
    if not reference_id:
        reference_id = f"DOC-{int(timezone.now().timestamp())}"

    firmantes = _normalizar_firmantes(data.get('firmantes', []))
    if not firmantes:
        return JsonResponse({"error": "Añade al menos un firmante."}, status=400)

    formatos_folder_id = _drive_formatos_folder_id() or getattr(plantilla, 'drive_folder_id', '')
    pdfs_folder_id = _drive_configured_pdfs_folder_id() or getattr(plantilla, 'carpeta_firmados_id', '') or _drive_pdfs_folder_id()
    payload = {
        **_drive_storage_payload(),
        "reference_id": reference_id,
        "dir": pdfs_folder_id,
        "folder_id": pdfs_folder_id,
        "pdfs_folder_id": pdfs_folder_id,
        "formatos_folder_id": formatos_folder_id,
        "template_id": getattr(plantilla, 'doc_id', ''),
        "view_info": getattr(plantilla, 'view_info', 'file') or 'file',
        "exec": "form",
        "owner": owner_email,
        "variables_asignadas": data.get('variables_asignadas') or data.get('document_variables') or {},
        "firmantes": firmantes,
    }

    try:
        response = tracked_post(N8N_WEBHOOK_REQUEST_SIGNATURE, json=payload, timeout=30)
        n8n_error = _n8n_response_error(response)
        if n8n_error:
            return JsonResponse({
                "error": "N8N no pudo generar el documento.",
                "detail": n8n_error,
            }, status=502)
    except Exception as e:
        return JsonResponse({"error": f"Error contactando N8N: {e}"}, status=502)

    return JsonResponse({"status": "success", "msg": "Documento enviado a generación.", "reference_id": reference_id})


# ================= VISTAS DE PDFS LIBRES (DRAG & DROP) =================
def _pdf_usuario_confirmado_en_drive(doc):
    return bool(str(getattr(doc, 'drive_file_id', '') or '').strip()) and getattr(doc, 'upload_status', 'uploaded') != 'paused'


def _pdf_usuario_dedupe_key(doc):
    upload_sha256 = str(getattr(doc, 'upload_sha256', '') or '').strip()
    if upload_sha256:
        return f"sha256:{upload_sha256}"
    nombre = str(getattr(doc, 'nombre', '') or '').strip().lower()
    return f"nombre:{nombre}" if nombre else ''


def _pdf_usuario_mismo_intento_legacy(a_doc, b_doc):
    if getattr(a_doc, 'upload_sha256', '') and getattr(b_doc, 'upload_sha256', ''):
        return True
    a_created = _datetime_for_compare(getattr(a_doc, 'created_at', None))
    b_created = _datetime_for_compare(getattr(b_doc, 'created_at', None))
    if a_created is None or b_created is None:
        return True
    return abs((a_created - b_created).total_seconds()) <= PDF_LEGACY_DUPLICATE_WINDOW_SECONDS


def _deduplicar_pdfs_usuario_visibles(pdfs):
    visibles = []
    seen = {}
    for doc in pdfs:
        if getattr(doc, 'enviado_a_firma', False) or getattr(doc, 'converted_to_master', False):
            visibles.append(doc)
            continue
        key = _pdf_usuario_dedupe_key(doc)
        if not key:
            visibles.append(doc)
            continue
        existing_index = seen.get(key)
        if existing_index is None:
            seen[key] = len(visibles)
            visibles.append(doc)
            continue
        existing = visibles[existing_index]
        if not _pdf_usuario_mismo_intento_legacy(doc, existing):
            seen[f"{key}:{getattr(doc, 'id_documento', len(visibles))}"] = len(visibles)
            visibles.append(doc)
            continue
        if _pdf_usuario_confirmado_en_drive(doc) and not _pdf_usuario_confirmado_en_drive(existing):
            visibles[existing_index] = doc

    return sorted(
        visibles,
        key=lambda doc: _datetime_for_compare(getattr(doc, 'created_at', None)) or datetime.min.replace(tzinfo=datetime_timezone.utc),
        reverse=True,
    )


def portal_pdfs_usuario(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    pdfs = _mongo_find(DocumentoPDFUsuario, {'owner_email': owner_email, 'deleted': {'$ne': True}}, [('created_at', -1)])
    pdfs = _deduplicar_pdfs_usuario_visibles(pdfs)

    return render(
        request,
        'motor_firmas/portal_pdfs_usuario.html',
        _portal_context(owner_email, pdfs=pdfs),
    )


@csrf_exempt
def eliminar_pdf_usuario(request, pdf_id):
    owner_email = request.session.get('owner_email')
    if not owner_email: return JsonResponse({"error": "No autorizado"}, status=403)

    doc = _mongo_find_one_by_uuid_field(DocumentoPDFUsuario, 'id_documento', pdf_id, {'owner_email': owner_email})
    if doc is None:
        doc = _mongo_find_one_by_id_text(DocumentoPDFUsuario, pdf_id, {'owner_email': owner_email})

    if doc is not None:
        _mongo_update_document(DocumentoPDFUsuario, doc, {'deleted': True})
        return JsonResponse({"status": "success"})

    return JsonResponse({"error": "Documento no encontrado"}, status=404)


def portal_subir_pdf(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    return render(request, 'motor_firmas/portal_subir_pdf.html', _portal_context(owner_email))


def _safe_pdf_libre_filename(original_filename):
    filename = os.path.basename(str(original_filename or '') or 'documento.pdf')
    safe_original = re.sub(r'[^A-Za-z0-9._-]+', '_', filename).strip('._') or 'documento.pdf'
    if not safe_original.lower().endswith('.pdf'):
        safe_original = f"{safe_original}.pdf"
    return f"{uuid.uuid4()}_{safe_original[:180]}"


def _guardar_pdf_libre_local_desde_bytes(file_bytes, original_filename, existing_doc=None):
    rel_path = str(getattr(existing_doc, 'archivo_local', '') or '').replace('\\', '/') if existing_doc else ''
    if rel_path:
        abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
        if os.path.exists(abs_path):
            return rel_path

    os.makedirs(os.path.join(settings.MEDIA_ROOT, 'pdfs_libres'), exist_ok=True)
    local_path = os.path.join('pdfs_libres', _safe_pdf_libre_filename(original_filename))
    with open(os.path.join(settings.MEDIA_ROOT, local_path), 'wb+') as f:
        f.write(file_bytes)
    return local_path


def _buscar_pdf_usuario_por_hash(owner_email, upload_sha256):
    if not upload_sha256:
        return None
    return _mongo_find_one(DocumentoPDFUsuario, {
        'owner_email': owner_email,
        'upload_sha256': upload_sha256,
        'deleted': {'$ne': True},
        'converted_to_master': {'$ne': True},
    })


def _n8n_upload_attempt_es_reciente(doc):
    last_attempt = _datetime_for_compare(getattr(doc, 'last_n8n_upload_attempt_at', None))
    if last_attempt is None:
        return False
    return timezone.now() - last_attempt < timedelta(seconds=PDF_UPLOAD_RETRY_COOLDOWN_SECONDS)


def _guardar_borrador_pdf_pausado(owner_email, original_filename, file_bytes, upload_sha256, existing_doc=None, error=''):
    now = _datetime_for_mongo()
    local_path = _guardar_pdf_libre_local_desde_bytes(file_bytes, original_filename, existing_doc)
    fields = {
        'nombre': original_filename,
        'owner_email': owner_email,
        'archivo_local': local_path,
        'enviado_a_firma': False,
        'upload_sha256': upload_sha256,
        'upload_size': len(file_bytes),
        'upload_status': 'paused',
        'n8n_upload_error': str(error or '')[:1000],
        'last_n8n_upload_attempt_at': now,
        'updated_at': now,
    }
    if existing_doc is not None:
        _mongo_update_document(DocumentoPDFUsuario, existing_doc, fields)
        return existing_doc

    id_documento = str(uuid.uuid4())
    document = {
        'id_documento': id_documento,
        'drive_file_id': '',
        'created_at': now,
        **fields,
    }
    _mongo_collection(DocumentoPDFUsuario).insert_one(document)
    return _mongo_to_namespace(document)


def _marcar_borrador_pdf_subido(doc, drive_file_id, original_filename, file_bytes, upload_sha256):
    now = _datetime_for_mongo()
    local_path = _guardar_pdf_libre_local_desde_bytes(file_bytes, original_filename, doc)
    fields = {
        'nombre': original_filename,
        'drive_file_id': drive_file_id,
        'archivo_local': local_path,
        'upload_sha256': upload_sha256,
        'upload_size': len(file_bytes),
        'upload_status': 'uploaded',
        'n8n_upload_error': '',
        'last_n8n_upload_success_at': now,
        'updated_at': now,
    }
    _mongo_update_document(DocumentoPDFUsuario, doc, fields)
    return doc


@csrf_exempt
def subir_pdf_usuario(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return JsonResponse({"error": "No autenticado"}, status=403)
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)

    pdf_file = request.FILES.get('pdf_file')
    if not pdf_file: return JsonResponse({"error": "No se seleccionó ningún archivo PDF."}, status=400)
    original_filename = os.path.basename(str(getattr(pdf_file, 'name', '') or 'documento.pdf'))
    if not original_filename.lower().endswith('.pdf'):
        return JsonResponse({"error": "Solo se permiten archivos PDF."}, status=400)
    file_bytes = pdf_file.read()
    pdf_file.seek(0)
    upload_sha256 = hashlib.sha256(file_bytes).hexdigest()
    existing_doc = _buscar_pdf_usuario_por_hash(owner_email, upload_sha256)
    if existing_doc and str(getattr(existing_doc, 'drive_file_id', '') or '').strip():
        return JsonResponse({
            "status": "success",
            "nombre": getattr(existing_doc, 'nombre', original_filename) or original_filename,
            "id": str(getattr(existing_doc, 'id_documento', '') or ''),
            "deduplicated": True,
        })
    if existing_doc and _n8n_upload_attempt_es_reciente(existing_doc):
        return _pausar_subida_pdf_usuario_por_n8n(
            'La subida ya esta pausada por una falla reciente de N8N.',
            f"Reintento duplicado bloqueado por {PDF_UPLOAD_RETRY_COOLDOWN_SECONDS} segundos para evitar subidas/correos duplicados.",
            document_id=getattr(existing_doc, 'id_documento', ''),
            owner_email=owner_email,
        )

    dominio = _dominio_de_email(owner_email)
    try:
        carpeta_dom = _mongo_find_one(CarpetaDominio, {'dominio': dominio})
    except Exception as e:
        return JsonResponse({
            "error": "No se pudo consultar la carpeta de Google Drive para tu dominio.",
            "detail": str(e),
        }, status=500)
    if not carpeta_dom: return JsonResponse(
        {"error": f"Tu dominio (@{dominio}) no tiene asignada una carpeta en Google Drive."}, status=400)
    drive_folder_id = str(getattr(carpeta_dom, 'drive_folder_id', '') or '').strip()
    if not drive_folder_id:
        return JsonResponse({"error": f"Tu dominio (@{dominio}) no tiene una carpeta de Google Drive valida."}, status=400)

    existing_doc = _guardar_borrador_pdf_pausado(
        owner_email,
        original_filename,
        file_bytes,
        upload_sha256,
        existing_doc=existing_doc,
        error='Subida a N8N en proceso.',
    )

    try:
        files = {'data': (original_filename, file_bytes, 'application/pdf')}
        response = tracked_post(N8N_WEBHOOK_SUBIR_PDF_USUARIO, data={'folder_id': drive_folder_id},
                                files=files, timeout=PDF_UPLOAD_N8N_TIMEOUT_SECONDS)
        n8n_error = _n8n_response_error(response)
        if n8n_error:
            _guardar_borrador_pdf_pausado(
                owner_email,
                original_filename,
                file_bytes,
                upload_sha256,
                existing_doc=existing_doc,
                error=n8n_error,
            )
            return _pausar_subida_pdf_usuario_por_n8n(
                'N8N fallo al subir el PDF a Google Drive.',
                n8n_error,
                document_id=getattr(existing_doc, 'id_documento', ''),
                owner_email=owner_email,
            )
        try:
            resp = response.json()
        except ValueError as exc:
            _guardar_borrador_pdf_pausado(
                owner_email,
                original_filename,
                file_bytes,
                upload_sha256,
                existing_doc=existing_doc,
                error=exc,
            )
            return _pausar_subida_pdf_usuario_por_n8n(
                'N8N no devolvio una respuesta JSON valida al subir el PDF.',
                exc,
                document_id=getattr(existing_doc, 'id_documento', ''),
                owner_email=owner_email,
            )

        if isinstance(resp, list):
            resp = resp[0] if resp else {}
        if not isinstance(resp, dict):
            _guardar_borrador_pdf_pausado(
                owner_email,
                original_filename,
                file_bytes,
                upload_sha256,
                existing_doc=existing_doc,
                error=resp,
            )
            return _pausar_subida_pdf_usuario_por_n8n(
                'N8N devolvio una respuesta invalida al subir el PDF.',
                resp,
                document_id=getattr(existing_doc, 'id_documento', ''),
                owner_email=owner_email,
            )

        n8n_status = str(resp.get('status') or resp.get('state') or '').strip().lower()
        drive_file_id = str(
            resp.get('file_id')
            or resp.get('drive_file_id')
            or resp.get('id')
            or ''
        ).strip()

        if n8n_status == 'success' and drive_file_id:
            doc = _marcar_borrador_pdf_subido(
                existing_doc,
                drive_file_id,
                original_filename,
                file_bytes,
                upload_sha256,
            )
            return JsonResponse({"status": "success", "nombre": original_filename, "id": str(getattr(doc, 'id_documento', '') or '')})

        n8n_detail = resp.get('error') or resp.get('message') or resp.get('detail') or resp
        _guardar_borrador_pdf_pausado(
            owner_email,
            original_filename,
            file_bytes,
            upload_sha256,
            existing_doc=existing_doc,
            error=n8n_detail,
        )
        return _pausar_subida_pdf_usuario_por_n8n(
            'N8N no confirmo la subida del PDF a Google Drive.',
            n8n_detail,
            document_id=getattr(existing_doc, 'id_documento', ''),
            owner_email=owner_email,
        )
    except requests.RequestException as e:
        _guardar_borrador_pdf_pausado(
            owner_email,
            original_filename,
            file_bytes,
            upload_sha256,
            existing_doc=existing_doc,
            error=e,
        )
        return _pausar_subida_pdf_usuario_por_n8n(
            'No se pudo contactar N8N para subir el PDF a Google Drive.',
            e,
            document_id=getattr(existing_doc, 'id_documento', ''),
            owner_email=owner_email,
        )
    except Exception as e:
        return JsonResponse({"error": f"Error interno al subir el PDF: {e}"}, status=500)


def portal_configurar_pdf(request, pdf_id):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    doc = _mongo_find_one_by_uuid_field(DocumentoPDFUsuario, 'id_documento', pdf_id, {'owner_email': owner_email})
    if not doc:
        raise Http404("Documento PDF no encontrado")
    if not str(getattr(doc, 'drive_file_id', '') or '').strip() or getattr(doc, 'upload_status', 'uploaded') == 'paused':
        raise Http404("El PDF aun no fue confirmado en Google Drive. Reintenta la subida antes de configurarlo.")
    try:
        rel_path, _ = _asegurar_pdf_usuario_local(doc, owner_email)
    except Exception as e:
        raise Http404(f"No se pudo preparar el PDF: {e}")
    pdf_url = f"{settings.MEDIA_URL}{rel_path}"
    return render(
        request,
        'motor_firmas/portal_configurar_pdf.html',
        _portal_context(
            owner_email,
            doc=doc,
            pdf_url=pdf_url,
            signed_documents=json.dumps(_documentos_firmados_usuario(owner_email)),
        ),
    )


def _firma_libre_en_proceso_reciente(doc):
    started_at = _datetime_for_compare(getattr(doc, 'firma_iniciando_at', None))
    if started_at is None:
        return False
    return timezone.now() - started_at < timedelta(seconds=FIRMA_LIBRE_DUPLICATE_GUARD_SECONDS)


def _respuesta_firma_libre_ya_iniciada(doc):
    ref_id = str(
        getattr(doc, 'proceso_reference_id', '')
        or getattr(doc, 'reference_id', '')
        or ''
    ).strip()
    if ref_id:
        return JsonResponse({
            "status": "success",
            "already_started": True,
            "reference_id": ref_id,
            "msg": "La solicitud de firma ya estaba enviada; no se envio otro correo.",
        })
    return JsonResponse({
        "status": "processing",
        "already_started": True,
        "msg": "La solicitud de firma ya esta en proceso; no se enviara otro correo.",
    }, status=202)


@csrf_exempt
def iniciar_firma_libre(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return JsonResponse({"error": "No autorizado"}, status=403)
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    doc = _mongo_find_one_by_uuid_field(DocumentoPDFUsuario, 'id_documento', data.get('pdf_id'), {'owner_email': owner_email})
    if not doc:
        return JsonResponse({"error": "Documento no encontrado."}, status=404)
    if getattr(doc, 'enviado_a_firma', False) or getattr(doc, 'converted_to_master', False):
        return _respuesta_firma_libre_ya_iniciada(doc)
    if getattr(doc, 'firma_iniciando', False) and _firma_libre_en_proceso_reciente(doc):
        return _respuesta_firma_libre_ya_iniciada(doc)
    if not str(getattr(doc, 'drive_file_id', '') or '').strip() or getattr(doc, 'upload_status', 'uploaded') == 'paused':
        return JsonResponse({
            "status": "paused",
            "error": "El PDF aun no esta confirmado en Google Drive. Reintenta la subida antes de solicitar firmas.",
        }, status=409)

    firmantes = _normalizar_firmantes(data.get('firmantes', []))
    if not firmantes:
        return JsonResponse({"error": "Añade al menos un firmante."}, status=400)
    for f in firmantes: f['token_firmante'] = str(uuid.uuid4())

    try:
        document_references = _normalizar_referencias_documento(data.get('document_references', []), owner_email)
        fill_fields = _normalizar_campos_llenado(data.get('fill_fields', []), firmantes)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    document_variables = _document_variables_desde_campos_llenado(fill_fields)

    try:
        _, original_path = _asegurar_pdf_usuario_local(doc, owner_email)
    except Exception as e:
        return JsonResponse({"error": f"No se pudo preparar el PDF original: {e}"}, status=400)

    ref_id = f"LIBRE-{int(timezone.now().timestamp())}"
    counter = 1
    while _mongo_find_one(ProcesoFirma, {'reference_id': ref_id}) is not None:
        ref_id = f"LIBRE-{int(timezone.now().timestamp())}-{counter}"
        counter += 1
    final_path = os.path.join(settings.MEDIA_ROOT, f"{ref_id}.pdf")
    shutil.copyfile(original_path, final_path)
    _mongo_update_document(DocumentoPDFUsuario, doc, {
        'firma_iniciando': True,
        'firma_iniciando_at': _datetime_for_mongo(),
        'firma_iniciando_error': '',
    })

    dominio = owner_email.split('@')[1] if '@' in owner_email else ''
    carpeta_dom = _mongo_find_one(CarpetaDominio, {'dominio': dominio})

    proceso = _crear_proceso_firma_mongo(
        reference_id=ref_id, pdf_path=final_path, firmantes=firmantes,
        indice_actual=1, view_info="file", owner_email=owner_email,
        dir_drive=carpeta_dom.drive_folder_id if carpeta_dom else '', exec_mode="libre",
        document_variables=document_variables,
        summary_data={
            'source_drive_file_id': getattr(doc, 'drive_file_id', ''),
            'source_pdf_filename': getattr(doc, 'nombre', ''),
            'source_document_id': str(getattr(doc, 'id_documento', '') or ''),
            'document_references': document_references,
            'fill_fields': fill_fields,
        },
    )
    _mongo_update_document(DocumentoPDFUsuario, doc, {
        'enviado_a_firma': True,
        'proceso_reference_id': ref_id,
        'firma_iniciando': True,
        'firma_iniciando_at': _datetime_for_mongo(),
        'updated_at': _datetime_for_mongo(),
    })

    primer_firmante = firmantes[0]
    link_firma = f"https://dsign.raloy.com.mx/firmar/{proceso.token_acceso}/{primer_firmante.get('token_firmante', '')}/"
    try:
        tracked_post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                      json={"email": primer_firmante.get('email'), "nombre": primer_firmante.get('nombre'), "link": link_firma,
                            "mensaje": f"Raloy solicita tu firma para el documento libre {ref_id}."},
                      timeout=20)
    except Exception as e:
        print(f"Error en N8N_WEBHOOK_NOTIFICAR_CORREO: {e}")
    crear_notificacion_firma(primer_firmante.get('email'), ref_id, f"Raloy solicita tu firma para el documento libre {ref_id}.")

    link_trazabilidad = f"https://dsign.raloy.com.mx/trazabilidad/{proceso.token_acceso}/"
    try:
        tracked_post(N8N_WEBHOOK_NOTIFICAR_OWNER,
                      json={"email": owner_email, "reference_id": ref_id, "link": link_trazabilidad},
                      timeout=20)
    except Exception as e:
        print(f"Error en N8N_WEBHOOK_NOTIFICAR_OWNER: {e}")
    crear_notificacion_firma(owner_email, ref_id, f"Has iniciado el proceso de firma libre para {ref_id}.")

    doc_updates = {
        'deleted': True,
        'converted_to_master': True,
        'enviado_a_firma': True,
        'proceso_reference_id': ref_id,
        'firma_iniciando': False,
        'firma_iniciando_at': None,
        'updated_at': _datetime_for_mongo(),
    }
    if _eliminar_archivo_media(original_path):
        doc_updates['archivo_local'] = ''
    _mongo_update_document(DocumentoPDFUsuario, doc, doc_updates)

    return JsonResponse({"status": "success"})


# ================= VISTAS DE ADMINISTRADOR =================
@csrf_exempt
def admin_login(request):
    _asegurar_admin_maestro()
            
    if request.method == 'POST':
        try:
            data = json.loads(request.body or '{}')
        except ValueError:
            return JsonResponse({"error": "JSON inválido."}, status=400)
        email, pin_ingresado = _normalizar_email(data.get('email')), data.get('pin')
        if _mongo_find_one(AdministradorPortal, {'email': email}) is None: return JsonResponse(
            {"error": "No eres admin."}, status=403)
        colaborador = _mongo_find_one(DirectorioFirmas, {'email': email})
        otp_record = _mongo_find_one(OTPLogin, {'email': email})
        if _check_pin_colaborador(colaborador, pin_ingresado) or _otp_es_valido(otp_record, pin_ingresado):
            if otp_record:
                _mongo_delete_document(OTPLogin, otp_record)
            request.session['admin_email'] = email
            # Si también es colaborador, marcamos sesión de owner
            if _mongo_find_one(DirectorioFirmas, {'email': email}):
                request.session['owner_email'] = email
            return JsonResponse({"status": "success"})
        return JsonResponse({"error": "PIN incorrecto."}, status=403)
    if request.session.get('admin_email'): return redirect('admin_dashboard')
    return render(request, 'motor_firmas/admin_login.html')


def admin_dashboard(request):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    admin_obj = _mongo_find_one(AdministradorPortal, {'email': admin_email})
    if not admin_obj:
        request.session.flush()
        return redirect('admin_login')
    
    if getattr(admin_obj, 'es_superadmin', False) or admin_email == 'pjimenezb@raloy.com.mx':
        plantillas = _mongo_find(PlantillaFormulario, {}, [('created_at', -1)])
    else:
        usuarios_asignados = _mongo_find(DirectorioFirmas, {'tecnico_asignado': admin_email})
        emails_asignados = [u.email for u in usuarios_asignados if getattr(u, 'email', None)]
        owners_permitidos = list({admin_email, *emails_asignados})
        plantillas = _mongo_find(PlantillaFormulario, {'owner_email': {'$in': owners_permitidos}}, [('created_at', -1)])
    _asegurar_marca_raloy_actual()
    base_docs_query = _admin_dashboard_base_query(admin_obj)
    document_domains = _admin_dashboard_document_domains(base_docs_query)
    carpetas_dominio = [
        _carpeta_dominio_payload(c)
        for c in _mongo_find(CarpetaDominio, {}, [('dominio', 1)])
    ]

    es_usuario = _mongo_find_one(DirectorioFirmas, {'email': admin_email}) is not None

    return render(request, 'motor_firmas/admin_dashboard.html',
                  {'admin_email': admin_email,
                   'saved_config': json.dumps(_json_or_default(getattr(admin_obj, 'configuracion_dashboard', {}), {})),
                   'drive_config': json.dumps(_drive_config_payload()),
                   'plantillas': plantillas,
                   'carpetas_dominio': json.dumps(carpetas_dominio),
                   'document_domains': json.dumps(document_domains),
                   'es_superadmin': _admin_es_global(admin_obj),
                   'es_usuario': es_usuario})


def admin_logout(request):
    request.session.flush()
    return redirect('admin_login')


def admin_crear_plantilla(request):
    if not request.session.get('admin_email'): return redirect('admin_login')
    return render(request, 'motor_firmas/admin_crear_plantilla.html',
                  {
                      'admin_email': request.session.get('admin_email'),
                      'drive_archive_root_folder_id': _drive_root_folder_id(),
                      'drive_formatos_folder_id': _drive_formatos_folder_id(),
                      'drive_pdfs_folder_id': _drive_pdfs_folder_id(),
                      'drive_formatos_folder_name': DRIVE_FORMATOS_FOLDER_NAME,
                      'drive_pdfs_folder_name': DRIVE_PDFS_FOLDER_NAME,
                  })


def admin_editar_plantilla(request, plantilla_id):
    if not request.session.get('admin_email'): return redirect('admin_login')
    plantilla = _mongo_find_one_by_id(PlantillaFormulario, plantilla_id)
    if not plantilla:
        raise Http404("Plantilla no encontrada")
    plantilla.variables = _json_or_default(plantilla.variables, [])
    plantilla.firmantes_config = _json_or_default(plantilla.firmantes_config, [])
    plantilla.usuarios_permitidos = _json_or_default(plantilla.usuarios_permitidos, [])
    return render(request, 'motor_firmas/admin_editar_plantilla.html',
                  {
                      'admin_email': request.session.get('admin_email'),
                      'plantilla': plantilla,
                      'drive_archive_root_folder_id': _drive_root_folder_id(),
                      'drive_formatos_folder_id': _drive_formatos_folder_id(),
                      'drive_pdfs_folder_id': _drive_pdfs_folder_id(),
                      'drive_formatos_folder_name': DRIVE_FORMATOS_FOLDER_NAME,
                      'drive_pdfs_folder_name': DRIVE_PDFS_FOLDER_NAME,
                  })


@csrf_exempt
def admin_api(request, accion):
    if not request.session.get('admin_email'): return JsonResponse({"error": "No autorizado"}, status=403)
    admin_actual = _mongo_find_one(AdministradorPortal, {'email': request.session.get('admin_email')})
    if not admin_actual:
        return JsonResponse({"error": "Sesión de admin inválida"}, status=403)
    
    if request.method == 'POST':
        content_type = request.META.get('CONTENT_TYPE', '')
        if content_type.startswith('multipart/form-data'):
            data = request.POST.copy()
        else:
            try:
                data = json.loads(request.body or '{}')
            except ValueError:
                return JsonResponse({"error": "JSON inválido."}, status=400)
        
        if accion == 'listar_docs_dashboard':
            return JsonResponse(_admin_dashboard_docs_page(admin_actual, data))

        if accion == 'actualizar_usuario':
            u_id = data.get('id')
            usr = _mongo_find_one_by_id(DirectorioFirmas, u_id)
            if usr:
                if not _admin_es_global(admin_actual) and getattr(usr, 'tecnico_asignado', None) != admin_actual.email:
                    return JsonResponse({"error": "No tienes permiso."}, status=403)
                update_doc = {'permisos_portal': data.get('permisos', [])}
                if _admin_es_global(admin_actual) and 'tecnico_asignado' in data:
                    update_doc['tecnico_asignado'] = data.get('tecnico_asignado')
                if 'notificar_celular' in data:
                    update_doc['notificar_celular'] = data.get('notificar_celular')
                _mongo_update_document(DirectorioFirmas, usr, update_doc)
                return JsonResponse({"status": "success", "msg": "Usuario actualizado."})
            return JsonResponse({"error": "Usuario no encontrado."}, status=404)
            
        elif accion == 'eliminar_api_key':
            u_id = data.get('usuario_id')
            key_id = data.get('key_id')
            usr = _mongo_find_one_by_id(DirectorioFirmas, u_id)
            if usr:
                if not _admin_es_global(admin_actual) and getattr(usr, 'tecnico_asignado', None) != admin_actual.email:
                    return JsonResponse({"error": "No tienes permiso."}, status=403)
                
                api_keys = _json_or_default(getattr(usr, 'api_keys', []), [])
                api_keys = [k for k in api_keys if k.get('id') != key_id]
                _mongo_update_document(DirectorioFirmas, usr, {'api_keys': api_keys})
                return JsonResponse({"status": "success", "msg": "API Key eliminada."})
            return JsonResponse({"error": "Usuario no encontrado."}, status=404)

        elif accion == 'eliminar_usuario':
            u_id = data.get('id')
            usr = _mongo_find_one_by_id(DirectorioFirmas, u_id)
            if usr:
                if not _admin_es_global(admin_actual) and getattr(usr, 'tecnico_asignado', None) != admin_actual.email:
                    return JsonResponse({"error": "No tienes permiso."}, status=403)
                _mongo_delete_document(DirectorioFirmas, usr)
                return JsonResponse({"status": "success", "msg": "Usuario eliminado."})
            return JsonResponse({"error": "Usuario no encontrado."}, status=404)
            
        elif accion == 'actualizar_admin':
            if not _admin_es_global(admin_actual): return JsonResponse({"error": "Solo superadmin."}, status=403)
            a_id = data.get('id')
            a_obj = _mongo_find_one_by_id(AdministradorPortal, a_id)
            if a_obj:
                _mongo_update_document(AdministradorPortal, a_obj, {'es_superadmin': data.get('es_superadmin', False)})
                return JsonResponse({"status": "success"})
            return JsonResponse({"error": "No encontrado."}, status=404)
            
        elif accion == 'eliminar_admin':
            if not _admin_es_global(admin_actual): return JsonResponse({"error": "Solo superadmin."}, status=403)
            a_id = data.get('id')
            a_obj = _mongo_find_one_by_id(AdministradorPortal, a_id)
            if a_obj:
                if a_obj.email == "pjimenezb@raloy.com.mx": return JsonResponse({"error": "No puedes eliminar al admin maestro."})
                _mongo_delete_document(AdministradorPortal, a_obj)
                return JsonResponse({"status": "success"})
            return JsonResponse({"error": "No encontrado."}, status=404)


        if accion == 'agregar_admin':
            email = _normalizar_email(data.get('email'))
            if _mongo_find_one(AdministradorPortal, {'email': email}) is not None: return JsonResponse(
                {"error": "Ya es admin."})
            _mongo_insert_model(AdministradorPortal, {
                'email': email,
                'configuracion_dashboard': {},
                'es_superadmin': False,
            })
            return JsonResponse({"status": "success", "msg": "Admin agregado."})
        elif accion == 'cancelar_doc':
            doc = _mongo_find_proceso_by_token(data.get('token'))
            if not doc:
                return JsonResponse({"error": "No encontrado."}, status=404)
            if not _admin_tiene_acceso_proceso(admin_actual, doc):
                return JsonResponse({"error": "No tienes permiso sobre este documento."}, status=403)
            if _status_terminal_firmx(getattr(doc, 'status', '')):
                return JsonResponse({"error": "El documento ya está en estado terminal."}, status=400)

            summary_data = getattr(doc, 'summary_data', {}) or {}
            if summary_data.get('firmx_id'):
                summary_data.update({
                    'firmx_cancelled_local': True,
                    'firmx_cancelled_at': _datetime_for_mongo().isoformat(),
                    'firmx_cancelled_by': request.session.get('admin_email'),
                    'firmx_cancel_note': 'Cancelado solo en el sistema local; FIRMX no cuenta con cancelación remota.',
                })
                _actualizar_proceso_firma_mongo(doc, status='CANCELLED', summary_data=summary_data)
            else:
                _actualizar_proceso_firma_mongo(doc, status='CANCELLED')
            return JsonResponse({"status": "success"})
        elif accion == 'reenviar_firma':
            doc = _mongo_find_proceso_by_token(data.get('token'))
            if not doc:
                return JsonResponse({"error": "Documento no encontrado."}, status=404)
            if not _admin_tiene_acceso_proceso(admin_actual, doc):
                return JsonResponse({"error": "No tienes permiso sobre este documento."}, status=403)
            if doc.status != 'PROCESSING':
                return JsonResponse({"error": "Solo se puede reenviar en documentos en proceso."}, status=400)

            firmantes = _normalizar_firmantes(getattr(doc, 'firmantes', []))
            firmante_token = str(data.get('firmante_token') or '').strip()
            email = _normalizar_email(data.get('email'))
            idx = None
            if firmante_token:
                idx = _indice_por_token(firmantes, firmante_token)
            if idx is None and email:
                for i, firmante in enumerate(firmantes):
                    if _normalizar_email(firmante.get('email')) == email and not firmante.get('fecha_firma'):
                        idx = i
                        break
            if idx is None or idx < 0 or idx >= len(firmantes):
                return JsonResponse({"error": "Firmante pendiente no encontrado."}, status=404)

            firmante = firmantes[idx]
            if firmante.get('fecha_firma'):
                return JsonResponse({"error": "Ese firmante ya completó su firma."}, status=400)
            if not firmante.get('token_firmante'):
                firmante['token_firmante'] = str(uuid.uuid4())

            link_firma = f"{PUBLIC_BASE_URL}/firmar/{doc.token_acceso}/{firmante.get('token_firmante')}/"
            try:
                response = tracked_post(
                    N8N_WEBHOOK_NOTIFICAR_CORREO,
                    json={
                        "email": firmante.get('email'),
                        "nombre": firmante.get('nombre'),
                        "link": link_firma,
                        "mensaje": f"Reenvío de solicitud de firma para el documento {doc.reference_id}.",
                        "reenviado": True,
                    },
                    timeout=20,
                )
                n8n_error = _n8n_response_error(response)
                if n8n_error:
                    return JsonResponse({"error": f"N8N no confirmó el envío: {n8n_error}"}, status=502)
            except Exception as e:
                return JsonResponse({"error": f"No se pudo reenviar el correo: {e}"}, status=502)

            fecha_reenvio = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
            reenvios = _json_or_default(firmante.get('reenvios_correo', []), [])
            reenvios.append({
                'fecha': fecha_reenvio,
                'por': request.session.get('admin_email'),
                'email': firmante.get('email'),
            })
            firmante['reenvios_correo'] = reenvios
            firmante['ultimo_reenvio_correo'] = fecha_reenvio
            firmante['ultimo_reenvio_por'] = request.session.get('admin_email')
            _actualizar_proceso_firma_mongo(doc, firmantes=firmantes)
            crear_notificacion_firma(firmante.get('email'), doc.reference_id, f"Reenvío de solicitud de firma para {doc.reference_id}.")
            return JsonResponse({"status": "success", "msg": "Solicitud de firma reenviada.", "fecha": fecha_reenvio})
        elif accion == 'notificar_whatsapp':
            doc = _mongo_find_proceso_by_token(data.get('token'))
            if not doc:
                return JsonResponse({"error": "Documento no encontrado."}, status=404)
            if not _admin_tiene_acceso_proceso(admin_actual, doc):
                return JsonResponse({"error": "No tienes permiso sobre este documento."}, status=403)
            
            firmantes = _normalizar_firmantes(getattr(doc, 'firmantes', []))
            firmante_token = str(data.get('firmante_token') or '').strip()
            email = _normalizar_email(data.get('email'))
            telefono = str(data.get('telefono') or '').strip()
            link_firma = str(data.get('link') or '').strip()
            
            idx = None
            if firmante_token:
                idx = _indice_por_token(firmantes, firmante_token)
            if idx is None and email:
                for i, firmante in enumerate(firmantes):
                    if _normalizar_email(firmante.get('email')) == email and not firmante.get('fecha_firma'):
                        idx = i
                        break
            if idx is None or idx < 0 or idx >= len(firmantes):
                return JsonResponse({"error": "Firmante pendiente no encontrado."}, status=404)

            firmante = firmantes[idx]
            
            try:
                response = tracked_post(
                    'https://n8n.raloy.com.mx/webhook/dsign-recordatorio-firma',
                    json={"numero": telefono, "url": link_firma},
                    timeout=20,
                )
                n8n_error = _n8n_response_error(response)
                if n8n_error:
                    return JsonResponse({"error": f"N8N no confirmó el envío: {n8n_error}"}, status=502)
            except Exception as e:
                return JsonResponse({"error": f"No se pudo notificar por WhatsApp: {e}"}, status=502)

            fecha_whatsapp = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
            reenvios_wa = _json_or_default(firmante.get('reenvios_whatsapp', []), [])
            reenvios_wa.append({
                'fecha': fecha_whatsapp,
                'por': request.session.get('admin_email'),
                'telefono': telefono,
            })
            firmante['reenvios_whatsapp'] = reenvios_wa
            firmante['ultimo_reenvio_whatsapp'] = fecha_whatsapp
            firmante['ultimo_reenvio_whatsapp_por'] = request.session.get('admin_email')
            firmante['ultimo_telefono_whatsapp'] = telefono
            
            _actualizar_proceso_firma_mongo(doc, firmantes=firmantes)
            crear_notificacion_firma(firmante.get('email'), doc.reference_id, f"Notificación WhatsApp enviada al {telefono}.")
            return JsonResponse({"status": "success", "msg": "Notificación WhatsApp enviada.", "fecha": fecha_whatsapp, "telefono": telefono})

        elif accion == 'invitar_registro':
            try:
                tracked_post(N8N_WEBHOOK_INVITAR_REGISTRO,
                              json={"email": data.get('email'), "link": "https://dsign.raloy.com.mx/registro-firmas/"},
                              timeout=20)
            except Exception as e:
                print(f"Error en N8N_WEBHOOK_INVITAR_REGISTRO: {e}")
            return JsonResponse({"status": "success", "msg": "Invitación enviada."})
        elif accion == 'guardar_config':
            _mongo_update_document(
                AdministradorPortal,
                admin_actual,
                {'configuracion_dashboard': data.get('configuracion') or {}},
            )
            return JsonResponse({"status": "success"})
        elif accion == 'guardar_config_drive_resguardo':
            if not _admin_es_global(admin_actual):
                return JsonResponse({"error": "Solo superadmin."}, status=403)

            try:
                updates = {
                    'root_folder_id': _normalizar_drive_folder_id(data.get('root_folder_id'), 'carpeta raiz de formatos'),
                    'formatos_folder_id': _normalizar_drive_folder_id(data.get('formatos_folder_id'), 'carpeta de formatos'),
                    'pdfs_folder_id': _normalizar_drive_folder_id(data.get('pdfs_folder_id'), 'carpeta de PDFs firmados de formatos'),
                    'api_pdfs_folder_id': _normalizar_drive_folder_id(data.get('api_pdfs_folder_id'), 'carpeta de PDFs API'),
                    'contratos_base_folder_id': _normalizar_drive_folder_id(data.get('contratos_base_folder_id'), 'carpeta de contratos base'),
                    'updated_at': _datetime_for_mongo(),
                }
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)

            _mongo_update_or_insert_by_query(ConfiguracionDriveResguardo, {}, updates)
            return JsonResponse({
                "status": "success",
                "msg": "Configuración Drive guardada.",
                "drive_config": _drive_config_payload(),
            })
        elif accion == 'analizar_plantilla':
            try:
                response = tracked_post(N8N_WEBHOOK_ANALIZAR_PLANTILLA, json=data, timeout=30)
                n8n_error = _n8n_response_error(response)
                if n8n_error:
                    return JsonResponse({"error": f"N8N no pudo analizar plantilla: {n8n_error}"}, status=502)
                resp = response.json()
                return JsonResponse({"status": "success", "data": resp})
            except Exception as e:
                return JsonResponse({"error": f"Error al analizar plantilla: {e}"}, status=500)
        elif accion == 'guardar_plantilla':
            try:
                drive_storage = _preparar_estructura_drive_plantilla(data['doc_id'], _drive_root_folder_id())
            except Exception as e:
                return JsonResponse({"error": f"Excepción crítica al preparar la estructura de Drive: {str(e)}"}, status=500)
            
            _mongo_insert_model(PlantillaFormulario, {
                'nombre': data['nombre'],
                'doc_id': data['doc_id'],
                'owner_email': _normalizar_email(data['owner_email']),
                'drive_folder_id': drive_storage['formatos_folder_id'],
                'carpeta_firmados_id': drive_storage['pdfs_folder_id'],
                'drive_root_folder_id': drive_storage['root_folder_id'],
                'drive_storage_policy': DRIVE_STORAGE_POLICY,
                'view_info': data['view_info'],
                'formato_folio': data.get('formato_folio', ''),
                'contexto': data.get('contexto', ''),
                'intencion': data.get('intencion', ''),
                'variables': data.get('variables', []),
                'firmantes_config': _normalizar_firmantes(data.get('firmantes_config', [])),
                'usuarios_permitidos': data.get('usuarios_permitidos', []),
                'created_at': _datetime_for_mongo(),
            })
            return JsonResponse({"status": "success", "msg": "Plantilla preparada exitosamente."})
        elif accion == 'actualizar_plantilla':
            p = _mongo_find_one_by_id(PlantillaFormulario, data.get('id'))
            if p:
                try:
                    drive_storage = _preparar_estructura_drive_plantilla(getattr(p, 'doc_id', ''), _drive_root_folder_id())
                except Exception as e:
                    return JsonResponse({"error": f"No se pudo preparar Drive: {str(e)}"}, status=500)
                _mongo_update_document(PlantillaFormulario, p, {
                    'nombre': data.get('nombre'),
                    'formato_folio': data.get('formato_folio', ''),
                    'drive_folder_id': drive_storage['formatos_folder_id'],
                    'carpeta_firmados_id': drive_storage['pdfs_folder_id'],
                    'drive_root_folder_id': drive_storage['root_folder_id'],
                    'drive_storage_policy': DRIVE_STORAGE_POLICY,
                    'view_info': data.get('view_info'),
                    'usuarios_permitidos': data.get('usuarios_permitidos', []),
                    'variables': data.get('variables', []),
                    'firmantes_config': _normalizar_firmantes(data.get('firmantes_config', [])),
                    'contexto': data.get('contexto', getattr(p, 'contexto', '')),
                    'intencion': data.get('intencion', getattr(p, 'intencion', '')),
                })
                return JsonResponse({"status": "success", "msg": "Plantilla actualizada."})
            return JsonResponse({"error": "Plantilla no encontrada"}, status=404)
        elif accion == 'eliminar_plantilla':
            plantilla = _mongo_find_one_by_id(PlantillaFormulario, data.get('id'))
            if plantilla:
                _mongo_delete_document(PlantillaFormulario, plantilla)
            return JsonResponse({"status": "success", "msg": "Plantilla eliminada."})
        elif accion == 'guardar_carpeta_dominio':
            dominio = _normalizar_dominio(data.get('dominio'))
            folder_id = str(data.get('drive_folder_id', '')).strip()
            carpeta_id = str(data.get('id', '') or '').strip()
            if not dominio or not folder_id:
                return JsonResponse({"error": "Faltan dominio e ID de Google Drive."}, status=400)

            try:
                brand_color = _normalizar_hex_color(data.get('brand_color'), BRAND_DEFAULT_COLOR)
            except ValueError as e:
                return JsonResponse({"error": str(e)}, status=400)

            carpeta_actual = _mongo_find_one_by_id(CarpetaDominio, carpeta_id) if carpeta_id else None
            carpeta_mismo_dominio = _mongo_find_one(CarpetaDominio, {'dominio': dominio})
            if carpeta_actual and carpeta_mismo_dominio and str(getattr(carpeta_actual, 'id', '')) != str(getattr(carpeta_mismo_dominio, 'id', '')):
                return JsonResponse({"error": "Ya existe una configuración para ese dominio."}, status=400)

            updates = {
                'dominio': dominio,
                'drive_folder_id': folder_id,
                'brand_color': brand_color,
                'updated_at': _datetime_for_mongo(),
            }

            if dominio == BRAND_DEFAULT_DOMAIN and not getattr(carpeta_actual or carpeta_mismo_dominio, 'logo_url', ''):
                updates['logo_url'] = BRAND_DEFAULT_LOGO_URL
                updates['logo_path'] = ''

            try:
                logo_data = _guardar_logo_dominio(request.FILES.get('logo'), dominio)
            except ValueError as e:
                return JsonResponse({"error": str(e)}, status=400)

            if logo_data:
                old_logo_path = getattr(carpeta_actual or carpeta_mismo_dominio, 'logo_path', '')
                updates.update(logo_data)
            else:
                old_logo_path = ''

            if carpeta_actual:
                _mongo_update_document(CarpetaDominio, carpeta_actual, updates)
                carpeta_guardada = carpeta_actual
            else:
                updates['created_at'] = getattr(carpeta_mismo_dominio, 'created_at', None) or _datetime_for_mongo()
                carpeta_guardada, _ = _mongo_update_or_insert_by_query(CarpetaDominio, {'dominio': dominio}, updates)

            if logo_data and old_logo_path and old_logo_path != updates.get('logo_path'):
                _eliminar_logo_dominio(old_logo_path)

            return JsonResponse({
                "status": "success",
                "msg": "Configuración de dominio guardada.",
                "carpeta": _carpeta_dominio_payload(carpeta_guardada),
            })
        elif accion == 'eliminar_carpeta_dominio':
            carpeta = _mongo_find_one_by_id(CarpetaDominio, data.get('id'))
            if carpeta:
                _eliminar_logo_dominio(getattr(carpeta, 'logo_path', ''))
                _mongo_delete_document(CarpetaDominio, carpeta)
            return JsonResponse({"status": "success", "msg": "Configuración eliminada."})
    return JsonResponse({"error": "Acción inválida"}, status=400)
# ================= NUEVAS VISTAS ADMIN =================

def admin_usuarios(request):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    
    admin_obj = _mongo_find_one(AdministradorPortal, {'email': admin_email})
    if not admin_obj:
        raise Http404("Administrador no encontrado")
    
    if getattr(admin_obj, 'es_superadmin', False) or admin_email == 'pjimenezb@raloy.com.mx':
        usuarios = _mongo_find(DirectorioFirmas, {}, [('fecha_registro', -1)])
    else:
        usuarios = _mongo_find(DirectorioFirmas, {'tecnico_asignado': admin_email}, [('fecha_registro', -1)])
        
    lista_usrs = []
    permisos_labels = {
        'api_tester': 'API',
        'plantillas': 'Plantillas',
        'firmx': 'FIRMX',
    }
    ahora = timezone.now()
    for u in usuarios:
        tot_docs = _mongo_count(ProcesoFirma, {'owner_email': u.email})
        ultima_actividad = getattr(u, 'ultima_actividad', None)
        ultima_compare = _datetime_for_compare(ultima_actividad) if hasattr(ultima_actividad, 'strftime') else None
        if ultima_compare:
            dias_inactivo = (ahora - ultima_compare).days
            if dias_inactivo <= 7:
                actividad_grupo = 'Reciente'
            elif dias_inactivo <= 30:
                actividad_grupo = 'Este mes'
            else:
                actividad_grupo = 'Inactivo +30d'
            ultima_act = ultima_actividad.strftime("%d/%m/%Y %H:%M")
        else:
            dias_inactivo = ''
            actividad_grupo = 'Sin actividad'
            ultima_act = 'Nunca'

        email_usuario = getattr(u, 'email', '') or ''
        fecha_registro = getattr(u, 'fecha_registro', None)
        if hasattr(fecha_registro, 'strftime'):
            fecha_registro_label = fecha_registro.strftime("%d/%m/%Y")
        else:
            fecha_registro_label = str(fecha_registro) if fecha_registro else 'Sin fecha'
        dominio = email_usuario.split('@', 1)[1].lower() if '@' in email_usuario else 'Sin dominio'
        permisos = _json_or_default(getattr(u, 'permisos_portal', []), [])
        permisos_legibles = [permisos_labels.get(permiso, permiso) for permiso in permisos]
        lista_usrs.append({
            'id': u.id,
            'nombre': getattr(u, 'nombre', ''),
            'email': email_usuario,
            'puesto': getattr(u, 'puesto', '') or 'Sin puesto',
            'iniciales': getattr(u, 'iniciales', '') or '',
            'dominio': dominio,
            'tecnico': getattr(u, 'tecnico_asignado', None) or 'Sin asignar',
            'ultima_act': ultima_act,
            'actividad_grupo': actividad_grupo,
            'dias_inactivo': dias_inactivo,
            'fecha_registro': fecha_registro_label,
            'tot_docs': tot_docs,
            'docs_grupo': 'Sin documentos' if tot_docs == 0 else ('1-5 docs' if tot_docs <= 5 else '6+ docs'),
            'permisos': permisos,
            'permisos_label': ', '.join(permisos_legibles) if permisos_legibles else 'Sin permisos',
            'notificar_celular': bool(getattr(u, 'notificar_celular', False)),
            'notificar_label': 'App móvil activa' if getattr(u, 'notificar_celular', False) else 'Solo correo',
        })
        
    return render(request, 'motor_firmas/admin_usuarios.html', {
        'admin_email': admin_email,
        'es_superadmin': getattr(admin_obj, 'es_superadmin', False) or admin_email == 'pjimenezb@raloy.com.mx',
        'usuarios': lista_usrs
    })

def admin_usuarios_detalle(request, usuario_id):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    
    admin_obj = _mongo_find_one(AdministradorPortal, {'email': admin_email})
    usuario = _mongo_find_one_by_id(DirectorioFirmas, usuario_id)
    if not admin_obj or not usuario:
        raise Http404("Registro no encontrado")
    
    if not getattr(admin_obj, 'es_superadmin', False) and admin_email != 'pjimenezb@raloy.com.mx' and getattr(usuario, 'tecnico_asignado', None) != admin_email:
        return HttpResponse("<h1>No tienes permisos para ver a este usuario.</h1>", status=403)
        
    tecnicos = _mongo_find(AdministradorPortal, {}, [('email', 1)])
    
    permisos = _json_or_default(getattr(usuario, 'permisos_portal', []), [])

    usuario.api_keys = _json_or_default(getattr(usuario, 'api_keys', []), [])
    return render(request, 'motor_firmas/admin_usuarios_detalle.html', {
        'admin_email': admin_email,
        'es_superadmin': getattr(admin_obj, 'es_superadmin', False) or admin_email == 'pjimenezb@raloy.com.mx',
        'usuario': usuario,
        'tecnicos': tecnicos,
        'permisos': permisos
    })

def admin_administradores(request):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    
    admin_obj = _mongo_find_one(AdministradorPortal, {'email': admin_email})
    if not admin_obj:
        raise Http404("Administrador no encontrado")
    if not _admin_es_global(admin_obj):
        return HttpResponse("<h1>Acceso denegado. Solo superadministradores.</h1>", status=403)
        
    admins = _mongo_find(AdministradorPortal, {}, [('email', 1)])
    return render(request, 'motor_firmas/admin_administradores.html', {
        'admin_email': admin_email,
        'admins': admins
    })


@csrf_exempt
def dev036_check_alerts(request):
    """
    DEV036 (El Apéndice): Motor de escucha y procesador de alertas pendientes.
    Consulta la colección gestionada por DEV108 (signatures_master).
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"has_new_signature": False, "error": "JSON inválido."}, status=400)

    try:
        email = _normalizar_email(data.get('email'))
        if not email:
            return JsonResponse({"has_new_signature": False, "error": "Email is required"}, status=400)

        from .models import SignaturesMaster
        primer_registro = _mongo_collection(SignaturesMaster).find_one(
            {
                'user_email': email,
                'notification_enabled': True,
                'notified_to_mobile': False,
            },
            sort=[('id', 1)],
        )
        if primer_registro:
            ref_id = primer_registro.get('reference_id')
            # Acción Atómica: actualizar estado
            _mongo_collection(SignaturesMaster).update_one(
                {'_id': primer_registro['_id']},
                {
                    '$set': {
                        'notified_to_mobile': True,
                        'updated_at': timezone.now().replace(tzinfo=None),
                    }
                },
            )
            return JsonResponse({"has_new_signature": True, "reference_id": ref_id})
        else:
            return JsonResponse({"has_new_signature": False})
    except Exception as e:
        return JsonResponse({"has_new_signature": False, "error": str(e)}, status=500)


@csrf_exempt
def check_notifications(request):
    """
    DEV108 (Cerebro): Endpoint Público Proxy Síncrono hacia DEV036.
    """
    import requests
    import os
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({"has_new_signature": False, "error": "JSON inválido."}, status=400)

    try:
        email = data.get('email')
        if not email:
            return JsonResponse({"error": "Email is required"}, status=400)

        # Proxy Síncrono a DEV036
        dev036_url = os.environ.get('DEV036_URL')

        if not dev036_url:
            # Anti-fallos: Si no está definida la URL del microservicio externo DEV036,
            # utilizamos la función interna de respaldo de manera síncrona.
            return dev036_check_alerts(request)

        # Timeout de no más de 5 segundos según protocolo
        response = tracked_post(
            dev036_url,
            json={"email": email},
            timeout=5
        )
        response.raise_for_status()
        return JsonResponse(response.json())

    except requests.exceptions.Timeout:
        return JsonResponse({"has_new_signature": False, "error": "Timeout DEV036"}, status=504)
    except Exception as e:
        return JsonResponse({"has_new_signature": False, "error": str(e)}, status=500)

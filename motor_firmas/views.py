import os
import json
import requests
import traceback
import re
import uuid
import shutil
from datetime import datetime, timedelta
from types import SimpleNamespace
from django.conf import settings
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from .models import ProcesoFirma, DirectorioFirmas, OTPLogin, AdministradorPortal, PlantillaFormulario, CarpetaDominio, \
    DocumentoPDFUsuario
from .utils import estampar_firma_en_pdf, estampar_variables_en_pdf, crear_notificacion_firma

# WEBHOOKS DE N8N
N8N_WEBHOOK_NOTIFICAR_CORREO = "https://n8n.raloy.com.mx/webhook/enviar-correo-firma"
N8N_WEBHOOK_FINALIZAR_PROCESO = "https://n8n.raloy.com.mx/webhook/subir-pdf-final"
N8N_WEBHOOK_NOTIFICAR_OWNER = "https://n8n.raloy.com.mx/webhook/notificar-owner"
N8N_WEBHOOK_RECUPERAR_PIN = "https://n8n.raloy.com.mx/webhook/recuperar-pin-firma"
N8N_WEBHOOK_ENVIAR_OTP = "https://n8n.raloy.com.mx/webhook/enviar-otp-portal"
N8N_WEBHOOK_INVITAR_REGISTRO = "https://n8n.raloy.com.mx/webhook/invitar-registro-firma"
N8N_WEBHOOK_ANALIZAR_PLANTILLA = "https://n8n.raloy.com.mx/webhook/analizar-plantilla"
N8N_WEBHOOK_PREPARAR_DIR = "https://n8n.raloy.com.mx/webhook/preparar-directorio"
N8N_WEBHOOK_SUBIR_PDF_USUARIO = "https://n8n.raloy.com.mx/webhook/subir-pdf-usuario"

_MONGO_CLIENT = None


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
    return [f for f in firmantes if isinstance(f, dict)]


def _normalizar_email(email):
    return str(email or '').strip().lower()


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
    value = _json_or_default(value, default)
    return json.dumps(value, ensure_ascii=False)


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
        'created_at': timezone.now().replace(tzinfo=None),
    }
    _mongo_collection(ProcesoFirma).insert_one(document)
    return _mongo_to_namespace(document)


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
            dir_drive = data.get('dir', '')
            exec_mode = data.get('exec', 'normal')

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
                requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
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
                    requests.post(N8N_WEBHOOK_NOTIFICAR_OWNER,
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

    message_context = {'token': token, 'view_info': proceso.view_info, 'summary_data': summary_data,
                       'pdf_url': f"{settings.MEDIA_URL}{os.path.basename(proceso.pdf_path)}", 'is_message_view': True}

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

    cant_firmas = len(indices_turno)

    context = {'token': token, 'firmante_token': firmante_token or '',
               'nombre_firmante': firmante_actual.get('nombre', 'Firmante'),
               'email_firmante': firmante_actual.get('email', ''), 'view_info': proceso.view_info,
               'summary_data': summary_data,
               'pdf_url': f"{settings.MEDIA_URL}{os.path.basename(proceso.pdf_path)}",
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

        if not os.path.exists(proceso.pdf_path):
            return JsonResponse({"error": "El PDF del proceso no existe en el servidor."}, status=400)
        backup_path = f"{proceso.pdf_path}.{uuid.uuid4().hex}.bak"
        shutil.copyfile(proceso.pdf_path, backup_path)

        variables = _json_or_default(data.get('variables', {}), {})
        if variables:
            valores_capturados = _json_or_default(proceso.valores_capturados, {})
            valores_capturados.update(variables)
            proceso.valores_capturados = valores_capturados
            estampar_variables_en_pdf(proceso.pdf_path, variables)

        fecha_firma = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
        for idx in indices_turno:
            firmante = firmantes_lista[idx]
            coords = firmante.get('coordenadas')
            nombre = firmante.get('nombre') or firmante_esperado.get('nombre') or 'Firmante'
            document_hash = estampar_firma_en_pdf(
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
            )
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
                requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
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

        todos_los_correos = [f.get('email') for f in firmantes_lista if f.get('email')]
        if proceso.owner_email:
            todos_los_correos.append(proceso.owner_email)

            link_trazabilidad = f"https://dsign.raloy.com.mx/trazabilidad/{proceso.token_acceso}/"
            try:
                requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
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

        with open(proceso.pdf_path, 'rb') as f:
            try:
                resp_n8n = requests.post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                              data={"reference_id": proceso.reference_id, "status": "COMPLETED",
                                    "correos_destino": correos, "folder_id": proceso.dir_drive}, files={
                        "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")}, timeout=30)

                if resp_n8n.status_code != 200:
                    print(f"Fallo en la comunicación con el webhook de finalización (N8N): {resp_n8n.text}")
            except Exception as e:
                print(f"Error en N8N_WEBHOOK_FINALIZAR_PROCESO: {e}")

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


def vista_trazabilidad(request, token):
    proceso = _get_proceso_por_token_or_404(token)
    return render(request, 'motor_firmas/trazabilidad.html',
                  {'proceso': proceso, 'pdf_url': f"{settings.MEDIA_URL}{os.path.basename(proceso.pdf_path)}"})


@csrf_exempt
def registro_firmas(request):
    if request.method == 'POST':
        email = _normalizar_email(request.POST.get('email'))
        if _mongo_find_one(DirectorioFirmas, {'email': email}) is not None: return render(request,
                                                                                'motor_firmas/registro_firmas.html',
                                                                                {"error": "Correo registrado."})
        _mongo_insert_model(DirectorioFirmas, {
            'nombre': request.POST.get('nombre'),
            'email': email,
            'puesto': request.POST.get('puesto'),
            'iniciales': request.POST.get('iniciales'),
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
            requests.post(N8N_WEBHOOK_RECUPERAR_PIN, json={"email": colaborador.email, "nombre": colaborador.nombre,
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
        requests.post(N8N_WEBHOOK_ENVIAR_OTP, json={"email": email, "otp": otp_record.otp_code}, timeout=20)
    except Exception as e:
        print(f"Error en N8N_WEBHOOK_ENVIAR_OTP: {e}")
    return JsonResponse({"status": "success", "msg": "PIN temporal enviado."})


def portal_dashboard(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    documentos = _mongo_find(ProcesoFirma, {'owner_email': owner_email}, [('created_at', -1)])
    lista_docs = []
    for doc in documentos:
        firmantes = _normalizar_firmantes(getattr(doc, 'firmantes', []))
        tot = len(firmantes)
        hechas = sum(1 for f in firmantes if f.get('fecha_firma'))
        lista_docs.append({'proceso': doc, 'total_firmas': tot, 'firmas_hechas': hechas,
                           'porcentaje': int((hechas / tot) * 100) if tot > 0 else 0})

    dominio = owner_email.split('@')[1] if '@' in owner_email else ''
    tiene_carpeta_dominio = _mongo_find_one(CarpetaDominio, {'dominio': dominio}) is not None

    colaborador = _mongo_find_one(DirectorioFirmas, {'email': owner_email})
    permisos = getattr(colaborador, 'permisos_portal', []) if colaborador else []
    permisos = _json_or_default(permisos, [])

    return render(request, 'motor_firmas/portal_dashboard.html', {
        'owner_email': owner_email, 
        'documentos': lista_docs,
        'tiene_carpeta_dominio': tiene_carpeta_dominio,
        'permisos': permisos
    })


def portal_logout(request):
    request.session.flush()
    return redirect('portal_login')


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
    return render(request, 'motor_firmas/portal_plantillas.html',
                  {'plantillas': permitidas, 'owner_email': owner_email})


def portal_usar_plantilla(request, plantilla_id):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    plantilla = _mongo_find_one_by_id(PlantillaFormulario, plantilla_id)
    if not plantilla:
        raise Http404("Plantilla no encontrada")
    plantilla.variables = _json_or_default(plantilla.variables, [])
    plantilla.firmantes_config = _json_or_default(plantilla.firmantes_config, [])
    plantilla.usuarios_permitidos = _json_or_default(plantilla.usuarios_permitidos, [])
    return render(request, 'motor_firmas/portal_usar_plantilla.html',
                  {'plantilla': plantilla, 'owner_email': owner_email})


# ================= VISTAS DE PDFS LIBRES (DRAG & DROP) =================
def portal_pdfs_usuario(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    pdfs = _mongo_find(DocumentoPDFUsuario, {'owner_email': owner_email}, [('created_at', -1)])

    return render(request, 'motor_firmas/portal_pdfs_usuario.html', {'pdfs': pdfs, 'owner_email': owner_email})


@csrf_exempt
def eliminar_pdf_usuario(request, pdf_id):
    owner_email = request.session.get('owner_email')
    if not owner_email: return JsonResponse({"error": "No autorizado"}, status=403)

    doc = _mongo_find_one_by_uuid_field(DocumentoPDFUsuario, 'id_documento', pdf_id, {'owner_email': owner_email})
    if doc is None:
        doc = _mongo_find_one_by_id_text(DocumentoPDFUsuario, pdf_id, {'owner_email': owner_email})

    if doc is not None:
        archivo_local = getattr(doc, 'archivo_local', None)
        if archivo_local:
            full_path = os.path.join(settings.MEDIA_ROOT, archivo_local)
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                except:
                    pass

        _mongo_collection(DocumentoPDFUsuario).delete_one({'_id': doc.id})
        return JsonResponse({"status": "success"})

    return JsonResponse({"error": "Documento no encontrado"}, status=404)


def portal_subir_pdf(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    return render(request, 'motor_firmas/portal_subir_pdf.html', {'owner_email': owner_email})


@csrf_exempt
def subir_pdf_usuario(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return JsonResponse({"error": "No autenticado"}, status=403)
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido."}, status=405)

    pdf_file = request.FILES.get('pdf_file')
    if not pdf_file: return JsonResponse({"error": "No se seleccionó ningún archivo PDF."}, status=400)

    dominio = owner_email.split('@')[1] if '@' in owner_email else ''
    carpeta_dom = _mongo_find_one(CarpetaDominio, {'dominio': dominio})
    if not carpeta_dom: return JsonResponse(
        {"error": f"Tu dominio (@{dominio}) no tiene asignada una carpeta en Google Drive."}, status=400)

    try:
        files = {'data': (pdf_file.name, pdf_file.read(), 'application/pdf')}
        pdf_file.seek(0)
        resp = requests.post(N8N_WEBHOOK_SUBIR_PDF_USUARIO, data={'folder_id': carpeta_dom.drive_folder_id},
                             files=files, timeout=30).json()

        if resp.get('status') == 'success':
            id_documento = str(uuid.uuid4())
            safe_filename = f"{uuid.uuid4()}_{pdf_file.name}"
            os.makedirs(os.path.join(settings.MEDIA_ROOT, 'pdfs_libres'), exist_ok=True)
            local_path = os.path.join('pdfs_libres', safe_filename)
            with open(os.path.join(settings.MEDIA_ROOT, local_path), 'wb+') as f:
                for chunk in pdf_file.chunks(): f.write(chunk)

            _mongo_collection(DocumentoPDFUsuario).insert_one({
                'id_documento': id_documento,
                'nombre': pdf_file.name,
                'drive_file_id': resp.get('file_id'),
                'owner_email': owner_email,
                'archivo_local': local_path,
                'enviado_a_firma': False,
                'created_at': timezone.now().replace(tzinfo=None),
            })
            return JsonResponse({"status": "success", "nombre": pdf_file.name, "id": id_documento})
        else:
            return JsonResponse({"error": "N8n falló al subir a Drive."})
    except Exception as e:
        return JsonResponse({"error": f"Error: {e}"})


def portal_configurar_pdf(request, pdf_id):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    doc = _mongo_find_one_by_uuid_field(DocumentoPDFUsuario, 'id_documento', pdf_id, {'owner_email': owner_email})
    if not doc:
        raise Http404("Documento PDF no encontrado")
    pdf_url = f"{settings.MEDIA_URL}{getattr(doc, 'archivo_local', '')}"
    return render(request, 'motor_firmas/portal_configurar_pdf.html',
                  {'doc': doc, 'pdf_url': pdf_url, 'owner_email': owner_email})


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

    firmantes = _normalizar_firmantes(data.get('firmantes', []))
    if not firmantes:
        return JsonResponse({"error": "Añade al menos un firmante."}, status=400)
    for f in firmantes: f['token_firmante'] = str(uuid.uuid4())

    original_path = os.path.join(settings.MEDIA_ROOT, getattr(doc, 'archivo_local', ''))
    if not os.path.exists(original_path):
        return JsonResponse({"error": "El PDF original no existe en el servidor."}, status=400)

    ref_id = f"LIBRE-{int(timezone.now().timestamp())}"
    counter = 1
    while _mongo_find_one(ProcesoFirma, {'reference_id': ref_id}) is not None:
        ref_id = f"LIBRE-{int(timezone.now().timestamp())}-{counter}"
        counter += 1
    final_path = os.path.join(settings.MEDIA_ROOT, f"{ref_id}.pdf")
    shutil.copyfile(original_path, final_path)

    dominio = owner_email.split('@')[1] if '@' in owner_email else ''
    carpeta_dom = _mongo_find_one(CarpetaDominio, {'dominio': dominio})

    proceso = _crear_proceso_firma_mongo(
        reference_id=ref_id, pdf_path=final_path, firmantes=firmantes,
        indice_actual=1, view_info="file", owner_email=owner_email,
        dir_drive=carpeta_dom.drive_folder_id if carpeta_dom else '', exec_mode="libre"
    )

    primer_firmante = firmantes[0]
    link_firma = f"https://dsign.raloy.com.mx/firmar/{proceso.token_acceso}/{primer_firmante.get('token_firmante', '')}/"
    try:
        requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                      json={"email": primer_firmante.get('email'), "nombre": primer_firmante.get('nombre'), "link": link_firma,
                            "mensaje": f"Raloy solicita tu firma para el documento libre {ref_id}."},
                      timeout=20)
    except Exception as e:
        print(f"Error en N8N_WEBHOOK_NOTIFICAR_CORREO: {e}")
    crear_notificacion_firma(primer_firmante.get('email'), ref_id, f"Raloy solicita tu firma para el documento libre {ref_id}.")

    link_trazabilidad = f"https://dsign.raloy.com.mx/trazabilidad/{proceso.token_acceso}/"
    try:
        requests.post(N8N_WEBHOOK_NOTIFICAR_OWNER,
                      json={"email": owner_email, "reference_id": ref_id, "link": link_trazabilidad},
                      timeout=20)
    except Exception as e:
        print(f"Error en N8N_WEBHOOK_NOTIFICAR_OWNER: {e}")
    crear_notificacion_firma(owner_email, ref_id, f"Has iniciado el proceso de firma libre para {ref_id}.")

    if os.path.exists(original_path):
        os.remove(original_path)
    _mongo_collection(DocumentoPDFUsuario).delete_one({'_id': doc.id})

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
        todos_docs = _mongo_find(ProcesoFirma, {}, [('created_at', -1)])
        plantillas = _mongo_find(PlantillaFormulario, {}, [('created_at', -1)])
    else:
        usuarios_asignados = _mongo_find(DirectorioFirmas, {'tecnico_asignado': admin_email})
        emails_asignados = [u.email for u in usuarios_asignados if getattr(u, 'email', None)]
        owners_permitidos = list({admin_email, *emails_asignados})
        todos_docs = _mongo_find(ProcesoFirma, {'owner_email': {'$in': owners_permitidos}}, [('created_at', -1)])
        plantillas = _mongo_find(PlantillaFormulario, {'owner_email': {'$in': owners_permitidos}}, [('created_at', -1)])
    docs_json = []
    for d in todos_docs:
        firmantes = _normalizar_firmantes(getattr(d, 'firmantes', []))
        owner_doc = getattr(d, 'owner_email', '') or ''
        created_at = getattr(d, 'created_at', None)
        docs_json.append({'reference_id': d.reference_id, 'token': str(d.token_acceso), 'owner_email': owner_doc or 'N/A',
                          'dominio': owner_doc.split('@')[1] if '@' in owner_doc else 'N/A',
                          'status': d.status, 'fecha': created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else '',
                          'progreso': f"{sum(1 for f in firmantes if f.get('fecha_firma'))}/{len(firmantes)}"})
    carpetas_dominio = [
        {'id': str(c.id), 'dominio': c.dominio, 'drive_folder_id': c.drive_folder_id}
        for c in _mongo_find(CarpetaDominio, {}, [('dominio', 1)])
    ]
    return render(request, 'motor_firmas/admin_dashboard.html',
                  {'admin_email': admin_email, 'docs_json': json.dumps(docs_json),
                   'saved_config': json.dumps(_json_or_default(getattr(admin_obj, 'configuracion_dashboard', {}), {})),
                   'plantillas': plantillas,
                   'carpetas_dominio': json.dumps(carpetas_dominio),
                   'es_superadmin': getattr(admin_obj, 'es_superadmin', False)})


def admin_logout(request):
    request.session.flush()
    return redirect('admin_login')


def admin_crear_plantilla(request):
    if not request.session.get('admin_email'): return redirect('admin_login')
    return render(request, 'motor_firmas/admin_crear_plantilla.html',
                  {'admin_email': request.session.get('admin_email')})


def admin_editar_plantilla(request, plantilla_id):
    if not request.session.get('admin_email'): return redirect('admin_login')
    plantilla = _mongo_find_one_by_id(PlantillaFormulario, plantilla_id)
    if not plantilla:
        raise Http404("Plantilla no encontrada")
    plantilla.variables = _json_or_default(plantilla.variables, [])
    plantilla.firmantes_config = _json_or_default(plantilla.firmantes_config, [])
    plantilla.usuarios_permitidos = _json_or_default(plantilla.usuarios_permitidos, [])
    return render(request, 'motor_firmas/admin_editar_plantilla.html',
                  {'admin_email': request.session.get('admin_email'), 'plantilla': plantilla})


@csrf_exempt
def admin_api(request, accion):
    if not request.session.get('admin_email'): return JsonResponse({"error": "No autorizado"}, status=403)
    admin_actual = _mongo_find_one(AdministradorPortal, {'email': request.session.get('admin_email')})
    if not admin_actual:
        return JsonResponse({"error": "Sesión de admin inválida"}, status=403)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body or '{}')
        except ValueError:
            return JsonResponse({"error": "JSON inválido."}, status=400)
        
        if accion == 'actualizar_usuario':
            u_id = data.get('id')
            usr = _mongo_find_one_by_id(DirectorioFirmas, u_id)
            if usr:
                if not getattr(admin_actual, 'es_superadmin', False) and admin_actual.email != 'pjimenezb@raloy.com.mx' and getattr(usr, 'tecnico_asignado', None) != admin_actual.email:
                    return JsonResponse({"error": "No tienes permiso."}, status=403)
                update_doc = {'permisos_portal': data.get('permisos', [])}
                if (getattr(admin_actual, 'es_superadmin', False) or admin_actual.email == 'pjimenezb@raloy.com.mx') and 'tecnico_asignado' in data:
                    update_doc['tecnico_asignado'] = data.get('tecnico_asignado')
                if 'notificar_celular' in data:
                    update_doc['notificar_celular'] = data.get('notificar_celular')
                _mongo_update_document(DirectorioFirmas, usr, update_doc)
                return JsonResponse({"status": "success", "msg": "Usuario actualizado."})
            return JsonResponse({"error": "Usuario no encontrado."}, status=404)
            
        elif accion == 'eliminar_usuario':
            u_id = data.get('id')
            usr = _mongo_find_one_by_id(DirectorioFirmas, u_id)
            if usr:
                if not getattr(admin_actual, 'es_superadmin', False) and getattr(usr, 'tecnico_asignado', None) != admin_actual.email:
                    return JsonResponse({"error": "No tienes permiso."}, status=403)
                _mongo_delete_document(DirectorioFirmas, usr)
                return JsonResponse({"status": "success", "msg": "Usuario eliminado."})
            return JsonResponse({"error": "Usuario no encontrado."}, status=404)
            
        elif accion == 'actualizar_admin':
            if not getattr(admin_actual, 'es_superadmin', False): return JsonResponse({"error": "Solo superadmin."}, status=403)
            a_id = data.get('id')
            a_obj = _mongo_find_one_by_id(AdministradorPortal, a_id)
            if a_obj:
                _mongo_update_document(AdministradorPortal, a_obj, {'es_superadmin': data.get('es_superadmin', False)})
                return JsonResponse({"status": "success"})
            return JsonResponse({"error": "No encontrado."}, status=404)
            
        elif accion == 'eliminar_admin':
            if not getattr(admin_actual, 'es_superadmin', False): return JsonResponse({"error": "Solo superadmin."}, status=403)
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
            if doc:
                _actualizar_proceso_firma_mongo(doc, status='CANCELLED')
                return JsonResponse({"status": "success"})
            return JsonResponse({"error": "No encontrado."}, status=404)
        elif accion == 'invitar_registro':
            try:
                requests.post(N8N_WEBHOOK_INVITAR_REGISTRO,
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
        elif accion == 'analizar_plantilla':
            try:
                resp = requests.post(N8N_WEBHOOK_ANALIZAR_PLANTILLA, json=data, timeout=30).json()
                return JsonResponse({"status": "success", "data": resp})
            except Exception as e:
                return JsonResponse({"error": f"Error al analizar plantilla: {e}"}, status=500)
        elif accion == 'guardar_plantilla':
            carpeta_firmados = data['drive_folder_id']
            try:
                resp_dir = requests.post(N8N_WEBHOOK_PREPARAR_DIR,
                                         json={"doc_id": data['doc_id'], "parent_folder": data['drive_folder_id']},
                                         timeout=20)
                if resp_dir.status_code != 200:
                    return JsonResponse({"error": f"Fallo al preparar directorio en Drive. Código HTTP: {resp_dir.status_code}"}, status=500)

                try:
                    resp_json = resp_dir.json()
                    if isinstance(resp_json, dict) and resp_json.get('status') == 'success':
                        carpeta_firmados = resp_json.get('firmados_folder_id', data['drive_folder_id'])
                except ValueError:
                    print(f"Advertencia: Respuesta de N8N_WEBHOOK_PREPARAR_DIR no es JSON válido. Body: {resp_dir.text}")
            except Exception as e:
                return JsonResponse({"error": f"Excepción crítica al preparar la estructura de Drive: {str(e)}"}, status=500)
            
            _mongo_insert_model(PlantillaFormulario, {
                'nombre': data['nombre'],
                'doc_id': data['doc_id'],
                'owner_email': _normalizar_email(data['owner_email']),
                'drive_folder_id': data['drive_folder_id'],
                'carpeta_firmados_id': carpeta_firmados,
                'view_info': data['view_info'],
                'formato_folio': data.get('formato_folio', ''),
                'contexto': data.get('contexto', ''),
                'intencion': data.get('intencion', ''),
                'variables': data.get('variables', []),
                'firmantes_config': data.get('firmantes_config', []),
                'usuarios_permitidos': data.get('usuarios_permitidos', []),
                'created_at': _datetime_for_mongo(),
            })
            return JsonResponse({"status": "success", "msg": "Plantilla preparada exitosamente."})
        elif accion == 'actualizar_plantilla':
            p = _mongo_find_one_by_id(PlantillaFormulario, data.get('id'))
            if p:
                _mongo_update_document(PlantillaFormulario, p, {
                    'nombre': data.get('nombre'),
                    'formato_folio': data.get('formato_folio', ''),
                    'drive_folder_id': data.get('drive_folder_id'),
                    'view_info': data.get('view_info'),
                    'usuarios_permitidos': data.get('usuarios_permitidos', []),
                    'variables': data.get('variables', []),
                    'firmantes_config': data.get('firmantes_config', []),
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
            dominio, folder_id = data.get('dominio', '').strip().lower(), data.get('drive_folder_id', '').strip()
            if not dominio or not folder_id: return JsonResponse({"error": "Faltan campos"}, status=400)
            _mongo_update_or_insert_by_query(
                CarpetaDominio,
                {'dominio': dominio},
                {'drive_folder_id': str(folder_id), 'created_at': _datetime_for_mongo()},
            )
            return JsonResponse({"status": "success", "msg": "Carpeta asignada."})
        elif accion == 'eliminar_carpeta_dominio':
            carpeta = _mongo_find_one_by_id(CarpetaDominio, data.get('id'))
            if carpeta:
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
    for u in usuarios:
        tot_docs = _mongo_count(ProcesoFirma, {'owner_email': u.email})
        ultima_actividad = getattr(u, 'ultima_actividad', None)
        # Calculate effectiveness simply as percentage of documents signed or created
        lista_usrs.append({
            'id': u.id,
            'nombre': getattr(u, 'nombre', ''),
            'email': getattr(u, 'email', ''),
            'tecnico': getattr(u, 'tecnico_asignado', None) or 'Sin asignar',
            'ultima_act': ultima_actividad.strftime("%d/%m/%Y %H:%M") if ultima_actividad else 'Nunca',
            'tot_docs': tot_docs
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
    if not getattr(admin_obj, 'es_superadmin', False):
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
        response = requests.post(
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

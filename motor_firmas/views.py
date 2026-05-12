import os
import json
import requests
import traceback
import re
import uuid
import shutil
from datetime import datetime
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import ProcesoFirma, DirectorioFirmas, OTPLogin, AdministradorPortal, PlantillaFormulario, CarpetaDominio, \
    DocumentoPDFUsuario
from .utils import estampar_firma_en_pdf, estampar_variables_en_pdf

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


@csrf_exempt
def recibir_documento_n8n(request):
    if request.method == 'POST':
        try:
            pdf_file = request.FILES.get('pdf_file')
            data = json.loads(request.POST.get('data'))
            ref_id = data['reference_id']
            firmantes = data['firmantes']
            view_info = data.get('view_info', 'file')
            summary_data = data.get('summary_data', {})
            owner_email = data.get('owner', '')
            dir_drive = data.get('dir', '')
            exec_mode = data.get('exec', 'normal')

            document_variables = data.get('variables_asignadas', data.get('document_variables', {}))

            for f in firmantes:
                if 'token_firmante' not in f: f['token_firmante'] = str(uuid.uuid4())

            original_ref_id = ref_id
            match = re.search(r'^(.*?-)(\d+)$', ref_id)
            if match:
                base_name, num_str = match.group(1), match.group(2)
                num_len, current_num = len(num_str), int(num_str)
                while ProcesoFirma.objects.filter(reference_id=ref_id).exists():
                    current_num += 1
                    ref_id = f"{base_name}{str(current_num).zfill(num_len)}"
            else:
                counter = 1
                while ProcesoFirma.objects.filter(reference_id=ref_id).exists():
                    ref_id = f"{original_ref_id}-{counter}"
                    counter += 1

            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
            file_path = os.path.join(settings.MEDIA_ROOT, f"{ref_id}.pdf")
            with open(file_path, 'wb+') as destination:
                for chunk in pdf_file.chunks(): destination.write(chunk)

            proceso = ProcesoFirma.objects.create(
                reference_id=ref_id, pdf_path=file_path, firmantes=firmantes, indice_actual=1,
                view_info=view_info, summary_data=summary_data, owner_email=owner_email,
                dir_drive=dir_drive, exec_mode=exec_mode, document_variables=document_variables
            )

            primer_firmante = firmantes[0]
            link_firma = f"https://dsign.raloy.com.mx/firmar/{proceso.token_acceso}/{primer_firmante.get('token_firmante', '')}/"
            requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                          json={"email": primer_firmante['email'], "nombre": primer_firmante['nombre'],
                                "link": link_firma,
                                "mensaje": f"Raloy solicita tu firma electrónica para el documento {ref_id}."})

            if owner_email:
                link_trazabilidad = f"https://dsign.raloy.com.mx/trazabilidad/{proceso.token_acceso}/"
                requests.post(N8N_WEBHOOK_NOTIFICAR_OWNER,
                              json={"email": owner_email, "reference_id": ref_id, "link": link_trazabilidad})

            return JsonResponse({"status": "success", "msg": "Documento recibido.", "folio_asignado": ref_id})
        except Exception as e:
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=400)


def vista_firma_ui(request, token, firmante_token=None):
    proceso = get_object_or_404(ProcesoFirma, token_acceso=token)
    message_context = {'token': token, 'view_info': proceso.view_info, 'summary_data': proceso.summary_data,
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

    if firmante_token:
        firmante_actual = next((f for f in proceso.firmantes if f.get('token_firmante') == firmante_token), None)
        if not firmante_actual: return HttpResponse("<h1>Enlace inválido.</h1>")
        if firmante_actual.get('fecha_firma'):
            message_context.update({'message_icon': '✓', 'message_color': '#10b981', 'message_title': 'Ya has firmado',
                                    'message_body': 'Tu firma ya ha sido capturada.'})
            return render(request, 'motor_firmas/firma_ui.html', message_context)

        firmante_esperado = proceso.firmantes[proceso.indice_actual - 1]
        if firmante_actual.get('token_firmante') != firmante_esperado.get('token_firmante'):
            message_context.update(
                {'message_icon': '⏳', 'message_color': '#f39c12', 'message_title': 'Aún no es tu turno',
                 'message_body': 'Te notificaremos cuando sea tu turno.'})
            return render(request, 'motor_firmas/firma_ui.html', message_context)
    else:
        firmante_actual = proceso.firmantes[proceso.indice_actual - 1]

    colaborador = DirectorioFirmas.objects.filter(email=firmante_actual.get('email')).first()
    
    content_option = {}
    labels_map = {}
    
    # Extraer opciones directo de la Plantilla original cruzando con dir_drive
    if proceso.exec_mode == 'form' and proceso.dir_drive:
        plantillas = PlantillaFormulario.objects.filter(drive_folder_id=proceso.dir_drive)
        if not plantillas.exists():
            plantillas = PlantillaFormulario.objects.filter(carpeta_firmados_id=proceso.dir_drive)
            
        plantilla_encontrada = None
        for p in plantillas:
            prefix = p.formato_folio.split('-0')[0] if p.formato_folio else ''
            if prefix and proceso.reference_id.startswith(prefix):
                plantilla_encontrada = p
                break
        if not plantilla_encontrada and plantillas.exists():
            plantilla_encontrada = plantillas.first()
            
        if plantilla_encontrada and plantilla_encontrada.variables:
            import json
            vars_list = plantilla_encontrada.variables
            
            # Djongo might stringify or double-stringify the list
            while isinstance(vars_list, str):
                try:
                    parsed = json.loads(vars_list)
                    if parsed == vars_list: # Prevent infinite loop if string is not valid JSON array
                        break
                    vars_list = parsed
                except:
                    break
                    
            if not isinstance(vars_list, list):
                vars_list = []
                    
            for v in vars_list:
                if isinstance(v, dict):
                    labels_map[v.get('key')] = v.get('label', v.get('key'))
                    if v.get('type') in ('option', 'seleccionable'):
                        if 'content-option' in v:
                            content_option[v['key']] = v['content-option']
                        elif 'content_options' in v:
                            content_option[v['key']] = v['content_options']
                    
    # Fallback por si N8N lo mandó de otra forma en summary_data (Legacy)
    if not content_option and proceso.summary_data:
        co_raw = proceso.summary_data.get('content-option', proceso.summary_data.get('content_option', {}))
        if isinstance(co_raw, dict):
            content_option = co_raw
        elif isinstance(co_raw, list):
            for item in co_raw:
                if isinstance(item, dict):
                    content_option.update(item)

    campos_a_llenar = []
    if proceso.exec_mode == 'form':
        import json
        doc_vars = proceso.document_variables
        while isinstance(doc_vars, str):
            try:
                parsed = json.loads(doc_vars)
                if parsed == doc_vars: break
                doc_vars = parsed
            except:
                break
        if not isinstance(doc_vars, dict):
            doc_vars = {}
            
        for key, em in doc_vars.items():
            if em == firmante_actual['email'] and key not in proceso.valores_capturados:
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

    context = {'token': token, 'firmante_token': firmante_token or '',
               'nombre_firmante': firmante_actual.get('nombre', 'Firmante'),
               'email_firmante': firmante_actual.get('email', ''), 'view_info': proceso.view_info,
               'summary_data': proceso.summary_data,
               'pdf_url': f"{settings.MEDIA_URL}{os.path.basename(proceso.pdf_path)}",
               'is_registered': bool(colaborador), 'campos_a_llenar': campos_a_llenar, 'is_message_view': False}
    return render(request, 'motor_firmas/firma_ui.html', context)


@csrf_exempt
def procesar_firma(request, token, firmante_token=None):
    if request.method == 'POST':
        data = json.loads(request.body)
        ip_user = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))
        proceso = get_object_or_404(ProcesoFirma, token_acceso=token)
        if proceso.status == 'CANCELLED': return JsonResponse({"error": "Documento cancelado."}, status=403)

        firmante_esperado = proceso.firmantes[proceso.indice_actual - 1]
        if firmante_token and firmante_token != firmante_esperado.get('token_firmante'): return JsonResponse(
            {"error": "No es tu turno."}, status=403)

        try:
            pin_ingresado = data.get('pin')
            if pin_ingresado:
                colaborador = DirectorioFirmas.objects.filter(email=firmante_esperado['email']).first()
                if not colaborador or not colaborador.check_pin(pin_ingresado): return JsonResponse(
                    {"error": "PIN incorrecto."}, status=403)
                firma_b64 = colaborador.firma_base64
            else:
                firma_b64 = data.get('firma_base64')
                if not firma_b64: return JsonResponse({"error": "Firma o PIN requerido."}, status=400)

            if data.get('variables'):
                proceso.valores_capturados.update(data.get('variables'))
                estampar_variables_en_pdf(proceso.pdf_path, data.get('variables'))
                proceso.save()

            coordenadas = firmante_esperado.get('coordenadas')
            estampar_firma_en_pdf(proceso.pdf_path, firma_b64, proceso.indice_actual, firmante_esperado['email'],
                                  firmante_esperado['nombre'], ip_user, coordenadas)

            firmantes_lista = list(proceso.firmantes)
            firmantes_lista[proceso.indice_actual - 1]['fecha_firma'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
            proceso.firmantes = firmantes_lista

            if proceso.indice_actual < len(proceso.firmantes):
                proceso.indice_actual += 1
                proceso.save()
                siguiente = proceso.firmantes[proceso.indice_actual - 1]
                link_firma = f"https://dsign.raloy.com.mx/firmar/{proceso.token_acceso}/{siguiente.get('token_firmante', '')}/"
                requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                              json={"email": siguiente['email'], "nombre": siguiente['nombre'], "link": link_firma,
                                    "mensaje": "Es tu turno de firmar."})
                return JsonResponse({"status": "success", "msg": "Firma guardada."})
            else:
                proceso.status = 'COMPLETED'
                proceso.save()
                correos = ",".join([f['email'] for f in proceso.firmantes]) + (
                    f",{proceso.owner_email}" if proceso.owner_email else "")
                with open(proceso.pdf_path, 'rb') as f:
                    requests.post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                                  data={"reference_id": proceso.reference_id, "status": "COMPLETED",
                                        "correos_destino": correos, "folder_id": proceso.dir_drive}, files={
                            "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")})
                return JsonResponse({"status": "success"})
        except Exception as e:
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=500)


def vista_trazabilidad(request, token):
    proceso = get_object_or_404(ProcesoFirma, token_acceso=token)
    return render(request, 'motor_firmas/trazabilidad.html',
                  {'proceso': proceso, 'pdf_url': f"{settings.MEDIA_URL}{os.path.basename(proceso.pdf_path)}"})


@csrf_exempt
def registro_firmas(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        if DirectorioFirmas.objects.filter(email=email).exists(): return render(request,
                                                                                'motor_firmas/registro_firmas.html',
                                                                                {"error": "Correo registrado."})
        colaborador = DirectorioFirmas(nombre=request.POST.get('nombre'), email=email,
                                       puesto=request.POST.get('puesto'), iniciales=request.POST.get('iniciales'),
                                       firma_base64=request.POST.get('firma_base64'), acepto_terminos=True)
        colaborador.set_pin(request.POST.get('pin'))
        colaborador.save()
        return HttpResponse("<h1 style='text-align:center; margin-top:50px;'>Registro exitoso.</h1>")
    return render(request, 'motor_firmas/registro_firmas.html')


@csrf_exempt
def solicitar_recuperacion(request):
    if request.method == 'POST':
        colaborador = DirectorioFirmas.objects.filter(email=json.loads(request.body).get('email')).first()
        if colaborador:
            colaborador.generar_token_recuperacion()
            requests.post(N8N_WEBHOOK_RECUPERAR_PIN, json={"email": colaborador.email, "nombre": colaborador.nombre,
                                                           "link": f"https://dsign.raloy.com.mx/recuperar-pin/{colaborador.reset_token}/"})
        return JsonResponse({"status": "success"})


@csrf_exempt
def resetear_pin(request, token):
    colaborador = get_object_or_404(DirectorioFirmas, reset_token=token)
    if colaborador.reset_token_expires < timezone.now(): return HttpResponse("<h1>Enlace expirado.</h1>")
    if request.method == 'POST':
        colaborador.set_pin(request.POST.get('nuevo_pin'))
        colaborador.reset_token = None
        colaborador.save()
        return HttpResponse("<h1 style='text-align:center; margin-top:50px;'>PIN actualizado.</h1>")
    return render(request, 'motor_firmas/resetear_pin.html', {'token': token})


@csrf_exempt
def portal_login(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        email, pin_ingresado = data.get('email'), data.get('pin')
        colaborador = DirectorioFirmas.objects.filter(email=email).first()
        otp_record = OTPLogin.objects.filter(email=email).first()
        if (colaborador and colaborador.check_pin(pin_ingresado)) or (
                otp_record and otp_record.es_valido(pin_ingresado)):
            if otp_record:
                # SOLUCIÓN DE MONGODB APLICADA AQUÍ: Borrado por QuerySet
                OTPLogin.objects.filter(email=email).delete()
            request.session['owner_email'] = email
            return JsonResponse({"status": "success"})
        return JsonResponse({"error": "PIN incorrecto."}, status=403)
    if request.session.get('owner_email'): return redirect('portal_dashboard')
    return render(request, 'motor_firmas/portal_login.html')


@csrf_exempt
def solicitar_otp(request):
    if request.method == 'POST':
        email = json.loads(request.body).get('email')
        if not email: return JsonResponse({"error": "Correo requerido"}, status=400)
        otp_record, _ = OTPLogin.objects.get_or_create(email=email,
                                                       defaults={'otp_code': '000', 'expires_at': timezone.now()})
        otp_record.generar_otp()
        requests.post(N8N_WEBHOOK_ENVIAR_OTP, json={"email": email, "otp": otp_record.otp_code})
        return JsonResponse({"status": "success", "msg": "PIN temporal enviado."})


def portal_dashboard(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    documentos = ProcesoFirma.objects.filter(owner_email=owner_email).order_by('-created_at')
    lista_docs = []
    for doc in documentos:
        tot = len(doc.firmantes)
        hechas = sum(1 for f in doc.firmantes if f.get('fecha_firma'))
        lista_docs.append({'proceso': doc, 'total_firmas': tot, 'firmas_hechas': hechas,
                           'porcentaje': int((hechas / tot) * 100) if tot > 0 else 0})

    dominio = owner_email.split('@')[1] if '@' in owner_email else ''
    tiene_carpeta_dominio = CarpetaDominio.objects.filter(dominio=dominio).exists()

    colaborador = DirectorioFirmas.objects.filter(email=owner_email).first()
    permisos = colaborador.permisos_portal if colaborador and colaborador.permisos_portal else []
    import json
    while isinstance(permisos, str):
        try:
            parsed = json.loads(permisos)
            if parsed == permisos: break
            permisos = parsed
        except:
            break
    if not isinstance(permisos, list): permisos = []

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
    todas = PlantillaFormulario.objects.all().order_by('-created_at')
    permitidas = [p for p in todas if owner_email in p.usuarios_permitidos or p.owner_email == owner_email]
    return render(request, 'motor_firmas/portal_plantillas.html',
                  {'plantillas': permitidas, 'owner_email': owner_email})


def portal_usar_plantilla(request, plantilla_id):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    plantilla = get_object_or_404(PlantillaFormulario, id=plantilla_id)
    return render(request, 'motor_firmas/portal_usar_plantilla.html',
                  {'plantilla': plantilla, 'owner_email': owner_email})


# ================= VISTAS DE PDFS LIBRES (DRAG & DROP) =================
def portal_pdfs_usuario(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    pdfs = DocumentoPDFUsuario.objects.filter(owner_email=owner_email).order_by('-created_at')
    return render(request, 'motor_firmas/portal_pdfs_usuario.html', {'pdfs': pdfs, 'owner_email': owner_email})


@csrf_exempt
def eliminar_pdf_usuario(request, pdf_id):
    owner_email = request.session.get('owner_email')
    if not owner_email: return JsonResponse({"error": "No autorizado"}, status=403)

    qs = DocumentoPDFUsuario.objects.none()

    try:
        uid = uuid.UUID(pdf_id)
        qs = DocumentoPDFUsuario.objects.filter(id_documento=uid, owner_email=owner_email)
    except ValueError:
        pass

    if not qs.exists():
        try:
            qs = DocumentoPDFUsuario.objects.filter(id=pdf_id, owner_email=owner_email)
        except Exception:
            pass

    if qs.exists():
        doc = qs.first()
        if doc.archivo_local:
            full_path = os.path.join(settings.MEDIA_ROOT, doc.archivo_local)
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                except:
                    pass

        # SOLUCIÓN DE MONGODB APLICADA AQUÍ: Borrado por QuerySet en lugar de Instancia
        qs.delete()
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
    if request.method == 'POST':
        pdf_file = request.FILES.get('pdf_file')
        if not pdf_file: return JsonResponse({"error": "No se seleccionó ningún archivo PDF."}, status=400)

        dominio = owner_email.split('@')[1] if '@' in owner_email else ''
        carpeta_dom = CarpetaDominio.objects.filter(dominio=dominio).first()
        if not carpeta_dom: return JsonResponse(
            {"error": f"Tu dominio (@{dominio}) no tiene asignada una carpeta en Google Drive."}, status=400)

        try:
            files = {'data': (pdf_file.name, pdf_file.read(), 'application/pdf')}
            pdf_file.seek(0)
            resp = requests.post(N8N_WEBHOOK_SUBIR_PDF_USUARIO, data={'folder_id': carpeta_dom.drive_folder_id},
                                 files=files, timeout=30).json()

            if resp.get('status') == 'success':
                safe_filename = f"{uuid.uuid4()}_{pdf_file.name}"
                os.makedirs(os.path.join(settings.MEDIA_ROOT, 'pdfs_libres'), exist_ok=True)
                local_path = os.path.join('pdfs_libres', safe_filename)
                with open(os.path.join(settings.MEDIA_ROOT, local_path), 'wb+') as f:
                    for chunk in pdf_file.chunks(): f.write(chunk)

                nuevo_doc = DocumentoPDFUsuario.objects.create(
                    nombre=pdf_file.name, drive_file_id=resp.get('file_id'), owner_email=owner_email,
                    archivo_local=local_path
                )
                return JsonResponse({"status": "success", "nombre": pdf_file.name, "id": str(nuevo_doc.id_documento)})
            else:
                return JsonResponse({"error": "N8n falló al subir a Drive."})
        except Exception as e:
            return JsonResponse({"error": f"Error: {e}"})


def portal_configurar_pdf(request, pdf_id):
    owner_email = request.session.get('owner_email')
    if not owner_email: return redirect('portal_login')
    doc = get_object_or_404(DocumentoPDFUsuario, id_documento=pdf_id, owner_email=owner_email)
    pdf_url = f"{settings.MEDIA_URL}{doc.archivo_local}"
    return render(request, 'motor_firmas/portal_configurar_pdf.html',
                  {'doc': doc, 'pdf_url': pdf_url, 'owner_email': owner_email})


@csrf_exempt
def iniciar_firma_libre(request):
    owner_email = request.session.get('owner_email')
    if not owner_email: return JsonResponse({"error": "No autorizado"}, status=403)
    if request.method == 'POST':
        data = json.loads(request.body)
        doc = get_object_or_404(DocumentoPDFUsuario, id_documento=data['pdf_id'], owner_email=owner_email)

        firmantes = data.get('firmantes', [])
        for f in firmantes: f['token_firmante'] = str(uuid.uuid4())

        original_path = os.path.join(settings.MEDIA_ROOT, doc.archivo_local)

        ref_id = f"LIBRE-{int(timezone.now().timestamp())}"
        final_path = os.path.join(settings.MEDIA_ROOT, f"{ref_id}.pdf")
        shutil.copyfile(original_path, final_path)

        dominio = owner_email.split('@')[1] if '@' in owner_email else ''
        carpeta_dom = CarpetaDominio.objects.filter(dominio=dominio).first()

        proceso = ProcesoFirma.objects.create(
            reference_id=ref_id, pdf_path=final_path, firmantes=firmantes, indice_actual=1,
            view_info="file", owner_email=owner_email, dir_drive=carpeta_dom.drive_folder_id if carpeta_dom else '',
            exec_mode="libre"
        )

        primer_firmante = firmantes[0]
        link_firma = f"https://dsign.raloy.com.mx/firmar/{proceso.token_acceso}/{primer_firmante.get('token_firmante', '')}/"
        requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                      json={"email": primer_firmante['email'], "nombre": primer_firmante['nombre'], "link": link_firma,
                            "mensaje": f"Raloy solicita tu firma para el documento libre {ref_id}."})

        link_trazabilidad = f"https://dsign.raloy.com.mx/trazabilidad/{proceso.token_acceso}/"
        requests.post(N8N_WEBHOOK_NOTIFICAR_OWNER,
                      json={"email": owner_email, "reference_id": ref_id, "link": link_trazabilidad})

        # SOLUCIÓN DE MONGODB APLICADA AQUÍ: Borrado por QuerySet
        if os.path.exists(original_path):
            os.remove(original_path)
        DocumentoPDFUsuario.objects.filter(id_documento=doc.id_documento).delete()

        return JsonResponse({"status": "success"})


# ================= VISTAS DE ADMINISTRADOR =================
@csrf_exempt
def admin_login(request):
    if not AdministradorPortal.objects.exists(): AdministradorPortal.objects.create(email="pjimenezb@raloy.com.mx", es_superadmin=True)
    else:
        # Asegurar que pjimenezb sea superadmin siempre
        pj = AdministradorPortal.objects.filter(email="pjimenezb@raloy.com.mx").first()
        if pj and not pj.es_superadmin:
            pj.es_superadmin = True
            pj.save()
            
    if request.method == 'POST':
        data = json.loads(request.body)
        email, pin_ingresado = data.get('email'), data.get('pin')
        if not AdministradorPortal.objects.filter(email=email).exists(): return JsonResponse(
            {"error": "No eres admin."}, status=403)
        colaborador = DirectorioFirmas.objects.filter(email=email).first()
        otp_record = OTPLogin.objects.filter(email=email).first()
        if (colaborador and colaborador.check_pin(pin_ingresado)) or (
                otp_record and otp_record.es_valido(pin_ingresado)):
            if otp_record:
                # SOLUCIÓN DE MONGODB APLICADA AQUÍ: Borrado por QuerySet
                OTPLogin.objects.filter(email=email).delete()
            request.session['admin_email'] = email
            return JsonResponse({"status": "success"})
        return JsonResponse({"error": "PIN incorrecto."}, status=403)
    if request.session.get('admin_email'): return redirect('admin_dashboard')
    return render(request, 'motor_firmas/admin_login.html')


def admin_dashboard(request):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    admin_obj = AdministradorPortal.objects.get(email=admin_email)
    
    if admin_obj.es_superadmin or admin_email == 'pjimenezb@raloy.com.mx':
        todos_docs = ProcesoFirma.objects.all().order_by('-created_at')
    else:
        from django.db.models import Q
        emails_asignados = list(DirectorioFirmas.objects.filter(tecnico_asignado=admin_email).values_list('email', flat=True))
        todos_docs = ProcesoFirma.objects.filter(Q(owner_email=admin_email) | Q(owner_email__in=emails_asignados)).order_by('-created_at')
    docs_json = [{'reference_id': d.reference_id, 'token': str(d.token_acceso), 'owner_email': d.owner_email or 'N/A',
                  'dominio': d.owner_email.split('@')[1] if d.owner_email and '@' in d.owner_email else 'N/A',
                  'status': d.status, 'fecha': d.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                  'progreso': f"{sum(1 for f in d.firmantes if f.get('fecha_firma'))}/{len(d.firmantes)}"} for d in
                 todos_docs]
    if admin_obj.es_superadmin or admin_email == 'pjimenezb@raloy.com.mx':
        plantillas = PlantillaFormulario.objects.all().order_by('-created_at')
    else:
        plantillas = PlantillaFormulario.objects.filter(Q(owner_email=admin_email) | Q(owner_email__in=emails_asignados)).order_by('-created_at')
    carpetas_dominio = list(CarpetaDominio.objects.values('id', 'dominio', 'drive_folder_id'))
    return render(request, 'motor_firmas/admin_dashboard.html',
                  {'admin_email': admin_email, 'docs_json': json.dumps(docs_json),
                   'saved_config': json.dumps(admin_obj.configuracion_dashboard), 'plantillas': plantillas,
                   'carpetas_dominio': json.dumps(carpetas_dominio), 'es_superadmin': admin_obj.es_superadmin})


def admin_logout(request):
    request.session.flush()
    return redirect('admin_login')


def admin_crear_plantilla(request):
    if not request.session.get('admin_email'): return redirect('admin_login')
    return render(request, 'motor_firmas/admin_crear_plantilla.html',
                  {'admin_email': request.session.get('admin_email')})


def admin_editar_plantilla(request, plantilla_id):
    if not request.session.get('admin_email'): return redirect('admin_login')
    plantilla = get_object_or_404(PlantillaFormulario, id=plantilla_id)
    return render(request, 'motor_firmas/admin_editar_plantilla.html',
                  {'admin_email': request.session.get('admin_email'), 'plantilla': plantilla})


@csrf_exempt
def admin_api(request, accion):
    if not request.session.get('admin_email'): return JsonResponse({"error": "No autorizado"}, status=403)
    admin_actual = AdministradorPortal.objects.filter(email=request.session.get('admin_email')).first()
    
    if request.method == 'POST':
        data = json.loads(request.body)
        
        if accion == 'actualizar_usuario':
            u_id = data.get('id')
            usr = DirectorioFirmas.objects.filter(id=u_id).first()
            if usr:
                if not admin_actual.es_superadmin and admin_actual.email != 'pjimenezb@raloy.com.mx' and usr.tecnico_asignado != admin_actual.email:
                    return JsonResponse({"error": "No tienes permiso."}, status=403)
                if (admin_actual.es_superadmin or admin_actual.email == 'pjimenezb@raloy.com.mx') and 'tecnico_asignado' in data:
                    usr.tecnico_asignado = data.get('tecnico_asignado')
                usr.permisos_portal = data.get('permisos', [])
                usr.save()
                return JsonResponse({"status": "success", "msg": "Usuario actualizado."})
            return JsonResponse({"error": "Usuario no encontrado."}, status=404)
            
        elif accion == 'eliminar_usuario':
            u_id = data.get('id')
            usr = DirectorioFirmas.objects.filter(id=u_id).first()
            if usr:
                if not admin_actual.es_superadmin and usr.tecnico_asignado != admin_actual.email:
                    return JsonResponse({"error": "No tienes permiso."}, status=403)
                usr.delete()
                return JsonResponse({"status": "success", "msg": "Usuario eliminado."})
            return JsonResponse({"error": "Usuario no encontrado."}, status=404)
            
        elif accion == 'actualizar_admin':
            if not admin_actual.es_superadmin: return JsonResponse({"error": "Solo superadmin."}, status=403)
            a_id = data.get('id')
            a_obj = AdministradorPortal.objects.filter(id=a_id).first()
            if a_obj:
                a_obj.es_superadmin = data.get('es_superadmin', False)
                a_obj.save()
                return JsonResponse({"status": "success"})
            return JsonResponse({"error": "No encontrado."}, status=404)
            
        elif accion == 'eliminar_admin':
            if not admin_actual.es_superadmin: return JsonResponse({"error": "Solo superadmin."}, status=403)
            a_id = data.get('id')
            a_obj = AdministradorPortal.objects.filter(id=a_id).first()
            if a_obj:
                if a_obj.email == "pjimenezb@raloy.com.mx": return JsonResponse({"error": "No puedes eliminar al admin maestro."})
                a_obj.delete()
                return JsonResponse({"status": "success"})
            return JsonResponse({"error": "No encontrado."}, status=404)


        if accion == 'agregar_admin':
            if AdministradorPortal.objects.filter(email=data.get('email')).exists(): return JsonResponse(
                {"error": "Ya es admin."})
            AdministradorPortal.objects.create(email=data.get('email'))
            return JsonResponse({"status": "success", "msg": "Admin agregado."})
        elif accion == 'cancelar_doc':
            doc = ProcesoFirma.objects.filter(token_acceso=data.get('token')).first()
            if doc:
                doc.status = 'CANCELLED'
                doc.save()
                return JsonResponse({"status": "success"})
            return JsonResponse({"error": "No encontrado."}, status=404)
        elif accion == 'invitar_registro':
            requests.post(N8N_WEBHOOK_INVITAR_REGISTRO,
                          json={"email": data.get('email'), "link": "https://dsign.raloy.com.mx/registro-firmas/"})
            return JsonResponse({"status": "success", "msg": "Invitación enviada."})
        elif accion == 'guardar_config':
            admin_obj = AdministradorPortal.objects.get(email=request.session.get('admin_email'))
            admin_obj.configuracion_dashboard = data.get('configuracion')
            admin_obj.save()
            return JsonResponse({"status": "success"})
        elif accion == 'analizar_plantilla':
            resp = requests.post(N8N_WEBHOOK_ANALIZAR_PLANTILLA, json=data).json()
            return JsonResponse({"status": "success", "data": resp})
        elif accion == 'guardar_plantilla':
            carpeta_firmados = data['drive_folder_id']
            try:
                resp_dir = requests.post(N8N_WEBHOOK_PREPARAR_DIR,
                                         json={"doc_id": data['doc_id'], "parent_folder": data['drive_folder_id']},
                                         timeout=20).json()
                if resp_dir.get('status') == 'success': carpeta_firmados = resp_dir.get('firmados_folder_id',
                                                                                        data['drive_folder_id'])
            except Exception as e:
                pass
            PlantillaFormulario.objects.create(
                nombre=data['nombre'], doc_id=data['doc_id'], owner_email=data['owner_email'],
                drive_folder_id=data['drive_folder_id'],
                carpeta_firmados_id=carpeta_firmados, view_info=data['view_info'],
                formato_folio=data.get('formato_folio', ''),
                contexto=data.get('contexto', ''), intencion=data.get('intencion', ''), variables=data.get('variables', []),
                firmantes_config=data.get('firmantes_config', []), usuarios_permitidos=data.get('usuarios_permitidos', [])
            )
            return JsonResponse({"status": "success", "msg": "Plantilla preparada exitosamente."})
        elif accion == 'actualizar_plantilla':
            p = PlantillaFormulario.objects.filter(id=data.get('id')).first()
            if p:
                p.nombre = data.get('nombre')
                p.formato_folio = data.get('formato_folio', '')
                p.drive_folder_id = data.get('drive_folder_id')
                p.view_info = data.get('view_info')
                p.usuarios_permitidos = data.get('usuarios_permitidos')
                p.variables = data.get('variables')
                p.firmantes_config = data.get('firmantes_config')
                p.save()
                return JsonResponse({"status": "success", "msg": "Plantilla actualizada."})
            return JsonResponse({"error": "Plantilla no encontrada"}, status=404)
        elif accion == 'eliminar_plantilla':
            # SOLUCIÓN DE MONGODB APLICADA AQUÍ: Borrado por QuerySet
            PlantillaFormulario.objects.filter(id=data.get('id')).delete()
            return JsonResponse({"status": "success", "msg": "Plantilla eliminada."})
        elif accion == 'guardar_carpeta_dominio':
            dominio, folder_id = data.get('dominio', '').strip().lower(), data.get('drive_folder_id', '').strip()
            if not dominio or not folder_id: return JsonResponse({"error": "Faltan campos"}, status=400)
            CarpetaDominio.objects.update_or_create(dominio=dominio, defaults={'drive_folder_id': str(folder_id)})
            return JsonResponse({"status": "success", "msg": "Carpeta asignada."})
        elif accion == 'eliminar_carpeta_dominio':
            # SOLUCIÓN DE MONGODB APLICADA AQUÍ: Borrado por QuerySet
            CarpetaDominio.objects.filter(id=data.get('id')).delete()
            return JsonResponse({"status": "success", "msg": "Configuración eliminada."})
    return JsonResponse({"error": "Acción inválida"}, status=400)
# ================= NUEVAS VISTAS ADMIN =================

def admin_usuarios(request):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    
    admin_obj = get_object_or_404(AdministradorPortal, email=admin_email)
    
    if admin_obj.es_superadmin or admin_email == 'pjimenezb@raloy.com.mx':
        usuarios = DirectorioFirmas.objects.all().order_by('-fecha_registro')
    else:
        usuarios = DirectorioFirmas.objects.filter(tecnico_asignado=admin_email).order_by('-fecha_registro')
        
    lista_usrs = []
    for u in usuarios:
        docs = ProcesoFirma.objects.filter(owner_email=u.email)
        tot_docs = docs.count()
        # Calculate effectiveness simply as percentage of documents signed or created
        lista_usrs.append({
            'id': u.id,
            'nombre': u.nombre,
            'email': u.email,
            'tecnico': u.tecnico_asignado or 'Sin asignar',
            'ultima_act': u.ultima_actividad.strftime("%d/%m/%Y %H:%M") if u.ultima_actividad else 'Nunca',
            'tot_docs': tot_docs
        })
        
    return render(request, 'motor_firmas/admin_usuarios.html', {
        'admin_email': admin_email,
        'es_superadmin': admin_obj.es_superadmin or admin_email == 'pjimenezb@raloy.com.mx',
        'usuarios': lista_usrs
    })

def admin_usuarios_detalle(request, usuario_id):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    
    admin_obj = get_object_or_404(AdministradorPortal, email=admin_email)
    usuario = get_object_or_404(DirectorioFirmas, id=usuario_id)
    
    if not admin_obj.es_superadmin and admin_email != 'pjimenezb@raloy.com.mx' and usuario.tecnico_asignado != admin_email:
        return HttpResponse("<h1>No tienes permisos para ver a este usuario.</h1>", status=403)
        
    tecnicos = AdministradorPortal.objects.all()
    
    permisos = usuario.permisos_portal
    import json
    if isinstance(permisos, str):
        try: permisos = json.loads(permisos)
        except: permisos = []
    if not isinstance(permisos, list): permisos = []

    return render(request, 'motor_firmas/admin_usuarios_detalle.html', {
        'admin_email': admin_email,
        'es_superadmin': admin_obj.es_superadmin or admin_email == 'pjimenezb@raloy.com.mx',
        'usuario': usuario,
        'tecnicos': tecnicos,
        'permisos': permisos
    })

def admin_administradores(request):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    
    admin_obj = get_object_or_404(AdministradorPortal, email=admin_email)
    if not admin_obj.es_superadmin:
        return HttpResponse("<h1>Acceso denegado. Solo superadministradores.</h1>", status=403)
        
    admins = AdministradorPortal.objects.all().order_by('email')
    return render(request, 'motor_firmas/admin_administradores.html', {
        'admin_email': admin_email,
        'admins': admins
    })


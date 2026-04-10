import os
import json
import requests
import traceback
import re
from datetime import datetime
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import ProcesoFirma, DirectorioFirmas, OTPLogin, AdministradorPortal, PlantillaFormulario
from .utils import estampar_firma_en_pdf, estampar_variables_en_pdf

# WEBHOOKS DE N8N
N8N_WEBHOOK_NOTIFICAR_CORREO = "https://n8n.raloy.com.mx/webhook/enviar-correo-firma"
N8N_WEBHOOK_FINALIZAR_PROCESO = "https://n8n.raloy.com.mx/webhook/subir-pdf-final"
N8N_WEBHOOK_NOTIFICAR_OWNER = "https://n8n.raloy.com.mx/webhook/notificar-owner"
N8N_WEBHOOK_RECUPERAR_PIN = "https://n8n.raloy.com.mx/webhook/recuperar-pin-firma"
N8N_WEBHOOK_ENVIAR_OTP = "https://n8n.raloy.com.mx/webhook/enviar-otp-portal"
N8N_WEBHOOK_INVITAR_REGISTRO = "https://n8n.raloy.com.mx/webhook/invitar-registro-firma"
N8N_WEBHOOK_ANALIZAR_PLANTILLA = "https://n8n.raloy.com.mx/webhook/analizar-plantilla"


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
            document_variables = data.get('document_variables', {})

            original_ref_id = ref_id
            match = re.search(r'^(.*?-)(\d+)$', ref_id)

            if match:
                base_name = match.group(1)
                num_str = match.group(2)
                num_len = len(num_str)
                current_num = int(num_str)
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
                for chunk in pdf_file.chunks():
                    destination.write(chunk)

            proceso = ProcesoFirma.objects.create(
                reference_id=ref_id,
                pdf_path=file_path,
                firmantes=firmantes,
                indice_actual=1,
                view_info=view_info,
                summary_data=summary_data,
                owner_email=owner_email,
                dir_drive=dir_drive,
                exec_mode=exec_mode,
                document_variables=document_variables,
                valores_capturados={}
            )

            primer_firmante = firmantes[0]
            link_firma = f"https://testapppjb0001.raloy.com.mx/firmar/{proceso.token_acceso}/"
            requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                          json={"email": primer_firmante['email'], "nombre": primer_firmante['nombre'],
                                "link": link_firma,
                                "mensaje": f"Raloy solicita tu firma electrónica para el documento {ref_id}."})

            if owner_email:
                link_trazabilidad = f"https://testapppjb0001.raloy.com.mx/trazabilidad/{proceso.token_acceso}/"
                requests.post(N8N_WEBHOOK_NOTIFICAR_OWNER,
                              json={"email": owner_email, "reference_id": ref_id, "link": link_trazabilidad})

            return JsonResponse({"status": "success", "msg": "Documento recibido.", "folio_asignado": ref_id})
        except Exception as e:
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=400)


def vista_firma_ui(request, token):
    proceso = get_object_or_404(ProcesoFirma, token_acceso=token)
    if proceso.status == 'CANCELLED': return HttpResponse(
        "<h1 style='color:red; text-align:center; margin-top:50px;'>Este documento ha sido CANCELADO.</h1>")
    if proceso.status == 'COMPLETED': return HttpResponse(
        "<h1 style='text-align:center; margin-top:50px;'>Este documento ya ha sido firmado en su totalidad.</h1>")

    firmante_actual = proceso.firmantes[proceso.indice_actual - 1]
    filename = os.path.basename(proceso.pdf_path)
    colaborador = DirectorioFirmas.objects.filter(email=firmante_actual.get('email')).first()

    campos_a_llenar = []
    if proceso.exec_mode == 'form':
        for key, email_asignado in proceso.document_variables.items():
            if email_asignado == firmante_actual['email'] and key not in proceso.valores_capturados:
                campos_a_llenar.append(key)

    context = {
        'token': token,
        'nombre_firmante': firmante_actual.get('nombre', 'Firmante'),
        'email_firmante': firmante_actual.get('email', ''),
        'view_info': proceso.view_info,
        'summary_data': proceso.summary_data,
        'pdf_url': f"{settings.MEDIA_URL}{filename}",
        'is_registered': bool(colaborador),
        'campos_a_llenar': campos_a_llenar
    }
    return render(request, 'motor_firmas/firma_ui.html', context)


@csrf_exempt
def procesar_firma(request, token):
    if request.method == 'POST':
        data = json.loads(request.body)
        ip_user = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))
        proceso = get_object_or_404(ProcesoFirma, token_acceso=token)
        if proceso.status == 'CANCELLED': return JsonResponse({"error": "Documento cancelado."}, status=403)

        firmante_actual = proceso.firmantes[proceso.indice_actual - 1]

        try:
            pin_ingresado = data.get('pin')
            if pin_ingresado:
                colaborador = DirectorioFirmas.objects.filter(email=firmante_actual['email']).first()
                if not colaborador or not colaborador.check_pin(pin_ingresado):
                    return JsonResponse({"error": "El PIN ingresado es incorrecto."}, status=403)
                firma_b64 = colaborador.firma_base64
            else:
                firma_b64 = data.get('firma_base64')
                if not firma_b64: return JsonResponse({"error": "Firma o PIN requerido."}, status=400)

            variables_recibidas = data.get('variables', {})
            if variables_recibidas:
                proceso.valores_capturados.update(variables_recibidas)
                estampar_variables_en_pdf(proceso.pdf_path, variables_recibidas)
                proceso.save()

            estampar_firma_en_pdf(proceso.pdf_path, firma_b64, proceso.indice_actual, firmante_actual['email'],
                                  firmante_actual['nombre'], ip_user)
            proceso.firmantes[proceso.indice_actual - 1]['fecha_firma'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S")

            if proceso.indice_actual < len(proceso.firmantes):
                proceso.indice_actual += 1
                proceso.save()
                siguiente_firmante = proceso.firmantes[proceso.indice_actual - 1]
                link_firma = f"https://testapppjb0001.raloy.com.mx/firmar/{proceso.token_acceso}/"
                requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                              json={"email": siguiente_firmante['email'], "nombre": siguiente_firmante['nombre'],
                                    "link": link_firma, "mensaje": "Es tu turno de firmar el documento."})
                return JsonResponse({"status": "success", "msg": "Firma guardada."})
            else:
                proceso.status = 'COMPLETED'
                proceso.save()
                correos_destino = ",".join([f['email'] for f in proceso.firmantes])
                if proceso.owner_email: correos_destino += f",{proceso.owner_email}"
                with open(proceso.pdf_path, 'rb') as f:
                    requests.post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                                  data={"reference_id": proceso.reference_id, "status": "COMPLETED",
                                        "correos_destino": correos_destino}, files={
                            "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")})
                return JsonResponse({"status": "success", "msg": "Documento finalizado."})
        except Exception as e:
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=500)


def vista_trazabilidad(request, token):
    proceso = get_object_or_404(ProcesoFirma, token_acceso=token)
    filename = os.path.basename(proceso.pdf_path)
    return render(request, 'motor_firmas/trazabilidad.html',
                  {'proceso': proceso, 'pdf_url': f"{settings.MEDIA_URL}{filename}"})


@csrf_exempt
def registro_firmas(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        if DirectorioFirmas.objects.filter(email=email).exists(): return render(request,
                                                                                'motor_firmas/registro_firmas.html', {
                                                                                    "error": "Este correo ya está registrado."})
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
                                                           "link": f"https://testapppjb0001.raloy.com.mx/recuperar-pin/{colaborador.reset_token}/"})
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


# ================= VISTAS DE USUARIOS NORMALES =================

@csrf_exempt
def portal_login(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        email, pin_ingresado = data.get('email'), data.get('pin')

        colaborador = DirectorioFirmas.objects.filter(email=email).first()
        otp_record = OTPLogin.objects.filter(email=email).first()

        if (colaborador and colaborador.check_pin(pin_ingresado)) or (
                otp_record and otp_record.es_valido(pin_ingresado)):
            if otp_record: otp_record.delete()
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
    return render(request, 'motor_firmas/portal_dashboard.html', {'owner_email': owner_email, 'documentos': lista_docs})


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


# ================= VISTAS DE ADMINISTRADOR =================

@csrf_exempt
def admin_login(request):
    if not AdministradorPortal.objects.exists(): AdministradorPortal.objects.create(email="pjimenezb@raloy.com.mx")
    if request.method == 'POST':
        data = json.loads(request.body)
        email, pin_ingresado = data.get('email'), data.get('pin')
        if not AdministradorPortal.objects.filter(email=email).exists(): return JsonResponse(
            {"error": "No eres admin."}, status=403)

        colaborador = DirectorioFirmas.objects.filter(email=email).first()
        otp_record = OTPLogin.objects.filter(email=email).first()
        if (colaborador and colaborador.check_pin(pin_ingresado)) or (
                otp_record and otp_record.es_valido(pin_ingresado)):
            if otp_record: otp_record.delete()
            request.session['admin_email'] = email
            return JsonResponse({"status": "success"})
        return JsonResponse({"error": "PIN incorrecto."}, status=403)
    if request.session.get('admin_email'): return redirect('admin_dashboard')
    return render(request, 'motor_firmas/admin_login.html')


def admin_dashboard(request):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    admin_obj = AdministradorPortal.objects.get(email=admin_email)

    todos_docs = ProcesoFirma.objects.all().order_by('-created_at')
    docs_json = [{'reference_id': d.reference_id, 'token': str(d.token_acceso), 'owner_email': d.owner_email or 'N/A',
                  'dominio': d.owner_email.split('@')[1] if d.owner_email and '@' in d.owner_email else 'N/A',
                  'status': d.status, 'fecha': d.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                  'progreso': f"{sum(1 for f in d.firmantes if f.get('fecha_firma'))}/{len(d.firmantes)}"} for d in
                 todos_docs]

    plantillas = PlantillaFormulario.objects.all().order_by('-created_at')

    return render(request, 'motor_firmas/admin_dashboard.html', {
        'admin_email': admin_email,
        'docs_json': json.dumps(docs_json),
        'saved_config': json.dumps(admin_obj.configuracion_dashboard),
        'plantillas': plantillas
    })


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
    if request.method == 'POST':
        data = json.loads(request.body)

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
            requests.post(N8N_WEBHOOK_INVITAR_REGISTRO, json={"email": data.get('email'),
                                                              "link": "https://testapppjb0001.raloy.com.mx/registro-firmas/"})
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
            PlantillaFormulario.objects.create(
                nombre=data['nombre'],
                doc_id=data['doc_id'],
                owner_email=data['owner_email'],
                drive_folder_id=data['drive_folder_id'],
                view_info=data['view_info'],
                formato_folio=data.get('formato_folio', ''),
                contexto=data['contexto'],
                intencion=data['intencion'],
                variables=data['variables'],
                firmantes_config=data['firmantes_config'],
                usuarios_permitidos=data['usuarios_permitidos']
            )
            return JsonResponse({"status": "success", "msg": "Plantilla guardada exitosamente."})

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
            PlantillaFormulario.objects.filter(id=data.get('id')).delete()
            return JsonResponse({"status": "success", "msg": "Plantilla eliminada correctamente."})

    return JsonResponse({"error": "Acción inválida"}, status=400)
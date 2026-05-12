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
from .models import ProcesoFirma, DirectorioFirmas, OTPLogin, AdministradorPortal
from .utils import estampar_firma_en_pdf

# WEBHOOKS DE N8N
N8N_WEBHOOK_NOTIFICAR_CORREO = "https://n8n.raloy.com.mx/webhook/enviar-correo-firma"
N8N_WEBHOOK_FINALIZAR_PROCESO = "https://n8n.raloy.com.mx/webhook/subir-pdf-final"
N8N_WEBHOOK_NOTIFICAR_OWNER = "https://n8n.raloy.com.mx/webhook/notificar-owner"
N8N_WEBHOOK_RECUPERAR_PIN = "https://n8n.raloy.com.mx/webhook/recuperar-pin-firma"
N8N_WEBHOOK_ENVIAR_OTP = "https://n8n.raloy.com.mx/webhook/enviar-otp-portal"
N8N_WEBHOOK_INVITAR_REGISTRO = "https://n8n.raloy.com.mx/webhook/invitar-registro-firma"  # NUEVO WEBHOOK


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
                owner_email=owner_email
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

            return JsonResponse(
                {"status": "success", "msg": "Documento recibido y flujo iniciado.", "folio_asignado": ref_id})

        except Exception as e:
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=400)


def vista_firma_ui(request, token):
    proceso = get_object_or_404(ProcesoFirma, token_acceso=token)

    # MODIFICACIÓN: Checar si está cancelado
    if proceso.status == 'CANCELLED':
        return HttpResponse(
            "<h1 style='color:red; text-align:center; margin-top:50px;'>Este documento ha sido CANCELADO por el administrador y ya no puede ser firmado.</h1>")

    if proceso.status == 'COMPLETED':
        return HttpResponse(
            "<h1 style='text-align:center; margin-top:50px;'>Este documento ya ha sido firmado en su totalidad.</h1>")

    firmante_actual = proceso.firmantes[proceso.indice_actual - 1]
    filename = os.path.basename(proceso.pdf_path)
    colaborador = DirectorioFirmas.objects.filter(email=firmante_actual.get('email')).first()

    content_option = None
    if proceso.summary_data:
        content_option = proceso.summary_data.get('content-option', proceso.summary_data.get('content_option'))

    context = {
        'token': token,
        'nombre_firmante': firmante_actual.get('nombre', 'Firmante'),
        'email_firmante': firmante_actual.get('email', ''),
        'view_info': proceso.view_info,
        'summary_data': proceso.summary_data,
        'content_option': content_option,
        'pdf_url': f"{settings.MEDIA_URL}{filename}",
        'is_registered': bool(colaborador)
    }
    return render(request, 'motor_firmas/firma_ui.html', context)


@csrf_exempt
def procesar_firma(request, token):
    if request.method == 'POST':
        data = json.loads(request.body)
        ip_user = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))
        proceso = get_object_or_404(ProcesoFirma, token_acceso=token)

        # Bloqueo extra por seguridad
        if proceso.status == 'CANCELLED':
            return JsonResponse({"error": "Documento cancelado."}, status=403)

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
                if not firma_b64:
                    return JsonResponse({"error": "Firma o PIN requerido."}, status=400)

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
                if proceso.owner_email:
                    correos_destino += f",{proceso.owner_email}"
                with open(proceso.pdf_path, 'rb') as f:
                    requests.post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                                  data={"reference_id": proceso.reference_id, "status": "COMPLETED",
                                        "correos_destino": correos_destino}, files={
                            "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")})
                return JsonResponse({"status": "success", "msg": "Documento finalizado y enviado a n8n."})
        except Exception as e:
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=500)


def vista_trazabilidad(request, token):
    proceso = get_object_or_404(ProcesoFirma, token_acceso=token)
    filename = os.path.basename(proceso.pdf_path)
    context = {'proceso': proceso, 'pdf_url': f"{settings.MEDIA_URL}{filename}"}
    return render(request, 'motor_firmas/trazabilidad.html', context)


@csrf_exempt
def registro_firmas(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        pin = request.POST.get('pin')
        if DirectorioFirmas.objects.filter(email=email).exists():
            return render(request, 'motor_firmas/registro_firmas.html', {"error": "Este correo ya está registrado."})
        colaborador = DirectorioFirmas(nombre=request.POST.get('nombre'), email=email,
                                       puesto=request.POST.get('puesto'), iniciales=request.POST.get('iniciales'),
                                       firma_base64=request.POST.get('firma_base64'), acepto_terminos=True)
        colaborador.set_pin(pin)
        colaborador.save()
        return HttpResponse(
            "<h1 style='text-align:center; margin-top:50px;'>¡Registro exitoso! Ya puedes usar tu PIN para firmar.</h1>")
    return render(request, 'motor_firmas/registro_firmas.html')


@csrf_exempt
def solicitar_recuperacion(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        colaborador = DirectorioFirmas.objects.filter(email=data.get('email')).first()
        if colaborador:
            colaborador.generar_token_recuperacion()
            link = f"https://testapppjb0001.raloy.com.mx/recuperar-pin/{colaborador.reset_token}/"
            requests.post(N8N_WEBHOOK_RECUPERAR_PIN,
                          json={"email": colaborador.email, "nombre": colaborador.nombre, "link": link})
        return JsonResponse({"status": "success"})


@csrf_exempt
def resetear_pin(request, token):
    colaborador = get_object_or_404(DirectorioFirmas, reset_token=token)
    if colaborador.reset_token_expires < timezone.now():
        return HttpResponse("<h1>Este enlace ha expirado. Solicita uno nuevo.</h1>")
    if request.method == 'POST':
        nuevo_pin = request.POST.get('nuevo_pin')
        colaborador.set_pin(nuevo_pin)
        colaborador.reset_token = None
        colaborador.save()
        return HttpResponse(
            "<h1 style='text-align:center; margin-top:50px;'>PIN actualizado con éxito. Puedes cerrar esta ventana.</h1>")
    return render(request, 'motor_firmas/resetear_pin.html', {'token': token})


# =======================================================
# VISTAS DEL PORTAL (USUARIOS NORMALES)
# =======================================================

@csrf_exempt
def portal_login(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        email = data.get('email')
        pin_ingresado = data.get('pin')

        colaborador = DirectorioFirmas.objects.filter(email=email).first()
        if colaborador and colaborador.check_pin(pin_ingresado):
            request.session['owner_email'] = email
            return JsonResponse({"status": "success"})

        otp_record = OTPLogin.objects.filter(email=email).first()
        if otp_record and otp_record.es_valido(pin_ingresado):
            request.session['owner_email'] = email
            otp_record.delete()
            return JsonResponse({"status": "success"})

        return JsonResponse({"error": "PIN incorrecto o temporal expirado."}, status=403)

    if request.session.get('owner_email'):
        return redirect('portal_dashboard')

    return render(request, 'motor_firmas/portal_login.html')


@csrf_exempt
def solicitar_otp(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        email = data.get('email')
        if not email:
            return JsonResponse({"error": "Correo requerido"}, status=400)
        otp_record = OTPLogin.objects.filter(email=email).first()
        if not otp_record:
            otp_record = OTPLogin(email=email)
        otp_record.generar_otp()
        requests.post(N8N_WEBHOOK_ENVIAR_OTP, json={"email": email, "otp": otp_record.otp_code})
        return JsonResponse({"status": "success", "msg": "PIN temporal enviado."})


def portal_dashboard(request):
    owner_email = request.session.get('owner_email')
    if not owner_email:
        return redirect('portal_login')

    documentos = ProcesoFirma.objects.filter(owner_email=owner_email).order_by('-created_at')

    lista_docs = []
    for doc in documentos:
        total_firmas = len(doc.firmantes)
        firmas_hechas = sum(1 for f in doc.firmantes if f.get('fecha_firma'))
        porcentaje = int((firmas_hechas / total_firmas) * 100) if total_firmas > 0 else 0
        lista_docs.append({
            'proceso': doc,
            'total_firmas': total_firmas,
            'firmas_hechas': firmas_hechas,
            'porcentaje': porcentaje
        })

    return render(request, 'motor_firmas/portal_dashboard.html', {'owner_email': owner_email, 'documentos': lista_docs})


def portal_logout(request):
    request.session.flush()
    return redirect('portal_login')


# =======================================================
# VISTAS DEL PORTAL (ADMINISTRADORES)
# =======================================================

@csrf_exempt
def admin_login(request):
    # Autocrear el administrador principal si la tabla está vacía
    if not AdministradorPortal.objects.exists():
        AdministradorPortal.objects.create(email="pjimenezb@raloy.com.mx")

    if request.method == 'POST':
        data = json.loads(request.body)
        email = data.get('email')
        pin_ingresado = data.get('pin')

        # Verificar si es admin
        admin_obj = AdministradorPortal.objects.filter(email=email).first()
        if not admin_obj:
            return JsonResponse({"error": "Acceso denegado. No eres administrador."}, status=403)

        # Usar la misma validación de PIN (Directorio o OTP)
        colaborador = DirectorioFirmas.objects.filter(email=email).first()
        otp_record = OTPLogin.objects.filter(email=email).first()

        if (colaborador and colaborador.check_pin(pin_ingresado)) or (
                otp_record and otp_record.es_valido(pin_ingresado)):
            if otp_record: otp_record.delete()
            request.session['admin_email'] = email
            return JsonResponse({"status": "success"})

        return JsonResponse({"error": "PIN incorrecto."}, status=403)

    if request.session.get('admin_email'):
        return redirect('admin_dashboard')

    return render(request, 'motor_firmas/admin_login.html')


def admin_dashboard(request):
    admin_email = request.session.get('admin_email')
    if not admin_email:
        return redirect('admin_login')

    admin_obj = AdministradorPortal.objects.get(email=admin_email)

    # Traer TODOS los documentos para la tabla del admin
    todos_docs = ProcesoFirma.objects.all().order_by('-created_at')
    docs_json = []

    for doc in todos_docs:
        dominio = doc.owner_email.split('@')[1] if doc.owner_email and '@' in doc.owner_email else 'Desconocido'
        total_firmas = len(doc.firmantes)
        firmas_hechas = sum(1 for f in doc.firmantes if f.get('fecha_firma'))

        docs_json.append({
            'reference_id': doc.reference_id,
            'token': str(doc.token_acceso),
            'owner_email': doc.owner_email or 'Sin Dueño',
            'dominio': dominio,
            'status': doc.status,
            'fecha': doc.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            'progreso': f"{firmas_hechas}/{total_firmas}"
        })

    return render(request, 'motor_firmas/admin_dashboard.html', {
        'admin_email': admin_email,
        'docs_json': json.dumps(docs_json),
        'saved_config': json.dumps(admin_obj.configuracion_dashboard)
    })


def admin_logout(request):
    request.session.flush()
    return redirect('admin_login')


@csrf_exempt
def admin_api(request, accion):
    """Maneja las acciones AJAX del dashboard del administrador"""
    if not request.session.get('admin_email'):
        return JsonResponse({"error": "No autorizado"}, status=403)

    if request.method == 'POST':
        data = json.loads(request.body)

        # 1. Agregar nuevo Admin
        if accion == 'agregar_admin':
            nuevo_email = data.get('email')
            if AdministradorPortal.objects.filter(email=nuevo_email).exists():
                return JsonResponse({"error": "Este usuario ya es administrador."})
            AdministradorPortal.objects.create(email=nuevo_email)
            return JsonResponse({"status": "success", "msg": "Administrador agregado correctamente."})

        # 2. Cancelar Documento
        elif accion == 'cancelar_doc':
            token = data.get('token')
            doc = ProcesoFirma.objects.filter(token_acceso=token).first()
            if doc:
                doc.status = 'CANCELLED'
                doc.save()
                return JsonResponse({"status": "success", "msg": "Documento cancelado."})
            return JsonResponse({"error": "Documento no encontrado."}, status=404)

        # 3. Invitar a Registro (N8N)
        elif accion == 'invitar_registro':
            correo_destino = data.get('email')
            link = "https://testapppjb0001.raloy.com.mx/registro-firmas/"
            requests.post(N8N_WEBHOOK_INVITAR_REGISTRO, json={"email": correo_destino, "link": link})
            return JsonResponse({"status": "success", "msg": "Invitación enviada por correo."})

        # 4. Guardar Diseño/Configuración de Filtros
        elif accion == 'guardar_config':
            config = data.get('configuracion')
            admin_obj = AdministradorPortal.objects.get(email=request.session.get('admin_email'))
            admin_obj.configuracion_dashboard = config
            admin_obj.save()
            return JsonResponse({"status": "success", "msg": "Configuración guardada."})

    return JsonResponse({"error": "Acción no válida"}, status=400)
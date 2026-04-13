import os
import json
import requests
import traceback
import re
import uuid
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
N8N_WEBHOOK_SUBIR_PDF_USUARIO = "https://n8n.raloy.com.mx/webhook/subir-pdf-usuario"  # NUEVO


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
    campos_a_llenar = [key for key, em in proceso.document_variables.items() if em == firmante_actual[
        'email'] and key not in proceso.valores_capturados] if proceso.exec_mode == 'form' else []

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

            estampar_firma_en_pdf(proceso.pdf_path, firma_b64, proceso.indice_actual, firmante_esperado['email'],
                                  firmante_esperado['nombre'], ip_user)

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
                return JsonResponse
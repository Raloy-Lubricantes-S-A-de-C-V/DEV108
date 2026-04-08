import os
import json
import requests
import traceback
import re
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from .models import ProcesoFirma
from .utils import estampar_firma_en_pdf

# WEBHOOKS DE N8N
N8N_WEBHOOK_NOTIFICAR_CORREO = "https://n8n.raloy.com.mx/webhook/enviar-correo-firma"
N8N_WEBHOOK_FINALIZAR_PROCESO = "https://n8n.raloy.com.mx/webhook/subir-pdf-final"


@csrf_exempt
def recibir_documento_n8n(request):
    """
    1. n8n llama a este endpoint mandando el PDF base y la lista de firmantes.
    """
    if request.method == 'POST':
        try:
            pdf_file = request.FILES.get('pdf_file')
            data = json.loads(request.POST.get('data'))
            ref_id = data['reference_id']
            firmantes = data['firmantes']

            # Extraemos los nuevos campos de visualización enviados desde n8n
            view_info = data.get('view_info', 'file')
            summary_data = data.get('summary_data', {})

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

            # Creamos el registro incluyendo view_info y summary_data
            proceso = ProcesoFirma.objects.create(
                reference_id=ref_id,
                pdf_path=file_path,
                firmantes=firmantes,
                indice_actual=1,
                view_info=view_info,
                summary_data=summary_data
            )

            primer_firmante = firmantes[0]
            link_firma = f"https://testapppjb0001.raloy.com.mx/firmar/{proceso.token_acceso}/"

            requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO, json={
                "email": primer_firmante['email'],
                "nombre": primer_firmante['nombre'],
                "link": link_firma,
                "mensaje": f"Raloy solicita tu firma electrónica para el documento {ref_id}."
            })

            return JsonResponse({
                "status": "success",
                "msg": "Documento recibido y flujo iniciado.",
                "folio_asignado": ref_id
            })

        except Exception as e:
            print("--- ERROR EN RECIBIR_DOCUMENTO_N8N ---")
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=400)


def vista_firma_ui(request, token):
    """
    2. Interfaz web donde el usuario dibuja la firma (Responsive).
    """
    proceso = get_object_or_404(ProcesoFirma, token_acceso=token)

    if proceso.status == 'COMPLETED':
        return HttpResponse(
            "<h1>Este documento ya ha sido firmado en su totalidad y asegurado criptográficamente.</h1>")

    firmante_actual = proceso.firmantes[proceso.indice_actual - 1]

    # Construimos la URL pública del PDF para el iframe
    filename = os.path.basename(proceso.pdf_path)
    pdf_url = f"{settings.MEDIA_URL}{filename}"

    context = {
        'token': token,
        'nombre_firmante': firmante_actual.get('nombre', 'Firmante'),
        'email_firmante': firmante_actual.get('email', ''),
        'view_info': proceso.view_info,
        'summary_data': proceso.summary_data,
        'pdf_url': pdf_url
    }
    return render(request, 'motor_firmas/firma_ui.html', context)


@csrf_exempt
def procesar_firma(request, token):
    """
    3. Recibe el dibujo, lo estampa y evalúa la secuencia.
    """
    if request.method == 'POST':
        data = json.loads(request.body)
        firma_b64 = data['firma_base64']
        ip_user = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))

        proceso = get_object_or_404(ProcesoFirma, token_acceso=token)
        firmante_actual = proceso.firmantes[proceso.indice_actual - 1]

        try:
            estampar_firma_en_pdf(
                proceso.pdf_path,
                firma_b64,
                proceso.indice_actual,
                firmante_actual['email'],
                firmante_actual['nombre'],
                ip_user
            )

            if proceso.indice_actual < len(proceso.firmantes):
                proceso.indice_actual += 1
                proceso.save()

                siguiente_firmante = proceso.firmantes[proceso.indice_actual - 1]
                link_firma = f"https://testapppjb0001.raloy.com.mx/firmar/{proceso.token_acceso}/"

                requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO, json={
                    "email": siguiente_firmante['email'],
                    "nombre": siguiente_firmante['nombre'],
                    "link": link_firma,
                    "mensaje": "Es tu turno de firmar el documento."
                })

                return JsonResponse({"status": "success", "msg": "Firma guardada. Se notificó al siguiente firmante."})

            else:
                proceso.status = 'COMPLETED'
                proceso.save()

                correos_destino = ",".join([f['email'] for f in proceso.firmantes])

                with open(proceso.pdf_path, 'rb') as f:
                    requests.post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                                  data={
                                      "reference_id": proceso.reference_id,
                                      "status": "COMPLETED",
                                      "correos_destino": correos_destino
                                  },
                                  files={
                                      "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")})

                return JsonResponse({"status": "success", "msg": "Documento finalizado y enviado a n8n."})

        except Exception as e:
            print("--- ERROR EN PROCESAR_FIRMA ---")
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=500)
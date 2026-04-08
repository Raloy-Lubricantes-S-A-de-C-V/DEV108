import os
import json
import requests
import traceback
import re  # NUEVO: Importamos el motor de Expresiones Regulares
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

            # =========================================================
            # MAGIA NUEVA: Auto-incremento de reference_id si está ocupado
            # =========================================================
            original_ref_id = ref_id

            # Buscamos si el ID termina en un guion seguido de números (ej. "CONTRATO-006")
            match = re.search(r'^(.*?-)(\d+)$', ref_id)

            if match:
                base_name = match.group(1)  # Ej. "CONTRATO-RALOY-2026-"
                num_str = match.group(2)  # Ej. "006"
                num_len = len(num_str)  # Para mantener el formato (3 dígitos)
                current_num = int(num_str)

                # Ciclo: Mientras el ID exista en Mongo, súmale 1 y vuelve a armarlo
                while ProcesoFirma.objects.filter(reference_id=ref_id).exists():
                    current_num += 1
                    ref_id = f"{base_name}{str(current_num).zfill(num_len)}"
            else:
                # Si el ID no tenía números al final (ej. "CONTRATO-RALOY"),
                # le agregamos "-1", "-2" secuencialmente
                counter = 1
                while ProcesoFirma.objects.filter(reference_id=ref_id).exists():
                    ref_id = f"{original_ref_id}-{counter}"
                    counter += 1
            # =========================================================

            # BLINDAJE: Asegurar que el directorio media/ exista
            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

            # Guardar PDF temporalmente en el servidor usando el NUEVO ref_id validado
            file_path = os.path.join(settings.MEDIA_ROOT, f"{ref_id}.pdf")
            with open(file_path, 'wb+') as destination:
                for chunk in pdf_file.chunks():
                    destination.write(chunk)

            # Crear registro en la base de datos (MongoDB) con el folio validado
            proceso = ProcesoFirma.objects.create(
                reference_id=ref_id,
                pdf_path=file_path,
                firmantes=firmantes,
                indice_actual=1
            )

            # Notificar a n8n que envíe el correo al PRIMER firmante
            primer_firmante = firmantes[0]
            link_firma = f"https://testapppjb0001.raloy.com.mx/firmar/{proceso.token_acceso}/"

            requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO, json={
                "email": primer_firmante['email'],
                "nombre": primer_firmante['nombre'],
                "link": link_firma,
                "mensaje": f"Raloy solicita tu firma electrónica para el documento {ref_id}."
            })

            # Devolvemos a n8n el ID final que se le asignó (por si quieres guardarlo en un log)
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

    context = {
        'token': token,
        'nombre_firmante': firmante_actual.get('nombre', 'Firmante'),
        'email_firmante': firmante_actual.get('email', '')
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
            # 1. Inyectar firma en el PDF
            estampar_firma_en_pdf(
                proceso.pdf_path,
                firma_b64,
                proceso.indice_actual,
                firmante_actual['email'],
                firmante_actual['nombre'],
                ip_user
            )

            # 2. Evaluar si faltan más personas por firmar
            if proceso.indice_actual < len(proceso.firmantes):
                proceso.indice_actual += 1
                proceso.save()

                siguiente_firmante = proceso.firmantes[proceso.indice_actual - 1]
                link_firma = f"https://testapppjb0001.raloy.com.mx/firmar/{proceso.token_acceso}/"

                # Avisar a n8n que mande el correo al SIGUIENTE firmante
                requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO, json={
                    "email": siguiente_firmante['email'],
                    "nombre": siguiente_firmante['nombre'],
                    "link": link_firma,
                    "mensaje": "Es tu turno de firmar el documento."
                })

                return JsonResponse({"status": "success", "msg": "Firma guardada. Se notificó al siguiente firmante."})

            else:
                # 3. Flujo Terminado: Ya firmaron todos.
                proceso.status = 'COMPLETED'
                proceso.save()

                # Extraer todos los correos del JSON y unirlos con comas
                correos_destino = ",".join([f['email'] for f in proceso.firmantes])

                # Abrimos el PDF final y hacemos POST a n8n (Workflow 3)
                with open(proceso.pdf_path, 'rb') as f:
                    requests.post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                                  data={
                                      "reference_id": proceso.reference_id,
                                      "status": "COMPLETED",
                                      "correos_destino": correos_destino
                                  },
                                  # Forzamos nombre y mimetype para que n8n lo tome como Binario
                                  files={
                                      "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")})

                return JsonResponse({"status": "success", "msg": "Documento finalizado y enviado a n8n."})

        except Exception as e:
            print("--- ERROR EN PROCESAR_FIRMA ---")
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=500)
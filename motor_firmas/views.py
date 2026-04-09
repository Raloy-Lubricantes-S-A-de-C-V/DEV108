# ... importaciones existentes ...
from django.contrib.auth.hashers import make_password
from .models import ProcesoFirma, DirectorioFirmas  # Importar el nuevo modelo

# NUEVO WEBHOOK PARA N8N (Para enviar el correo de recuperación)
N8N_WEBHOOK_RECUPERAR_PIN = "https://n8n.raloy.com.mx/webhook/recuperar-pin-firma"


# --- 1. MODIFICACIÓN: VISTA DE FIRMA (Evalúa si pide PIN o Canvas) ---
def vista_firma_ui(request, token):
    proceso = get_object_or_404(ProcesoFirma, token_acceso=token)

    if proceso.status == 'COMPLETED':
        return HttpResponse("<h1>Este documento ya ha sido firmado.</h1>")

    firmante_actual = proceso.firmantes[proceso.indice_actual - 1]
    filename = os.path.basename(proceso.pdf_path)

    # VERIFICAR SI ESTÁ EN EL BANCO DE FIRMAS
    colaborador = DirectorioFirmas.objects.filter(email=firmante_actual.get('email')).first()
    is_registered = bool(colaborador)

    context = {
        'token': token,
        'nombre_firmante': firmante_actual.get('nombre', 'Firmante'),
        'email_firmante': firmante_actual.get('email', ''),
        'view_info': proceso.view_info,
        'summary_data': proceso.summary_data,
        'pdf_url': f"{settings.MEDIA_URL}{filename}",
        'is_registered': is_registered  # Pasa la variable al HTML
    }
    return render(request, 'motor_firmas/firma_ui.html', context)


# --- 2. MODIFICACIÓN: PROCESAR FIRMA (Soporte para PIN) ---
@csrf_exempt
def procesar_firma(request, token):
    if request.method == 'POST':
        data = json.loads(request.body)
        ip_user = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))

        proceso = get_object_or_404(ProcesoFirma, token_acceso=token)
        firmante_actual = proceso.firmantes[proceso.indice_actual - 1]

        try:
            # LÓGICA DE DECISIÓN: ¿Mandó PIN o mandó Base64?
            pin_ingresado = data.get('pin')
            if pin_ingresado:
                colaborador = DirectorioFirmas.objects.filter(email=firmante_actual['email']).first()
                if not colaborador or not colaborador.check_pin(pin_ingresado):
                    return JsonResponse({"error": "El PIN ingresado es incorrecto."}, status=403)
                firma_b64 = colaborador.firma_base64  # Jalamos su firma de la BD
            else:
                firma_b64 = data.get('firma_base64')
                if not firma_b64:
                    return JsonResponse({"error": "Firma o PIN requerido."}, status=400)

            # Estampar (El resto sigue igual)
            estampar_firma_en_pdf(proceso.pdf_path, firma_b64, proceso.indice_actual, firmante_actual['email'],
                                  firmante_actual['nombre'], ip_user)

            proceso.firmantes[proceso.indice_actual - 1]['fecha_firma'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S")

            if proceso.indice_actual < len(proceso.firmantes):
                proceso.indice_actual += 1
                proceso.save()
                siguiente = proceso.firmantes[proceso.indice_actual - 1]
                requests.post(N8N_WEBHOOK_NOTIFICAR_CORREO,
                              json={"email": siguiente['email'], "nombre": siguiente['nombre'],
                                    "link": f"https://testapppjb0001.raloy.com.mx/firmar/{proceso.token_acceso}/",
                                    "mensaje": "Es tu turno de firmar."})
                return JsonResponse({"status": "success", "msg": "Firma guardada."})
            else:
                proceso.status = 'COMPLETED'
                proceso.save()
                correos = ",".join([f['email'] for f in proceso.firmantes])
                if proceso.owner_email: correos += f",{proceso.owner_email}"
                with open(proceso.pdf_path, 'rb') as f:
                    requests.post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                                  data={"reference_id": proceso.reference_id, "status": "COMPLETED",
                                        "correos_destino": correos}, files={
                            "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")})
                return JsonResponse({"status": "success", "msg": "Finalizado."})
        except Exception as e:
            return JsonResponse({"error": repr(e)}, status=500)


# --- 3. NUEVA VISTA: REGISTRO DE COLABORADORES ---
def registro_firmas(request):
    if request.method == 'POST':
        # Procesar Formulario
        email = request.POST.get('email')
        pin = request.POST.get('pin')

        if DirectorioFirmas.objects.filter(email=email).exists():
            return render(request, 'motor_firmas/registro_firmas.html', {"error": "Este correo ya está registrado."})

        colaborador = DirectorioFirmas(
            nombre=request.POST.get('nombre'),
            email=email,
            puesto=request.POST.get('puesto'),
            iniciales=request.POST.get('iniciales'),
            firma_base64=request.POST.get('firma_base64'),
            acepto_terminos=True
        )
        colaborador.set_pin(pin)  # Encriptar PIN
        colaborador.save()

        return HttpResponse("<h1>¡Registro exitoso! Ya puedes usar tu PIN para firmar.</h1>")

    return render(request, 'motor_firmas/registro_firmas.html')


# --- 4. NUEVAS VISTAS: RECUPERACIÓN DE PIN ---
@csrf_exempt
def solicitar_recuperacion(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        colaborador = DirectorioFirmas.objects.filter(email=data.get('email')).first()
        if colaborador:
            colaborador.generar_token_recuperacion()
            link = f"https://testapppjb0001.raloy.com.mx/recuperar-pin/{colaborador.reset_token}/"
            # Mandar a n8n
            requests.post(N8N_WEBHOOK_RECUPERAR_PIN,
                          json={"email": colaborador.email, "nombre": colaborador.nombre, "link": link})
        # Siempre devolvemos success por seguridad (para no revelar si un correo existe o no)
        return JsonResponse({"status": "success"})


def resetear_pin(request, token):
    colaborador = get_object_or_404(DirectorioFirmas, reset_token=token)

    if colaborador.reset_token_expires < timezone.now():
        return HttpResponse("<h1>Este enlace ha expirado.</h1>")

    if request.method == 'POST':
        nuevo_pin = request.POST.get('nuevo_pin')
        colaborador.set_pin(nuevo_pin)
        colaborador.reset_token = None  # Quemar el token
        colaborador.save()
        return HttpResponse("<h1>PIN actualizado con éxito. Puedes cerrar esta ventana.</h1>")

    return render(request, 'motor_firmas/resetear_pin.html', {'token': token})
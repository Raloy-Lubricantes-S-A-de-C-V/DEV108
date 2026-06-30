with open('motor_firmas/views.py', 'r') as f:
    content = f.read()

new_block = """        elif accion == 'notificar_whatsapp':
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
                response = requests.post(
                    'https://n8n.raloy.com.mx/webhook/dsign-recordatorio-firma',
                    json={"numero": telefono, "url": link_firma},
                    timeout=20,
                )
                if not 200 <= response.status_code < 300:
                    return JsonResponse({"error": f"N8N no confirmó el envío: {response.status_code}"}, status=502)
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

        elif accion == 'invitar_registro':"""

old_block = """        elif accion == 'invitar_registro':"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open('motor_firmas/views.py', 'w') as f:
        f.write(content)
    print("Success patching views.py")
else:
    print("Could not find anchor in views.py")

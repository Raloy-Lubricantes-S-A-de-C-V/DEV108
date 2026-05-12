import sys
import re

with open('motor_firmas/views.py', 'r') as f:
    content = f.read()

# Refactor procesar_firma (Security & Error Handling)
old_procesar = '''                proceso.status = 'COMPLETED'
                proceso.save()
                correos_destino = ",".join([f['email'] for f in proceso.firmantes])
                if proceso.owner_email: correos_destino += f",{proceso.owner_email}"
                with open(proceso.pdf_path, 'rb') as f:
                    requests.post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                                  data={"reference_id": proceso.reference_id, "status": "COMPLETED",
                                        "correos_destino": correos_destino, "folder_id": proceso.dir_drive}, files={
                            "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")})
                return JsonResponse({"status": "success", "msg": "Documento finalizado."})
        except Exception as e:
            print(traceback.format_exc())
            return JsonResponse({"error": repr(e)}, status=500)'''

new_procesar = '''                proceso.status = 'COMPLETED'
                proceso.save()
                
                # REGLA DE SEGURIDAD: Solo enviar a dominios internos.
                todos_los_correos = [f['email'] for f in proceso.firmantes]
                if proceso.owner_email: todos_los_correos.append(proceso.owner_email)
                
                dominio_creador = proceso.owner_email.split('@')[1] if proceso.owner_email and '@' in proceso.owner_email else 'raloy.com.mx'
                dominios_permitidos = {dominio_creador, 'raloy.com.mx', 'consorcionova.com'}
                
                correos_internos = [email for email in set(todos_los_correos) if any(email.endswith(d) for d in dominios_permitidos)]
                correos_destino = ",".join(correos_internos)
                
                with open(proceso.pdf_path, 'rb') as f:
                    resp_n8n = requests.post(N8N_WEBHOOK_FINALIZAR_PROCESO,
                                  data={"reference_id": proceso.reference_id, "status": "COMPLETED",
                                        "correos_destino": correos_destino, "folder_id": proceso.dir_drive}, files={
                            "pdf_final": (f"{proceso.reference_id}_CERTIFICADO.pdf", f, "application/pdf")}, timeout=30)
                    
                    if resp_n8n.status_code != 200:
                        raise Exception("Fallo en la comunicación con el webhook de finalización (N8N).")
                        
                return JsonResponse({"status": "success", "msg": "Documento finalizado y enviado internamente."})
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(error_details)
            return JsonResponse({"error": f"Falla de ejecución del sistema: {str(e)}. Por favor, contacte a soporte técnico aportando este mensaje."}, status=500)'''

if old_procesar in content:
    content = content.replace(old_procesar, new_procesar)
    with open('motor_firmas/views.py', 'w') as f:
        f.write(content)
    print("Refactored procesar_firma successfully.")
else:
    print("Failed to find procesar_firma block.")

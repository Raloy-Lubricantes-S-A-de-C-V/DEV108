import fitz  # PyMuPDF
import base64
import hashlib
from datetime import datetime


import re

def estampar_variables_en_pdf(pdf_path, variables_dict):
    doc = fitz.open(pdf_path)
    modificado = False
    
    for page in doc:
        page.clean_contents()
        text = page.get_text("text")
        for key, value in variables_dict.items():
            flex_key = r"\s*".join(re.escape(char) for char in key)
            pattern = r"\{\{" + flex_key + r"(?::.*?)?\}\}"
            matches = re.findall(pattern, text, re.DOTALL)
            
            etiquetas_a_buscar = list(set(matches))
            if not etiquetas_a_buscar:
                etiquetas_a_buscar = [f"{{{{{key}}}}}"]
            
            for etiqueta in etiquetas_a_buscar:
                instancias = page.search_for(etiqueta)
                if instancias:
                    instancias.sort(key=lambda r: (r.y0, r.x0))
                    for rect in instancias:
                        rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
                        page.add_redact_annot(rect_borrar, fill=(1, 1, 1))
                    page.apply_redactions()
                    first_rect = instancias[0]
                    y_alineado = first_rect.y1 - 2.5
                    page.insert_text((first_rect.x0, y_alineado), str(value).upper(), fontsize=11, fontname="hebo", color=(0, 0, 0))
                    modificado = True

    if modificado: 
        import shutil
        temp_vars_path = pdf_path.replace(".pdf", "_temp_vars.pdf")
        doc.save(temp_vars_path)
        doc.close()
        shutil.move(temp_vars_path, pdf_path)
    else:
        doc.close()


def estampar_firma_en_pdf(pdf_path, signature_b64, signer_index, email_user, nombre_user, ip_user, coordenadas=None):
    """
    Soporta dos modos:
    1. Por Coordenadas (Drag & Drop): Si se pasa el dict 'coordenadas' con 'x', 'y' y 'page' (en porcentajes).
    2. Por Búsqueda (Plantilla): Busca la etiqueta {{FIRMA_X}}.
    """
    doc = fitz.open(pdf_path)
    if ',' in signature_b64: signature_b64 = signature_b64.split(',')[1]
    img_data = base64.b64decode(signature_b64)
    firma_estampada = False

    # MODO 1: EDITOR VISUAL (DRAG & DROP)
    if coordenadas:
        page_num = int(coordenadas.get('page', 1)) - 1
        if page_num < len(doc):
            page = doc[page_num]
            page.clean_contents()
            # Convertimos el porcentaje visual a puntos reales del PDF
            x = float(coordenadas.get('x')) * page.rect.width
            y = float(coordenadas.get('y')) * page.rect.height

            # Dibujamos nombre y firma
            page.insert_text((x, y - 5), str(nombre_user).upper(), fontsize=10, fontname="hebo", color=(0, 0, 0))
            rect_firma = fitz.Rect(x, y, x + 120, y + 60)
            page.insert_image(rect_firma, stream=img_data)
            firma_estampada = True

    # MODO 2: PLANTILLA NORMAL (BÚSQUEDA)
    if not firma_estampada:
        etiqueta_busqueda = f"{{{{FIRMA_{signer_index}}}}}"
        for page in doc:
            page.clean_contents()
            instancias = page.search_for(etiqueta_busqueda)
            if instancias:
                rect = instancias[0]
                rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
                page.add_redact_annot(rect_borrar, fill=(1, 1, 1))
                page.apply_redactions()
                page.insert_text((rect.x0, rect.y1 - 2), str(nombre_user).upper(), fontsize=10, fontname="hebo",
                                 color=(0, 0, 0))
                rect_firma = fitz.Rect(rect.x0, rect.y0 - 50, rect.x0 + 120, rect.y1)
                page.insert_image(rect_firma, stream=img_data)
                firma_estampada = True
                break

    # MODO RESPALDO (Si no hay nada, al final)
    if not firma_estampada:
        ultima_pagina = doc[-1]
        ultima_pagina.clean_contents()
        rect_firma = fitz.Rect(100, 600 - (signer_index * 60), 220, 650 - (signer_index * 60))
        ultima_pagina.insert_image(rect_firma, stream=img_data)

    # Hoja de Auditoría
    temp_path = pdf_path.replace(".pdf", "_temp.pdf")
    doc.save(temp_path)
    with open(temp_path, "rb") as f:
        document_hash = hashlib.sha256(f.read()).hexdigest()

    if signer_index == 1:
        audit_page = doc.new_page()
        audit_page.insert_text((50, 40), "CONSTANCIA DE CONSERVACIÓN INTERNA RALOY", fontsize=14, fontname="hebo",
                               color=(0, 0, 0))
    else:
        audit_page = doc[-1]

    y_inicio = 80 + ((signer_index - 1) * 120)
    timestamp = datetime.utcnow().isoformat() + "Z"

    if signer_index > 1: audit_page.draw_line(fitz.Point(50, y_inicio - 15), fitz.Point(550, y_inicio - 15),
                                              color=(0.8, 0.8, 0.8), width=1)
    audit_page.insert_text((50, y_inicio), f"Firma {signer_index} - Autenticado:", fontsize=11, fontname="hebo",
                           color=(0, 0, 0))
    audit_page.insert_text((50, y_inicio + 20), f"Nombre: {nombre_user} ({email_user})", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 40), f"Dirección IP Origen: {ip_user}", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 60), f"Sello de Tiempo (UTC): {timestamp}", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 80), f"SHA-256 Checksum: {document_hash}", fontsize=8, fontname="helv")

    import shutil
    final_temp_path = pdf_path.replace(".pdf", "_final_temp.pdf")
    doc.save(final_temp_path)
    doc.close()
    shutil.move(final_temp_path, pdf_path)
import os
import traceback
from django.conf import settings

def crear_notificacion_firma(user_email, reference_id, message_body=""):
    from .models import DirectorioFirmas, SignatureNotification, SignaturesMaster
    try:
        user = DirectorioFirmas.objects.filter(email=user_email).first()
        if not user or not user.notificar_celular:
            return False

        SignatureNotification.objects.create(
            user_email=user_email,
            reference_id=str(reference_id),
            status='pending',
            processed=False
        )
        
        # Integración DEV108/DEV036: Registro maestro
        SignaturesMaster.objects.update_or_create(
            reference_id=str(reference_id),
            defaults={
                'user_email': user_email,
                'status': 'pending',
                'notification_enabled': True,
                'notified_to_mobile': False,
            }
        )
        
        print(f"Notificación MongoDB registrada para {user_email} (Ref: {reference_id})")
        return True
    except Exception as e:
        print("Error creando notificación MongoDB:", e)
        return False

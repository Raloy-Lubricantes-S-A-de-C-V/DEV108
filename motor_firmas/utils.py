import fitz  # PyMuPDF
import base64
import hashlib
import os
from datetime import datetime


def estampar_variables_en_pdf(pdf_path, variables_dict):
    """
    Busca {{VARIABLE}} en el PDF y lo reemplaza con el valor tecleado por el usuario.
    """
    doc = fitz.open(pdf_path)
    modificado = False

    for key, value in variables_dict.items():
        etiqueta = f"{{{{{key}}}}}"  # Se convierte en {{KEY}}
        for page in doc:
            instancias = page.search_for(etiqueta)
            for rect in instancias:
                # Borrar el texto original (Redaction)
                rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
                page.add_redact_annot(rect_borrar, fill=(1, 1, 1))
                page.apply_redactions()
                # Insertar el valor tecleado
                page.insert_text((rect.x0, rect.y1), str(value), fontsize=10, fontname="helv", color=(0, 0, 0))
                modificado = True

    if modificado:
        temp_path = pdf_path.replace(".pdf", "_var_temp.pdf")
        doc.save(temp_path)
        doc.close()
        os.replace(temp_path, pdf_path)
    else:
        doc.close()


def estampar_firma_en_pdf(pdf_path, signature_b64, signer_index, email_user, nombre_user, ip_user):
    doc = fitz.open(pdf_path)
    etiqueta_busqueda = f"{{{{FIRMA_{signer_index}}}}}"
    firma_encontrada = False

    if ',' in signature_b64:
        signature_b64 = signature_b64.split(',')[1]
    img_data = base64.b64decode(signature_b64)

    for page in doc:
        instancias = page.search_for(etiqueta_busqueda)
        if instancias:
            rect = instancias[0]
            rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
            page.add_redact_annot(rect_borrar, fill=(1, 1, 1))
            page.apply_redactions()

            page.insert_text((rect.x0, rect.y1), nombre_user, fontsize=10, fontname="helv", color=(0, 0, 0))
            rect_firma = fitz.Rect(rect.x0, rect.y0 - 50, rect.x0 + 120, rect.y1)
            page.insert_image(rect_firma, stream=img_data)
            firma_encontrada = True
            break

    if not firma_encontrada:
        ultima_pagina = doc[-1]
        rect_firma = fitz.Rect(100, 600 - (signer_index * 60), 220, 650 - (signer_index * 60))
        ultima_pagina.insert_image(rect_firma, stream=img_data)

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

    if signer_index > 1:
        audit_page.draw_line(fitz.Point(50, y_inicio - 15), fitz.Point(550, y_inicio - 15), color=(0.8, 0.8, 0.8),
                             width=1)

    audit_page.insert_text((50, y_inicio), f"Firma {signer_index} - Autenticado:", fontsize=11, fontname="hebo",
                           color=(0, 0, 0))
    audit_page.insert_text((50, y_inicio + 20), f"Nombre: {nombre_user} ({email_user})", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 40), f"Dirección IP Origen: {ip_user}", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 60), f"Sello de Tiempo (UTC): {timestamp}", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 80), f"SHA-256 Checksum: {document_hash}", fontsize=8, fontname="helv")

    doc.save(pdf_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
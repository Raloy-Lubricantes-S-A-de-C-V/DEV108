import fitz  # PyMuPDF
import base64
import hashlib
from datetime import datetime


def estampar_variables_en_pdf(pdf_path, variables_dict):
    doc = fitz.open(pdf_path)
    modificado = False
    for key, value in variables_dict.items():
        etiqueta_exacta = f"{{{{{key}}}}}"
        prefijo = f"{{{{{key}:"
        
        for page in doc:
            instancias = page.search_for(etiqueta_exacta)
            
            if not instancias:
                words = page.get_text("words")
                for w in words:
                    texto = w[4]
                    if texto.startswith(prefijo) and texto.endswith("}}"):
                        instancias.append(fitz.Rect(w[0], w[1], w[2], w[3]))
                        
            for rect in instancias:
                rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
                page.add_redact_annot(rect_borrar, fill=(1, 1, 1))
                page.apply_redactions()
                y_alineado = rect.y1 - 2.5
                page.insert_text((rect.x0, y_alineado), str(value).upper(), fontsize=11, fontname="hebo",
                                 color=(0, 0, 0))
                modificado = True
    if modificado: doc.save(pdf_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
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

    doc.save(pdf_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
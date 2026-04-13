import fitz  # PyMuPDF
import base64
import hashlib
from datetime import datetime


def estampar_variables_en_pdf(pdf_path, variables_dict):
    """
    Busca las llaves {{VARIABLE}}, las ELIMINA y escribe el valor proporcionado.
    Se ajusta el eje Y para alinear el texto al renglón y se utiliza fuente en negritas.
    """
    doc = fitz.open(pdf_path)
    modificado = False

    for key, value in variables_dict.items():
        etiqueta_busqueda = f"{{{{{key}}}}}"

        for page in doc:
            instancias = page.search_for(etiqueta_busqueda)
            for rect in instancias:
                # 1. Borrar la etiqueta con un recuadro blanco
                rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
                page.add_redact_annot(rect_borrar, fill=(1, 1, 1))
                page.apply_redactions()

                # 2. Calcular nueva posición Y (Subimos el texto 2.5 puntos para alinearlo al renglón)
                y_alineado = rect.y1 - 2.5

                # 3. Escribir el valor en NEGRITAS ("hebo" = Helvetica Bold)
                page.insert_text(
                    (rect.x0, y_alineado),
                    str(value).upper(),  # Nos aseguramos de que también se imprima en mayúsculas
                    fontsize=11,
                    fontname="hebo",
                    color=(0, 0, 0)
                )
                modificado = True

    if modificado:
        # Guardar cambios
        doc.save(pdf_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)

    doc.close()


def estampar_firma_en_pdf(pdf_path, signature_b64, signer_index, email_user, nombre_user, ip_user):
    """
    Busca la etiqueta {{FIRMA_X}}, la ELIMINA físicamente del PDF, escribe el nombre del firmante,
    coloca el dibujo de la firma arriba y añade la constancia criptográfica en UNA SOLA HOJA.
    """
    doc = fitz.open(pdf_path)

    # Buscamos la etiqueta exacta
    etiqueta_busqueda = f"{{{{FIRMA_{signer_index}}}}}"
    firma_encontrada = False

    # Decodificar imagen Base64 de la firma
    if ',' in signature_b64:
        signature_b64 = signature_b64.split(',')[1]
    img_data = base64.b64decode(signature_b64)

    for page in doc:
        instancias = page.search_for(etiqueta_busqueda)
        if instancias:
            rect = instancias[0]  # Coordenadas exactas de {{FIRMA_X}}

            # 1. BORRADO EXTREMO (REDACTION)
            rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
            page.add_redact_annot(rect_borrar, fill=(1, 1, 1))  # Cuadro blanco
            page.apply_redactions()  # Esto elimina físicamente el texto

            # 2. ESCRIBIR NOMBRE REAL (Alineado y en negritas opcional)
            y_alineado = rect.y1 - 2
            page.insert_text((rect.x0, y_alineado), nombre_user, fontsize=10, fontname="helv", color=(0, 0, 0))

            # 3. ESTAMPAR DIBUJO DE LA FIRMA
            rect_firma = fitz.Rect(rect.x0, rect.y0 - 50, rect.x0 + 120, rect.y1)
            page.insert_image(rect_firma, stream=img_data)

            firma_encontrada = True
            break

    if not firma_encontrada:
        # Modo Respaldo
        ultima_pagina = doc[-1]
        rect_firma = fitz.Rect(100, 600 - (signer_index * 60), 220, 650 - (signer_index * 60))
        ultima_pagina.insert_image(rect_firma, stream=img_data)

    # Calcular Hash para NOM-151
    temp_path = pdf_path.replace(".pdf", "_temp.pdf")
    doc.save(temp_path)
    with open(temp_path, "rb") as f:
        document_hash = hashlib.sha256(f.read()).hexdigest()

    # ========================================================
    # Control de la Hoja de Auditoría Única
    # ========================================================
    if signer_index == 1:
        # Si es el primer firmante, creamos la hoja anexa al final
        audit_page = doc.new_page()
        audit_page.insert_text((50, 40), "CONSTANCIA DE CONSERVACIÓN INTERNA RALOY", fontsize=14, fontname="hebo",
                               color=(0, 0, 0))
    else:
        # Si es el 2do, 3ro, etc., usamos la última hoja ya creada
        audit_page = doc[-1]

    # Calculamos en qué coordenada 'Y' (vertical) vamos a escribir para que no se encimen.
    y_inicio = 80 + ((signer_index - 1) * 120)

    timestamp = datetime.utcnow().isoformat() + "Z"

    # Dibujamos una pequeña línea separadora si no es el primero
    if signer_index > 1:
        audit_page.draw_line(fitz.Point(50, y_inicio - 15), fitz.Point(550, y_inicio - 15), color=(0.8, 0.8, 0.8),
                             width=1)

    # Insertamos los datos de la firma apilados
    audit_page.insert_text((50, y_inicio), f"Firma {signer_index} - Autenticado:", fontsize=11, fontname="hebo",
                           color=(0, 0, 0))
    audit_page.insert_text((50, y_inicio + 20), f"Nombre: {nombre_user} ({email_user})", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 40), f"Dirección IP Origen: {ip_user}", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 60), f"Sello de Tiempo (UTC): {timestamp}", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 80), f"SHA-256 Checksum: {document_hash}", fontsize=8, fontname="helv")

    doc.save(pdf_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
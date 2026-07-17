import fitz  # PyMuPDF
import base64
import hashlib
from datetime import datetime


import re


def _limpiar_firma_base64(signature_b64):
    if not signature_b64:
        return ''
    signature_b64 = str(signature_b64)
    if ',' in signature_b64:
        signature_b64 = signature_b64.split(',', 1)[1]
    return signature_b64.strip()


def _crear_posicion_firma(page, page_num, x, y, width=120, height=60, origen='manual'):
    return {
        'page': page_num + 1,
        'x': x / page.rect.width if page.rect.width else 0,
        'y': y / page.rect.height if page.rect.height else 0,
        'width': width / page.rect.width if page.rect.width else 0,
        'height': height / page.rect.height if page.rect.height else 0,
        'rect': {
            'x0': x,
            'y0': y,
            'x1': x + width,
            'y1': y + height,
        },
        'origen': origen,
    }


def _rect_from_position(page, posicion):
    if not posicion:
        return None

    rect_data = posicion.get('rect') if isinstance(posicion, dict) else None
    if isinstance(rect_data, dict):
        try:
            x0 = float(rect_data.get('x0'))
            y0 = float(rect_data.get('y0'))
            x1 = float(rect_data.get('x1'))
            y1 = float(rect_data.get('y1'))
            return fitz.Rect(x0 - 4, y0 - 18, x1 + 8, y1 + 8)
        except (TypeError, ValueError):
            pass

    try:
        x = float(posicion.get('x')) * page.rect.width
        y = float(posicion.get('y')) * page.rect.height
        width = float(posicion.get('width', 120 / page.rect.width)) * page.rect.width
        height = float(posicion.get('height', 60 / page.rect.height)) * page.rect.height
        return fitz.Rect(x - 4, y - 18, x + width + 8, y + height + 8)
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return None


def _inferir_rect_firma_por_nombre(doc, nombre_user):
    nombre_user = str(nombre_user or '').strip()
    if not nombre_user:
        return None, None

    terminos = []
    nombre_upper = nombre_user.upper()
    if nombre_upper:
        terminos.append(nombre_upper)
    if nombre_user not in terminos:
        terminos.append(nombre_user)

    for page_num, page in enumerate(doc):
        page_text = page.get_text("text")
        if "CONSTANCIA DE CONSERV" in page_text or "BITÁCORA DE AJUSTE" in page_text:
            continue
        for termino in terminos:
            instancias = page.search_for(termino)
            if not instancias:
                continue
            rect = sorted(instancias, key=lambda r: (r.y0, r.x0))[0]
            return page_num, fitz.Rect(
                max(0, rect.x0 - 8),
                max(0, rect.y0 - 78),
                min(page.rect.width, rect.x0 + 150),
                min(page.rect.height, rect.y1 + 78),
            )
    return None, None


def _insertar_firma(page, signature_b64, nombre_user, x, y):
    img_data = base64.b64decode(_limpiar_firma_base64(signature_b64))
    page.clean_contents()
    page.insert_text((x, y - 5), str(nombre_user).upper(), fontsize=10, fontname="hebo", color=(0, 0, 0))
    rect_firma = fitz.Rect(x, y, x + 120, y + 60)
    page.insert_image(rect_firma, stream=img_data)
    return rect_firma


def _hash_en_lineas(hash_firma, chunk_size=24):
    hash_firma = str(hash_firma or '').strip()
    return "\n".join(hash_firma[i:i + chunk_size] for i in range(0, len(hash_firma), chunk_size))


def _insertar_hash_firma(page, hash_firma, nombre_user, x, y):
    hash_firma = str(hash_firma or '').strip()
    if not hash_firma:
        raise ValueError(f"No hay firma ni hash recuperable para {nombre_user or 'Firmante'}.")

    page.clean_contents()
    page.insert_text((x, y - 5), str(nombre_user).upper(), fontsize=10, fontname="hebo", color=(0, 0, 0))
    rect_firma = fitz.Rect(x, y, x + 138, y + 60)
    page.draw_rect(rect_firma, color=(0.08, 0.08, 0.08), fill=(1, 1, 1), width=0.7)
    page.insert_textbox(
        fitz.Rect(x + 4, y + 5, x + 134, y + 57),
        f"HASH FIRMA:\n{_hash_en_lineas(hash_firma)}",
        fontsize=5.2,
        fontname="helv",
        color=(0, 0, 0),
        align=fitz.TEXT_ALIGN_CENTER,
    )
    return rect_firma


def _texto_una_linea(value, default='N/A'):
    value = str(value or '').replace('\n', ' ').strip()
    return value or default


def _insertar_textbox(page, rect, text, fontsize=8, fontname="helv", color=(0, 0, 0), align=fitz.TEXT_ALIGN_LEFT):
    page.insert_textbox(
        rect,
        str(text or ''),
        fontsize=fontsize,
        fontname=fontname,
        color=color,
        align=align,
    )


def _insertar_evidencia_en_rect(page, ajuste, rect):
    nombre = ajuste.get('nombre') or 'Firmante'
    firma_b64 = ajuste.get('firma_base64')
    if firma_b64:
        try:
            img_data = base64.b64decode(_limpiar_firma_base64(firma_b64))
            page.insert_image(rect, stream=img_data, keep_proportion=True)
            return 'firma'
        except Exception:
            pass

    hash_firma = str(ajuste.get('hash_firma') or '').strip()
    if not hash_firma:
        raise ValueError(f"No hay firma ni hash recuperable para {nombre}.")

    page.draw_rect(rect, color=(0.08, 0.08, 0.08), fill=(1, 1, 1), width=0.6)
    _insertar_textbox(
        page,
        fitz.Rect(rect.x0 + 4, rect.y0 + 5, rect.x1 - 4, rect.y1 - 4),
        f"HASH FIRMA:\n{_hash_en_lineas(hash_firma, 26)}",
        fontsize=5.3,
        align=fitz.TEXT_ALIGN_CENTER,
    )
    return 'hash'


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


def estampar_campos_posicionados_en_pdf(pdf_path, variables_dict, campos):
    doc = fitz.open(pdf_path)
    modificado = False

    for campo in campos or []:
        if not isinstance(campo, dict):
            continue
        key = str(campo.get('key') or '').strip()
        value = variables_dict.get(key)
        if value in (None, ''):
            continue
        try:
            page_num = max(int(campo.get('page') or 1) - 1, 0)
        except (TypeError, ValueError):
            page_num = 0
        if page_num >= len(doc):
            continue

        page = doc[page_num]
        try:
            x = float(campo.get('x') or 0) * page.rect.width
            y = float(campo.get('y') or 0) * page.rect.height
            width = max(float(campo.get('width') or 0.1) * page.rect.width, 24)
            height = max(float(campo.get('height') or 0.035) * page.rect.height, 12)
        except (TypeError, ValueError):
            continue

        rect = fitz.Rect(
            max(0, x),
            max(0, y),
            min(page.rect.width, x + width),
            min(page.rect.height, y + height),
        )
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            continue

        page.clean_contents()
        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
        font_size = min(11, max(7, rect.height * 0.48))
        page.insert_textbox(
            fitz.Rect(rect.x0 + 2, rect.y0 + 1, rect.x1 - 2, rect.y1 - 1),
            str(value).upper(),
            fontsize=font_size,
            fontname="hebo",
            color=(0, 0, 0),
            align=fitz.TEXT_ALIGN_LEFT,
        )
        modificado = True

    if modificado:
        import shutil
        temp_fields_path = pdf_path.replace(".pdf", "_temp_fields.pdf")
        doc.save(temp_fields_path)
        doc.close()
        shutil.move(temp_fields_path, pdf_path)
    else:
        doc.close()


def estampar_firma_en_pdf(
        pdf_path, signature_b64, signer_index, email_user, nombre_user, ip_user,
        coordenadas=None, registro=None, fecha_firma=None, hash_documento=None, return_metadata=False):
    """
    Soporta dos modos:
    1. Por Coordenadas (Drag & Drop): Si se pasa el dict 'coordenadas' con 'x', 'y' y 'page' (en porcentajes).
    2. Por Búsqueda (Plantilla): Busca la etiqueta {{FIRMA_X}}.
    """
    doc = fitz.open(pdf_path)
    firma_estampada = False
    posicion_estampada = None

    # MODO 1: EDITOR VISUAL (DRAG & DROP)
    if coordenadas:
        page_num = int(coordenadas.get('page', 1)) - 1
        if page_num < len(doc):
            page = doc[page_num]
            # Convertimos el porcentaje visual a puntos reales del PDF
            x = float(coordenadas.get('x')) * page.rect.width
            y = float(coordenadas.get('y')) * page.rect.height

            _insertar_firma(page, signature_b64, nombre_user, x, y)
            posicion_estampada = _crear_posicion_firma(page, page_num, x, y, origen='coordenadas')
            firma_estampada = True

    # MODO 2: PLANTILLA NORMAL (BÚSQUEDA)
    if not firma_estampada:
        etiqueta_busqueda = f"{{{{FIRMA_{signer_index}}}}}"
        for page_num, page in enumerate(doc):
            page.clean_contents()
            instancias = page.search_for(etiqueta_busqueda)
            if instancias:
                rect = instancias[0]
                rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
                page.add_redact_annot(rect_borrar, fill=(1, 1, 1))
                page.apply_redactions()
                x = rect.x0
                y = rect.y0 - 50
                page.insert_text((x, rect.y1 - 2), str(nombre_user).upper(), fontsize=10, fontname="hebo",
                                 color=(0, 0, 0))
                rect_firma = fitz.Rect(x, y, x + 120, rect.y1)
                img_data = base64.b64decode(_limpiar_firma_base64(signature_b64))
                page.insert_image(rect_firma, stream=img_data)
                posicion_estampada = _crear_posicion_firma(
                    page, page_num, x, y, width=120, height=rect.y1 - y, origen='plantilla'
                )
                firma_estampada = True
                break

    # MODO RESPALDO (Si no hay nada, al final)
    if not firma_estampada:
        ultima_pagina = doc[-1]
        ultima_pagina.clean_contents()
        x = 100
        y = 600 - (signer_index * 60)
        rect_firma = fitz.Rect(x, y, 220, 650 - (signer_index * 60))
        img_data = base64.b64decode(_limpiar_firma_base64(signature_b64))
        ultima_pagina.insert_image(rect_firma, stream=img_data)
        posicion_estampada = _crear_posicion_firma(
            ultima_pagina, len(doc) - 1, x, y, width=120, height=rect_firma.height, origen='respaldo'
        )

    # Hoja de Auditoría
    temp_path = pdf_path.replace(".pdf", "_temp.pdf")
    doc.save(temp_path)
    with open(temp_path, "rb") as f:
        document_hash = hash_documento or hashlib.sha256(f.read()).hexdigest()

    if signer_index == 1:
        audit_page = doc.new_page()
        audit_page.insert_text((50, 40), "CONSTANCIA DE CONSERVACIÓN INTERNA RALOY", fontsize=14, fontname="hebo",
                               color=(0, 0, 0))
    else:
        audit_page = doc[-1]

    y_inicio = 80 + ((signer_index - 1) * 120)
    timestamp = fecha_firma or (datetime.utcnow().isoformat() + "Z")

    if signer_index > 1: audit_page.draw_line(fitz.Point(50, y_inicio - 15), fitz.Point(550, y_inicio - 15),
                                              color=(0.8, 0.8, 0.8), width=1)
    audit_page.insert_text((50, y_inicio), f"Firma {signer_index} - Autenticado:", fontsize=11, fontname="hebo",
                           color=(0, 0, 0))
    audit_page.insert_text((50, y_inicio + 20), f"Nombre: {nombre_user} ({email_user})", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 40), f"Dirección IP Origen: {ip_user}", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 60), f"Sello de Tiempo (UTC): {timestamp}", fontsize=10, fontname="helv")
    audit_page.insert_text((50, y_inicio + 80), f"SHA-256 Checksum: {document_hash}", fontsize=8, fontname="helv")
    if registro:
        audit_page.insert_text((50, y_inicio + 100), f"Registro/Folio: {registro}", fontsize=8, fontname="helv")

    import shutil
    final_temp_path = pdf_path.replace(".pdf", "_final_temp.pdf")
    doc.save(final_temp_path)
    doc.close()
    shutil.move(final_temp_path, pdf_path)
    if return_metadata:
        return {'hash': document_hash, 'posicion_estampada': posicion_estampada}
    return document_hash


def reubicar_firmas_en_pdf(pdf_path, ajustes, actor_email='', actor_role=''):
    doc = fitz.open(pdf_path)
    nuevas_posiciones = {}
    ajustes_ordenados = sorted(
        ajustes,
        key=lambda item: (
            int(item.get('orden_nuevo') or item.get('orden_anterior') or 0),
            int(item.get('orden_anterior') or 0),
        ),
    )
    page_rect = doc[0].rect if len(doc) else fitz.paper_rect("letter")
    width = page_rect.width
    height = page_rect.height
    margin = 42
    gap = 14
    columns = 2 if width >= 560 else 1
    card_width = (width - (margin * 2) - (gap * (columns - 1))) / columns
    card_height = 158
    header_height = 108
    footer_height = 34
    cards_per_page = max(columns, int(((height - header_height - footer_height) // card_height) * columns))
    cards_per_page = max(cards_per_page, columns)
    fecha_utc = datetime.utcnow().isoformat() + "Z"

    def nueva_hoja(numero_hoja):
        page = doc.new_page(width=width, height=height)
        page.insert_text((margin, 38), "HOJA DE CORRECCIÓN DE ORDEN DE FIRMAS", fontsize=14, fontname="hebo", color=(0, 0, 0))
        _insertar_textbox(
            page,
            fitz.Rect(margin, 52, width - margin, 86),
            "Esta hoja se anexa como constancia de corrección. Las páginas originales del documento se conservan sin nuevas redacciones ni reestampados.",
            fontsize=8,
            color=(0.18, 0.23, 0.28),
        )
        page.insert_text((margin, 96), f"Realizado por: {_texto_una_linea(actor_email)} ({_texto_una_linea(actor_role)})", fontsize=8, fontname="helv")
        page.insert_text((width - 210, 96), f"Fecha UTC: {fecha_utc}", fontsize=8, fontname="helv")
        page.draw_line(fitz.Point(margin, 106), fitz.Point(width - margin, 106), color=(0.75, 0.75, 0.75), width=0.8)
        page.insert_text((margin, height - 24), f"Hoja de corrección {numero_hoja}", fontsize=8, fontname="helv", color=(0.35, 0.35, 0.35))
        return page

    page = None
    for idx, ajuste in enumerate(ajustes_ordenados):
        if idx % cards_per_page == 0:
            page = nueva_hoja((idx // cards_per_page) + 1)

        slot = idx % cards_per_page
        col = slot % columns
        row = slot // columns
        x0 = margin + col * (card_width + gap)
        y0 = header_height + row * card_height
        card = fitz.Rect(x0, y0, x0 + card_width, y0 + card_height - 10)
        page.draw_rect(card, color=(0.78, 0.78, 0.78), fill=(1, 1, 1), width=0.7)

        orden = ajuste.get('orden_nuevo') or idx + 1
        orden_anterior = ajuste.get('orden_anterior') or 'N/A'
        page.insert_text((card.x0 + 10, card.y0 + 18), f"Orden correcto: {orden}", fontsize=10, fontname="hebo", color=(0, 0, 0))
        page.insert_text((card.x1 - 92, card.y0 + 18), f"Antes: {orden_anterior}", fontsize=7, fontname="helv", color=(0.35, 0.35, 0.35))
        _insertar_textbox(page, fitz.Rect(card.x0 + 10, card.y0 + 26, card.x1 - 10, card.y0 + 46), _texto_una_linea(ajuste.get('nombre'), 'Firmante'), fontsize=8, fontname="hebo")
        _insertar_textbox(page, fitz.Rect(card.x0 + 10, card.y0 + 45, card.x1 - 10, card.y0 + 62), _texto_una_linea(ajuste.get('email')), fontsize=7, color=(0.18, 0.23, 0.28))
        etiqueta = ajuste.get('etiqueta') or ajuste.get('label') or ajuste.get('key')
        _insertar_textbox(page, fitz.Rect(card.x0 + 10, card.y0 + 62, card.x1 - 10, card.y0 + 82), f"Etiqueta/Rol: {_texto_una_linea(etiqueta)}", fontsize=7, color=(0.18, 0.23, 0.28))
        _insertar_textbox(page, fitz.Rect(card.x0 + 10, card.y0 + 80, card.x1 - 10, card.y0 + 97), f"Firmado: {_texto_una_linea(ajuste.get('fecha_firma'))}", fontsize=7, color=(0.18, 0.23, 0.28))

        evidencia_rect = fitz.Rect(card.x0 + 10, card.y0 + 98, card.x1 - 10, card.y1 - 10)
        metodo = _insertar_evidencia_en_rect(page, ajuste, evidencia_rect)
        nuevas_posiciones[ajuste['key']] = _crear_posicion_firma(
            page,
            len(doc) - 1,
            evidencia_rect.x0,
            evidencia_rect.y0,
            width=evidencia_rect.width,
            height=evidencia_rect.height,
            origen='hoja_correccion',
        )
        page.insert_text((card.x1 - 78, card.y1 - 14), f"Evidencia: {metodo}", fontsize=6.5, fontname="helv", color=(0.35, 0.35, 0.35))

    import shutil
    temp_path = pdf_path.replace(".pdf", f"_ajuste_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf")
    doc.save(temp_path)
    doc.close()

    with open(temp_path, "rb") as f:
        document_hash = hashlib.sha256(f.read()).hexdigest()

    shutil.move(temp_path, pdf_path)
    return {'hash': document_hash, 'posiciones': nuevas_posiciones}
import os
import traceback
from django.conf import settings
from django.utils import timezone


_MONGO_CLIENT = None


def _normalizar_email(email):
    return str(email or '').strip().lower()


def _mongo_database():
    global _MONGO_CLIENT
    db_conf = settings.DATABASES['default']
    if _MONGO_CLIENT is None:
        from pymongo import MongoClient
        _MONGO_CLIENT = MongoClient(
            db_conf['CLIENT']['host'],
            serverSelectionTimeoutMS=5000,
            uuidRepresentation='pythonLegacy',
        )
    return _MONGO_CLIENT[db_conf['NAME']]


def _mongo_collection(model):
    return _mongo_database()[model._meta.db_table]


def _mongo_next_int_id(model):
    document = _mongo_collection(model).find_one(
        {'id': {'$exists': True}},
        sort=[('id', -1)],
        projection={'id': True},
    )
    try:
        return int(document.get('id', 0)) + 1 if document else 1
    except (TypeError, ValueError):
        return 1


def _mongo_now():
    return timezone.now().replace(tzinfo=None)


def _usuario_tiene_notificacion_movil(DirectorioFirmas, email_norm):
    user = _mongo_collection(DirectorioFirmas).find_one(
        {'email': email_norm},
        projection={'notificar_celular': True},
    )
    return bool(user and user.get('notificar_celular'))


def _registrar_notificacion_pendiente(SignatureNotification, email_norm, reference_id):
    collection = _mongo_collection(SignatureNotification)
    reference_id = str(reference_id)
    query = {
        'user_email': email_norm,
        'reference_id': reference_id,
        'status': 'pending',
        'processed': False,
    }

    if collection.find_one(query):
        collection.update_one(query, {'$set': {'created_at': _mongo_now()}})
        return

    collection.insert_one({
        'id': _mongo_next_int_id(SignatureNotification),
        'user_email': email_norm,
        'reference_id': reference_id,
        'status': 'pending',
        'created_at': _mongo_now(),
        'processed': False,
    })


def _actualizar_registro_maestro(SignaturesMaster, email_norm, reference_id):
    collection = _mongo_collection(SignaturesMaster)
    reference_id = str(reference_id)
    now = _mongo_now()
    master = collection.find_one({'reference_id': reference_id})

    debe_actualizar = (
        master is None
        or _normalizar_email(master.get('user_email')) == email_norm
        or master.get('status') != 'pending'
        or not master.get('notification_enabled', False)
    )
    if not debe_actualizar:
        return

    update_doc = {
        'user_email': email_norm,
        'status': 'pending',
        'notification_enabled': True,
        'notified_to_mobile': False,
        'updated_at': now,
    }
    if master:
        collection.update_one({'_id': master['_id']}, {'$set': update_doc})
        return

    update_doc.update({
        'id': _mongo_next_int_id(SignaturesMaster),
        'reference_id': reference_id,
    })
    collection.insert_one(update_doc)


def crear_notificacion_firma(user_email, reference_id, message_body=""):
    from .models import DirectorioFirmas, SignatureNotification, SignaturesMaster
    try:
        email_norm = _normalizar_email(user_email)
        if not email_norm:
            return False

        if not _usuario_tiene_notificacion_movil(DirectorioFirmas, email_norm):
            return False

        _registrar_notificacion_pendiente(SignatureNotification, email_norm, reference_id)

        # Integración DEV108/DEV036: Registro maestro
        _actualizar_registro_maestro(SignaturesMaster, email_norm, reference_id)

        print(f"Notificación MongoDB registrada para {email_norm} (Ref: {reference_id})")
        return True
    except Exception as e:
        print("Error creando notificación MongoDB:", e)
        return False

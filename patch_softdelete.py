with open('motor_firmas/views.py', 'r') as f:
    content = f.read()

# 1. portal_pdfs_usuario
old_find = "pdfs = _mongo_find(DocumentoPDFUsuario, {'owner_email': owner_email}, [('created_at', -1)])"
new_find = "pdfs = _mongo_find(DocumentoPDFUsuario, {'owner_email': owner_email, 'deleted': {'$ne': True}}, [('created_at', -1)])"

if old_find in content:
    content = content.replace(old_find, new_find)
    print("Replaced _mongo_find in portal_pdfs_usuario")
else:
    print("Could not find _mongo_find")

# 2. eliminar_pdf_usuario
old_eliminar = """        archivo_local = getattr(doc, 'archivo_local', None)
        if archivo_local:
            full_path = os.path.join(settings.MEDIA_ROOT, archivo_local)
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                except:
                    pass

        _mongo_collection(DocumentoPDFUsuario).delete_one({'_id': doc.id})
        return JsonResponse({"status": "success"})"""

new_eliminar = """        _mongo_update_document(DocumentoPDFUsuario, doc, {'deleted': True})
        return JsonResponse({"status": "success"})"""

if old_eliminar in content:
    content = content.replace(old_eliminar, new_eliminar)
    print("Replaced elimination logic in eliminar_pdf_usuario")
else:
    print("Could not find elimination logic in eliminar_pdf_usuario")

# 3. iniciar_firma_libre
old_iniciar = """    if os.path.exists(original_path):
        os.remove(original_path)
    _mongo_collection(DocumentoPDFUsuario).delete_one({'_id': doc.id})"""

new_iniciar = """    _mongo_update_document(DocumentoPDFUsuario, doc, {'deleted': True, 'converted_to_master': True})"""

if old_iniciar in content:
    content = content.replace(old_iniciar, new_iniciar)
    print("Replaced elimination logic in iniciar_firma_libre")
else:
    print("Could not find elimination logic in iniciar_firma_libre")

with open('motor_firmas/views.py', 'w') as f:
    f.write(content)
print("Finished patching views.py")

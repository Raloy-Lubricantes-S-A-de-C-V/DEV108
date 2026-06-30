with open('motor_firmas/views.py', 'r') as f:
    content = f.read()

old_admin_det = """    return render(request, 'motor_firmas/admin_usuarios_detalle.html', {
        'admin_email': admin_email,
        'es_superadmin': getattr(admin_obj, 'es_superadmin', False) or admin_email == 'pjimenezb@raloy.com.mx',
        'usuario': usuario,
        'tecnicos': tecnicos,
        'permisos': permisos
    })"""

new_admin_det = """    usuario.api_keys = _json_or_default(getattr(usuario, 'api_keys', []), [])
    return render(request, 'motor_firmas/admin_usuarios_detalle.html', {
        'admin_email': admin_email,
        'es_superadmin': getattr(admin_obj, 'es_superadmin', False) or admin_email == 'pjimenezb@raloy.com.mx',
        'usuario': usuario,
        'tecnicos': tecnicos,
        'permisos': permisos
    })"""

if old_admin_det in content:
    content = content.replace(old_admin_det, new_admin_det)
    with open('motor_firmas/views.py', 'w') as f:
        f.write(content)
    print("Patched admin_usuarios_detalle")
else:
    print("Could not find admin_usuarios_detalle block")

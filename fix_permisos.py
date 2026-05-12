import sys

with open('motor_firmas/views.py', 'r') as f:
    content = f.read()

old_string = '''    dominio = owner_email.split('@')[1] if '@' in owner_email else ''
    tiene_carpeta_dominio = CarpetaDominio.objects.filter(dominio=dominio).exists()

    return render(request, 'motor_firmas/portal_dashboard.html', {'owner_email': owner_email, 'documentos': lista_docs,
                                                                  'tiene_carpeta_dominio': tiene_carpeta_dominio})'''

new_string = '''    dominio = owner_email.split('@')[1] if '@' in owner_email else ''
    tiene_carpeta_dominio = CarpetaDominio.objects.filter(dominio=dominio).exists()

    colaborador = DirectorioFirmas.objects.filter(email=owner_email).first()
    permisos = colaborador.permisos_portal if colaborador and colaborador.permisos_portal else []
    import json
    while isinstance(permisos, str):
        try:
            parsed = json.loads(permisos)
            if parsed == permisos: break
            permisos = parsed
        except:
            break
    if not isinstance(permisos, list): permisos = []

    return render(request, 'motor_firmas/portal_dashboard.html', {
        'owner_email': owner_email, 
        'documentos': lista_docs,
        'tiene_carpeta_dominio': tiene_carpeta_dominio,
        'permisos': permisos
    })'''

if old_string not in content:
    print('Failed to find old string.')
    sys.exit(1)

content = content.replace(old_string, new_string)

with open('motor_firmas/views.py', 'w') as f:
    f.write(content)

print('Patch applied')

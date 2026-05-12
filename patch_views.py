import sys
import re

with open('motor_firmas/views.py', 'r') as f:
    content = f.read()

# 1. Update portal_login to set ultima_actividad
old_login = '''        if (colaborador and colaborador.check_pin(pin_ingresado)) or (
                otp_record and otp_record.es_valido(pin_ingresado)):
            if otp_record: otp_record.delete()
            request.session['owner_email'] = email
            return JsonResponse({"status": "success"})'''

new_login = '''        if (colaborador and colaborador.check_pin(pin_ingresado)) or (
                otp_record and otp_record.es_valido(pin_ingresado)):
            if otp_record: otp_record.delete()
            if colaborador:
                colaborador.ultima_actividad = timezone.now()
                colaborador.save()
            request.session['owner_email'] = email
            return JsonResponse({"status": "success"})'''
content = content.replace(old_login, new_login)

# 2. Update portal_dashboard to pass permisos_portal
old_dash = '''    return render(request, 'motor_firmas/portal_dashboard.html', {'owner_email': owner_email, 'documentos': lista_docs})'''
new_dash = '''    colaborador = DirectorioFirmas.objects.filter(email=owner_email).first()
    permisos = colaborador.permisos_portal if colaborador and colaborador.permisos_portal else []
    if isinstance(permisos, str):
        try:
            import json
            permisos = json.loads(permisos)
        except:
            permisos = []
            
    return render(request, 'motor_firmas/portal_dashboard.html', {
        'owner_email': owner_email, 
        'documentos': lista_docs,
        'permisos': permisos
    })'''
content = content.replace(old_dash, new_dash)

# 3. Update admin_login to make pjimenezb superadmin
old_admin_login = '''def admin_login(request):
    if not AdministradorPortal.objects.exists(): AdministradorPortal.objects.create(email="pjimenezb@raloy.com.mx")
    if request.method == 'POST':'''
new_admin_login = '''def admin_login(request):
    if not AdministradorPortal.objects.exists(): AdministradorPortal.objects.create(email="pjimenezb@raloy.com.mx", es_superadmin=True)
    else:
        # Asegurar que pjimenezb sea superadmin siempre
        pj = AdministradorPortal.objects.filter(email="pjimenezb@raloy.com.mx").first()
        if pj and not pj.es_superadmin:
            pj.es_superadmin = True
            pj.save()
            
    if request.method == 'POST':'''
content = content.replace(old_admin_login, new_admin_login)

# 4. Add new admin views at the bottom
new_views = '''
# ================= NUEVAS VISTAS ADMIN =================

def admin_usuarios(request):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    
    admin_obj = get_object_or_404(AdministradorPortal, email=admin_email)
    
    if admin_obj.es_superadmin:
        usuarios = DirectorioFirmas.objects.all().order_by('-fecha_registro')
    else:
        usuarios = DirectorioFirmas.objects.filter(tecnico_asignado=admin_email).order_by('-fecha_registro')
        
    lista_usrs = []
    for u in usuarios:
        docs = ProcesoFirma.objects.filter(owner_email=u.email)
        tot_docs = docs.count()
        # Calculate effectiveness simply as percentage of documents signed or created
        lista_usrs.append({
            'id': u.id,
            'nombre': u.nombre,
            'email': u.email,
            'tecnico': u.tecnico_asignado or 'Sin asignar',
            'ultima_act': u.ultima_actividad.strftime("%d/%m/%Y %H:%M") if u.ultima_actividad else 'Nunca',
            'tot_docs': tot_docs
        })
        
    return render(request, 'motor_firmas/admin_usuarios.html', {
        'admin_email': admin_email,
        'es_superadmin': admin_obj.es_superadmin,
        'usuarios': lista_usrs
    })

def admin_usuarios_detalle(request, usuario_id):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    
    admin_obj = get_object_or_404(AdministradorPortal, email=admin_email)
    usuario = get_object_or_404(DirectorioFirmas, id=usuario_id)
    
    if not admin_obj.es_superadmin and usuario.tecnico_asignado != admin_email:
        return HttpResponse("<h1>No tienes permisos para ver a este usuario.</h1>", status=403)
        
    tecnicos = AdministradorPortal.objects.all()
    
    permisos = usuario.permisos_portal
    import json
    if isinstance(permisos, str):
        try: permisos = json.loads(permisos)
        except: permisos = []
    if not isinstance(permisos, list): permisos = []

    return render(request, 'motor_firmas/admin_usuarios_detalle.html', {
        'admin_email': admin_email,
        'es_superadmin': admin_obj.es_superadmin,
        'usuario': usuario,
        'tecnicos': tecnicos,
        'permisos': permisos
    })

def admin_administradores(request):
    admin_email = request.session.get('admin_email')
    if not admin_email: return redirect('admin_login')
    
    admin_obj = get_object_or_404(AdministradorPortal, email=admin_email)
    if not admin_obj.es_superadmin:
        return HttpResponse("<h1>Acceso denegado. Solo superadministradores.</h1>", status=403)
        
    admins = AdministradorPortal.objects.all().order_by('email')
    return render(request, 'motor_firmas/admin_administradores.html', {
        'admin_email': admin_email,
        'admins': admins
    })

'''
content += new_views

# 5. Add to admin_api
old_api_start = '''@csrf_exempt
def admin_api(request, accion):
    if not request.session.get('admin_email'): return JsonResponse({"error": "No autorizado"}, status=403)
    if request.method == 'POST':
        data = json.loads(request.body)'''

new_api_start = '''@csrf_exempt
def admin_api(request, accion):
    if not request.session.get('admin_email'): return JsonResponse({"error": "No autorizado"}, status=403)
    admin_actual = AdministradorPortal.objects.filter(email=request.session.get('admin_email')).first()
    
    if request.method == 'POST':
        data = json.loads(request.body)
        
        if accion == 'actualizar_usuario':
            u_id = data.get('id')
            usr = DirectorioFirmas.objects.filter(id=u_id).first()
            if usr:
                if not admin_actual.es_superadmin and usr.tecnico_asignado != admin_actual.email:
                    return JsonResponse({"error": "No tienes permiso."}, status=403)
                if admin_actual.es_superadmin and 'tecnico_asignado' in data:
                    usr.tecnico_asignado = data.get('tecnico_asignado')
                usr.permisos_portal = data.get('permisos', [])
                usr.save()
                return JsonResponse({"status": "success", "msg": "Usuario actualizado."})
            return JsonResponse({"error": "Usuario no encontrado."}, status=404)
            
        elif accion == 'eliminar_usuario':
            u_id = data.get('id')
            usr = DirectorioFirmas.objects.filter(id=u_id).first()
            if usr:
                if not admin_actual.es_superadmin and usr.tecnico_asignado != admin_actual.email:
                    return JsonResponse({"error": "No tienes permiso."}, status=403)
                usr.delete()
                return JsonResponse({"status": "success", "msg": "Usuario eliminado."})
            return JsonResponse({"error": "Usuario no encontrado."}, status=404)
            
        elif accion == 'actualizar_admin':
            if not admin_actual.es_superadmin: return JsonResponse({"error": "Solo superadmin."}, status=403)
            a_id = data.get('id')
            a_obj = AdministradorPortal.objects.filter(id=a_id).first()
            if a_obj:
                a_obj.es_superadmin = data.get('es_superadmin', False)
                a_obj.save()
                return JsonResponse({"status": "success"})
            return JsonResponse({"error": "No encontrado."}, status=404)
            
        elif accion == 'eliminar_admin':
            if not admin_actual.es_superadmin: return JsonResponse({"error": "Solo superadmin."}, status=403)
            a_id = data.get('id')
            a_obj = AdministradorPortal.objects.filter(id=a_id).first()
            if a_obj:
                if a_obj.email == "pjimenezb@raloy.com.mx": return JsonResponse({"error": "No puedes eliminar al admin maestro."})
                a_obj.delete()
                return JsonResponse({"status": "success"})
            return JsonResponse({"error": "No encontrado."}, status=404)
'''

content = content.replace(old_api_start, new_api_start)

with open('motor_firmas/views.py', 'w') as f:
    f.write(content)

print("Patch applied to views.py")

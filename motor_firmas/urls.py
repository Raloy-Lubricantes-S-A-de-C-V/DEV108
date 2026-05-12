from django.urls import path
from . import views

urlpatterns = [
    # RUTAS API N8N Y FIRMA NORMAL
    path('api/recibir-documento/', views.recibir_documento_n8n, name='recibir_documento'),
    path('firmar/<uuid:token>/', views.vista_firma_ui, name='vista_firma_old'),
    path('firmar/<uuid:token>/<str:firmante_token>/', views.vista_firma_ui, name='vista_firma'),
    path('api/procesar/<uuid:token>/', views.procesar_firma, name='procesar_firma_old'),
    path('api/procesar/<uuid:token>/<str:firmante_token>/', views.procesar_firma, name='procesar_firma'),
    path('trazabilidad/<uuid:token>/', views.vista_trazabilidad, name='vista_trazabilidad'),

    # RUTAS DE BANCO DE FIRMAS
    path('registro-firmas/', views.registro_firmas, name='registro_firmas'),
    path('api/solicitar-recuperacion/', views.solicitar_recuperacion, name='solicitar_recuperacion'),
    path('recuperar-pin/<uuid:token>/', views.resetear_pin, name='resetear_pin'),

    # RUTAS DEL PORTAL
    path('portal/', views.portal_login, name='portal_login'),
    path('api/solicitar-otp/', views.solicitar_otp, name='solicitar_otp'),
    path('portal/dashboard/', views.portal_dashboard, name='portal_dashboard'),
    path('portal/logout/', views.portal_logout, name='portal_logout'),

    # RUTAS DE PLANTILLAS
    path('portal/plantillas/', views.portal_plantillas, name='portal_plantillas'),
    path('portal/usar-plantilla/<str:plantilla_id>/', views.portal_usar_plantilla, name='portal_usar_plantilla'),

    # === RUTAS DE PDFS LIBRES (DRAG & DROP) ===
    path('portal/mis-pdfs/', views.portal_pdfs_usuario, name='portal_pdfs_usuario'),
    path('portal/subir-pdf/', views.portal_subir_pdf, name='portal_subir_pdf'),
    path('api/subir-pdf-usuario/', views.subir_pdf_usuario, name='subir_pdf_usuario'),
    path('api/eliminar-pdf-usuario/<str:pdf_id>/', views.eliminar_pdf_usuario, name='eliminar_pdf_usuario'),
    path('portal/configurar-pdf/<uuid:pdf_id>/', views.portal_configurar_pdf, name='portal_configurar_pdf'),
    path('api/iniciar-firma-libre/', views.iniciar_firma_libre, name='iniciar_firma_libre'),

    # RUTAS DEL PORTAL (ADMINISTRADORES)
    path('admin-portal/', views.admin_login, name='admin_login'),
    path('admin-portal/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-portal/crear-plantilla/', views.admin_crear_plantilla, name='admin_crear_plantilla'),
    path('admin-portal/editar-plantilla/<str:plantilla_id>/', views.admin_editar_plantilla,
         name='admin_editar_plantilla'),
    path('admin-portal/usuarios/', views.admin_usuarios, name='admin_usuarios'),
    path('admin-portal/usuarios/<int:usuario_id>/', views.admin_usuarios_detalle, name='admin_usuarios_detalle'),
    path('admin-portal/administradores/', views.admin_administradores, name='admin_administradores'),
    path('admin-portal/logout/', views.admin_logout, name='admin_logout'),
    path('api/admin-action/<str:accion>/', views.admin_api, name='admin_api'),
]
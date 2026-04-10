from django.urls import path
from . import views

urlpatterns = [
    path('api/recibir-documento/', views.recibir_documento_n8n, name='recibir_documento'),
    path('firmar/<uuid:token>/', views.vista_firma_ui, name='vista_firma'),
    path('api/procesar/<uuid:token>/', views.procesar_firma, name='procesar_firma'),
    path('trazabilidad/<uuid:token>/', views.vista_trazabilidad, name='vista_trazabilidad'),

    path('registro-firmas/', views.registro_firmas, name='registro_firmas'),
    path('api/solicitar-recuperacion/', views.solicitar_recuperacion, name='solicitar_recuperacion'),
    path('recuperar-pin/<uuid:token>/', views.resetear_pin, name='resetear_pin'),

    path('portal/', views.portal_login, name='portal_login'),
    path('api/solicitar-otp/', views.solicitar_otp, name='solicitar_otp'),
    path('portal/dashboard/', views.portal_dashboard, name='portal_dashboard'),
    path('portal/logout/', views.portal_logout, name='portal_logout'),

    # NUEVAS RUTAS USUARIO (Plantillas)
    path('portal/plantillas/', views.portal_plantillas, name='portal_plantillas'),
    path('portal/usar-plantilla/<int:plantilla_id>/', views.portal_usar_plantilla, name='portal_usar_plantilla'),

    path('admin-portal/', views.admin_login, name='admin_login'),
    path('admin-portal/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-portal/crear-plantilla/', views.admin_crear_plantilla, name='admin_crear_plantilla'),
    path('admin-portal/logout/', views.admin_logout, name='admin_logout'),
    path('api/admin-action/<str:accion>/', views.admin_api, name='admin_api'),
]
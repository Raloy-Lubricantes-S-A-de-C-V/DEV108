from django.urls import path
from . import views

urlpatterns = [
    path('api/recibir-documento/', views.recibir_documento_n8n, name='recibir_documento'),
    path('firmar/<uuid:token>/', views.vista_firma_ui, name='vista_firma'),
    path('api/procesar/<uuid:token>/', views.procesar_firma, name='procesar_firma'),
    path('trazabilidad/<uuid:token>/', views.vista_trazabilidad, name='vista_trazabilidad'),

    # NUEVAS RUTAS DE BANCO DE FIRMAS
    path('registro-firmas/', views.registro_firmas, name='registro_firmas'),
    path('api/solicitar-recuperacion/', views.solicitar_recuperacion, name='solicitar_recuperacion'),
    path('recuperar-pin/<uuid:token>/', views.resetear_pin, name='resetear_pin'),
]
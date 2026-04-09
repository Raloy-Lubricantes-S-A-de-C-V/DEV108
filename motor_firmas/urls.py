from django.urls import path
from . import views

urlpatterns = [
    path('api/recibir-documento/', views.recibir_documento_n8n, name='recibir_documento'),
    path('firmar/<uuid:token>/', views.vista_firma_ui, name='vista_firma'),
    path('api/procesar/<uuid:token>/', views.procesar_firma, name='procesar_firma'),
    # NUEVA RUTA
    path('trazabilidad/<uuid:token>/', views.vista_trazabilidad, name='vista_trazabilidad'),
]
from django.urls import path
from . import views

urlpatterns = [
    # Endpoint consumido por n8n al inicio del flujo
    path('api/recibir-documento/', views.recibir_documento_n8n, name='recibir_documento'),

    # URL pública enviada por correo al firmante
    path('firmar/<uuid:token>/', views.vista_firma_ui, name='vista_firma'),

    # Endpoint interno para procesar el dibujo del canvas
    path('api/procesar/<uuid:token>/', views.procesar_firma, name='procesar_firma'),
]

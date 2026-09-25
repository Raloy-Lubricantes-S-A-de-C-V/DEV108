"""signature_project URL Configuration"""

from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', include('motor_firmas.urls')),
]

# ESTA ES LA MAGIA: Le dice a Django cómo servir los archivos de la carpeta /media/
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
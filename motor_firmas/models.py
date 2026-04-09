from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
from datetime import timedelta
import uuid


# Create your models here.

class ProcesoFirma(models.Model):
    """
    Controla el estado del documento y la secuencia de quién debe firmar.
    """
    reference_id = models.CharField(max_length=100, unique=True)
    token_acceso = models.UUIDField(default=uuid.uuid4, editable=False)  # Token único para la URL pública
    pdf_path = models.CharField(max_length=500)  # Ruta local del archivo PDF
    firmantes = models.JSONField()  # Lista de dicts: [{'nombre': 'Juan', 'email': 'j@j.com'}, ...]
    indice_actual = models.IntegerField(default=1)  # Empieza en 1 (Para {{FIRMA_1}})
    status = models.CharField(max_length=50, default='PROCESSING')  # PROCESSING, COMPLETED

    view_info = models.CharField(max_length=20, default='file')  # 'file' o 'summary'
    summary_data = models.JSONField(null=True, blank=True)  # Guardará el JSON con 'contexto' e 'intencion'

    # --- NUEVOS CAMPOS PARA TRAZABILIDAD ---
    owner_email = models.CharField(max_length=200, null=True, blank=True)  # Correo del dueño
    created_at = models.DateTimeField(default=timezone.now)  # Fecha de envío original

    def __str__(self):
        return f"{self.reference_id} - {self.status}"


class DirectorioFirmas(models.Model):
    """
    Banco de firmas de colaboradores internos de Raloy.
    """
    nombre = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    puesto = models.CharField(max_length=200)
    iniciales = models.CharField(max_length=10)
    firma_base64 = models.TextField()  # El dibujo en base64
    pin_hash = models.CharField(max_length=255)  # PIN ENCRIPTADO (Nadie lo puede ver)

    # Legal y auditoría
    acepto_terminos = models.BooleanField(default=False)
    fecha_registro = models.DateTimeField(default=timezone.now)

    # Recuperación de PIN
    reset_token = models.UUIDField(null=True, blank=True)
    reset_token_expires = models.DateTimeField(null=True, blank=True)

    def set_pin(self, raw_pin):
        """Encripta el PIN antes de guardarlo"""
        self.pin_hash = make_password(raw_pin)

    def check_pin(self, raw_pin):
        """Comprueba si el PIN ingresado coincide matemáticamente con el hash"""
        return check_password(raw_pin, self.pin_hash)

    def generar_token_recuperacion(self):
        """Genera un token de 1 hora para recuperar el PIN"""
        self.reset_token = uuid.uuid4()
        self.reset_token_expires = timezone.now() + timedelta(hours=1)
        self.save()

    def __str__(self):
        return f"{self.nombre} ({self.email})"
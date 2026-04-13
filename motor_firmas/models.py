from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
from datetime import timedelta
import uuid
import random


class ProcesoFirma(models.Model):
    reference_id = models.CharField(max_length=100, unique=True)
    token_acceso = models.UUIDField(default=uuid.uuid4, editable=False)
    pdf_path = models.CharField(max_length=500)
    firmantes = models.JSONField()
    indice_actual = models.IntegerField(default=1)
    status = models.CharField(max_length=50, default='PROCESSING')

    view_info = models.CharField(max_length=20, default='file')
    summary_data = models.JSONField(null=True, blank=True)

    dir_drive = models.CharField(max_length=200, null=True, blank=True)
    exec_mode = models.CharField(max_length=20, default='normal')
    document_variables = models.JSONField(default=dict, blank=True)
    valores_capturados = models.JSONField(default=dict, blank=True)

    owner_email = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.reference_id} - {self.status}"


class PlantillaFormulario(models.Model):
    nombre = models.CharField(max_length=200)
    doc_id = models.CharField(max_length=200)
    owner_email = models.CharField(max_length=200)

    drive_folder_id = models.CharField(max_length=200)
    carpeta_firmados_id = models.CharField(max_length=200, blank=True, null=True)

    view_info = models.CharField(max_length=50, default='file')
    formato_folio = models.CharField(max_length=100, blank=True, null=True, default='')

    contexto = models.TextField(blank=True, null=True)
    intencion = models.TextField(blank=True, null=True)
    variables = models.JSONField(default=list)
    firmantes_config = models.JSONField(default=list)
    usuarios_permitidos = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now)


class DirectorioFirmas(models.Model):
    nombre = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    puesto = models.CharField(max_length=200)
    iniciales = models.CharField(max_length=10)
    firma_base64 = models.TextField()
    pin_hash = models.CharField(max_length=255)
    acepto_terminos = models.BooleanField(default=False)
    fecha_registro = models.DateTimeField(default=timezone.now)
    reset_token = models.UUIDField(null=True, blank=True)
    reset_token_expires = models.DateTimeField(null=True, blank=True)

    def set_pin(self, raw_pin):
        self.pin_hash = make_password(raw_pin)

    def check_pin(self, raw_pin):
        return check_password(raw_pin, self.pin_hash)

    def generar_token_recuperacion(self):
        self.reset_token = uuid.uuid4()
        self.reset_token_expires = timezone.now() + timedelta(hours=1)
        self.save()


class OTPLogin(models.Model):
    email = models.EmailField(unique=True)
    otp_code = models.CharField(max_length=6)
    expires_at = models.DateTimeField()

    def generar_otp(self):
        self.otp_code = str(random.randint(100000, 999999))
        self.expires_at = timezone.now() + timedelta(minutes=15)
        self.save()

    def es_valido(self, code_ingresado):
        return self.otp_code == code_ingresado and timezone.now() <= self.expires_at


class AdministradorPortal(models.Model):
    email = models.EmailField(unique=True)
    configuracion_dashboard = models.JSONField(default=dict, blank=True)


class CarpetaDominio(models.Model):
    dominio = models.CharField(max_length=100, unique=True)
    drive_folder_id = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)


# NUEVO MODELO PARA PDFS DE USUARIOS
class DocumentoPDFUsuario(models.Model):
    nombre = models.CharField(max_length=200)
    drive_file_id = models.CharField(max_length=200)
    owner_email = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)
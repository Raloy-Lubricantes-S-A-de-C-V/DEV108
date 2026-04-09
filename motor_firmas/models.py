from django.contrib.auth.hashers import make_password, check_password
from datetime import timedelta


# ... (Mantén tu clase ProcesoFirma intacta arriba) ...

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
        self.reset_token = uuid.uuid4()
        self.reset_token_expires = timezone.now() + timedelta(hours=1)  # Expira en 1 hora
        self.save()

    def __str__(self):
        return f"{self.nombre} ({self.email})"
from django.db import models
import uuid
# Create your models here.



class ProcesoFirma(models.Model):
    """
    Controla el estado del documento y la secuencia de quién debe firmar.
    """
    reference_id = models.CharField(max_length=100, unique=True)
    token_acceso = models.UUIDField(default=uuid.uuid4, editable=False) # Token único para la URL pública
    pdf_path = models.CharField(max_length=500) # Ruta local del archivo PDF
    firmantes = models.JSONField() # Lista de dicts: [{'nombre': 'Juan', 'email': 'j@j.com'}, ...]
    indice_actual = models.IntegerField(default=1) # Empieza en 1 (Para {{FIRMA_1}})
    status = models.CharField(max_length=50, default='PROCESSING') # PROCESSING, COMPLETED

    def __str__(self):
        return f"{self.reference_id} - {self.status}"

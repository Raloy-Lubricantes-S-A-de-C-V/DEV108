import os, django, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "signature_project.settings")
django.setup()
from motor_firmas.models import ProcesoFirma

p = ProcesoFirma.objects.filter(exec_mode='form').last()
if p:
    print("Reference ID:", p.reference_id)
    print("Summary Data:", json.dumps(p.summary_data, indent=2))
    print("Document Variables:", json.dumps(p.document_variables, indent=2))
else:
    # Intenta buscar el penúltimo o alguno que tenga content-option
    ps = ProcesoFirma.objects.exclude(summary_data__isnull=True).order_by('-created_at')[:5]
    for p in ps:
        print("Ref:", p.reference_id, "Summary:", json.dumps(p.summary_data, indent=2))

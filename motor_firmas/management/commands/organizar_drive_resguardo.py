import requests

from django.core.management.base import BaseCommand

from motor_firmas.models import PlantillaFormulario, ProcesoFirma
from motor_firmas.views import (
    DRIVE_PDFS_FOLDER_NAME,
    DRIVE_STORAGE_POLICY,
    N8N_WEBHOOK_PREPARAR_DIR,
    _drive_pdfs_folder_id,
    _drive_root_folder_id,
    _drive_storage_payload,
    _mongo_find,
    _mongo_update_document,
    _preparar_estructura_drive_plantilla,
)


class Command(BaseCommand):
    help = "Reorganiza solo plantillas: Docs de plantilla a Formatos y PDFs generados desde plantilla a PDFs. No modifica libres ni FIRMX."

    def add_arguments(self, parser):
        parser.add_argument("--root-folder-id", default="", help="Carpeta raiz Drive. Default: settings.DRIVE_ARCHIVE_ROOT_FOLDER_ID.")
        parser.add_argument("--pdfs-folder-id", default="", help="ID conocido de PDFs. Si no se indica, usa settings.DRIVE_PDFS_FOLDER_ID o la raiz.")
        parser.add_argument("--dry-run", action="store_true", help="Muestra acciones sin actualizar Mongo.")
        parser.add_argument("--skip-n8n-global", action="store_true", help="No solicita a N8N mover archivos de plantillas en Drive.")

    def handle(self, *args, **options):
        root_folder_id = options["root_folder_id"] or _drive_root_folder_id()
        pdfs_folder_id = options["pdfs_folder_id"] or _drive_pdfs_folder_id()
        dry_run = bool(options["dry_run"])

        self.stdout.write(f"Raiz Drive: {root_folder_id}")
        self.stdout.write(f"PDFs fallback: {pdfs_folder_id}")

        if not options["skip_n8n_global"]:
            self._solicitar_reorganizacion_global(root_folder_id, dry_run)

        plantillas_actualizadas = 0
        for plantilla in _mongo_find(PlantillaFormulario, {}):
            doc_id = getattr(plantilla, "doc_id", "")
            if not doc_id:
                continue
            self.stdout.write(f"Plantilla {getattr(plantilla, 'nombre', '')}: {doc_id}")
            if dry_run:
                continue

            storage = _preparar_estructura_drive_plantilla(doc_id, root_folder_id)
            _mongo_update_document(PlantillaFormulario, plantilla, {
                "drive_folder_id": storage["formatos_folder_id"],
                "carpeta_firmados_id": storage["pdfs_folder_id"],
                "drive_root_folder_id": storage["root_folder_id"],
                "drive_storage_policy": DRIVE_STORAGE_POLICY,
            })
            pdfs_folder_id = storage["pdfs_folder_id"] or pdfs_folder_id
            plantillas_actualizadas += 1

        procesos_actualizados = 0
        pdfs_movidos = 0
        for proceso in _mongo_find(ProcesoFirma, {'exec_mode': 'form'}):
            summary_data = getattr(proceso, "summary_data", {}) or {}
            if summary_data.get("firmx_id"):
                continue
            pdf_drive_id = self._pdf_drive_id(summary_data)
            if dry_run:
                extra = f" y moveria PDF {pdf_drive_id}" if pdf_drive_id else " sin PDF Drive ID para mover"
                self.stdout.write(f"DRY-RUN actualizaria proceso {getattr(proceso, 'reference_id', '')} -> {pdfs_folder_id}{extra}")
                continue
            if pdf_drive_id:
                moved_folder_id = self._mover_pdf_plantilla(pdf_drive_id, root_folder_id)
                if moved_folder_id:
                    pdfs_folder_id = moved_folder_id
                    pdfs_movidos += 1
            _mongo_update_document(ProcesoFirma, proceso, {"dir_drive": pdfs_folder_id})
            procesos_actualizados += 1

        self.stdout.write(self.style.SUCCESS(
            f"Plantillas actualizadas: {plantillas_actualizadas}. Procesos de plantilla actualizados: {procesos_actualizados}. PDFs movidos: {pdfs_movidos}."
        ))

    def _solicitar_reorganizacion_global(self, root_folder_id, dry_run):
        payload = {
            **_drive_storage_payload(),
            "root_folder_id": root_folder_id,
            "accion": "reorganizar_resguardo_plantillas",
            "scope": "plantillas",
            "move_template_docs_to": "Formatos",
            "move_template_pdfs_to": DRIVE_PDFS_FOLDER_NAME,
            "keep_free_pdfs_in_domain_folders": True,
            "exclude_firmx": True,
            "dry_run": dry_run,
        }
        try:
            response = requests.post(N8N_WEBHOOK_PREPARAR_DIR, json=payload, timeout=60)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"No se pudo contactar N8N para reorganizacion global: {exc}"))
            return

        if not 200 <= response.status_code < 300:
            self.stdout.write(self.style.WARNING(
                f"N8N no confirmo reorganizacion global ({response.status_code}): {response.text}"
            ))
            return
        self.stdout.write("N8N recibio la solicitud de reorganizacion global.")

    def _pdf_drive_id(self, summary_data):
        return (
            summary_data.get("drive_file_id")
            or summary_data.get("pdf_file_id")
            or summary_data.get("drive_final_file_id")
            or summary_data.get("file_id")
            or ""
        )

    def _mover_pdf_plantilla(self, pdf_drive_id, root_folder_id):
        payload = {
            **_drive_storage_payload(),
            "root_folder_id": root_folder_id,
            "pdf_file_id": pdf_drive_id,
            "move_template_pdfs_to": DRIVE_PDFS_FOLDER_NAME,
            "keep_free_pdfs_in_domain_folders": True,
            "exclude_firmx": True,
        }
        try:
            response = requests.post(N8N_WEBHOOK_PREPARAR_DIR, json=payload, timeout=60)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"No se pudo mover PDF {pdf_drive_id}: {exc}"))
            return ""

        if not 200 <= response.status_code < 300:
            self.stdout.write(self.style.WARNING(
                f"N8N no movio PDF {pdf_drive_id} ({response.status_code}): {response.text}"
            ))
            return ""
        try:
            data = response.json()
        except ValueError:
            return ""
        if isinstance(data, list):
            data = data[0] if data else {}
        return data.get("pdfs_folder_id", "") if isinstance(data, dict) else ""

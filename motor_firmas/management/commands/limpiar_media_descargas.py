import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from motor_firmas.models import DocumentoPDFUsuario, ProcesoFirma
from motor_firmas.views import _mongo_find


class Command(BaseCommand):
    help = "Elimina descargas temporales de MEDIA_ROOT mas antiguas que el limite indicado."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=float, default=1.0, help="Antiguedad minima en dias para borrar. Default: 1.")
        parser.add_argument("--dry-run", action="store_true", help="Muestra lo que se borraria sin eliminar archivos.")
        parser.add_argument("--all-media", action="store_true", help="Limpia todo MEDIA_ROOT en vez de solo media/descargas.")

    def handle(self, *args, **options):
        media_root = os.path.abspath(settings.MEDIA_ROOT)
        target_root = media_root if options["all_media"] else os.path.join(media_root, "descargas")
        cutoff = time.time() - (float(options["days"]) * 24 * 60 * 60)
        dry_run = bool(options["dry_run"])
        protected = self._protected_paths(media_root)
        deleted = 0
        skipped = 0

        if not os.path.isdir(target_root):
            self.stdout.write(self.style.WARNING(f"Directorio no existe: {target_root}"))
            return

        for root, dirs, files in os.walk(target_root, topdown=False):
            rel_root = os.path.relpath(root, media_root).replace(os.sep, "/")
            if rel_root == "branding" or rel_root.startswith("branding/"):
                continue

            for filename in files:
                path = os.path.abspath(os.path.join(root, filename))
                if path in protected:
                    skipped += 1
                    continue
                try:
                    if os.path.getmtime(path) > cutoff:
                        skipped += 1
                        continue
                except OSError:
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(f"DRY-RUN borraria: {path}")
                else:
                    try:
                        os.remove(path)
                        deleted += 1
                    except OSError as exc:
                        skipped += 1
                        self.stdout.write(self.style.WARNING(f"No se pudo borrar {path}: {exc}"))

            if root != target_root:
                try:
                    if not os.listdir(root):
                        if dry_run:
                            self.stdout.write(f"DRY-RUN removeria carpeta vacia: {root}")
                        else:
                            os.rmdir(root)
                except OSError:
                    pass

        action = "Detectados" if dry_run else "Borrados"
        self.stdout.write(self.style.SUCCESS(f"{action}: {deleted}. Omitidos/protegidos: {skipped}."))

    def _protected_paths(self, media_root):
        protected = set()

        for proceso in _mongo_find(ProcesoFirma, {}):
            pdf_path = str(getattr(proceso, "pdf_path", "") or "")
            if pdf_path:
                abs_pdf_path = os.path.abspath(pdf_path)
                rel_path = os.path.relpath(abs_pdf_path, media_root).replace(os.sep, "/")
                if not rel_path.startswith("descargas/"):
                    protected.add(abs_pdf_path)

        for documento in _mongo_find(DocumentoPDFUsuario, {'deleted': {'$ne': True}}):
            rel_path = str(getattr(documento, "archivo_local", "") or "").replace("\\", "/")
            if rel_path:
                if not rel_path.startswith("descargas/"):
                    protected.add(os.path.abspath(os.path.join(media_root, rel_path)))

        return protected

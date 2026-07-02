import os
import time

from django.conf import settings

from motor_firmas.models import DocumentoPDFUsuario, ProcesoFirma
from motor_firmas.views import _mongo_find


def _write(stdout, message):
    if stdout:
        stdout.write(message)


def _protected_paths(media_root):
    protected = set()

    for proceso in _mongo_find(ProcesoFirma, {}):
        pdf_path = str(getattr(proceso, "pdf_path", "") or "")
        if pdf_path:
            abs_pdf_path = os.path.abspath(pdf_path)
            try:
                rel_path = os.path.relpath(abs_pdf_path, media_root).replace(os.sep, "/")
            except ValueError:
                continue
            if not rel_path.startswith("descargas/"):
                protected.add(abs_pdf_path)

    for documento in _mongo_find(DocumentoPDFUsuario, {'deleted': {'$ne': True}}):
        rel_path = str(getattr(documento, "archivo_local", "") or "").replace("\\", "/")
        if rel_path and not rel_path.startswith("descargas/"):
            protected.add(os.path.abspath(os.path.join(media_root, rel_path)))

    return protected


def limpiar_media_descargada(days=1.0, dry_run=False, all_media=False, stdout=None):
    media_root = os.path.abspath(settings.MEDIA_ROOT)
    target_root = media_root if all_media else os.path.join(media_root, "descargas")
    cutoff = time.time() - (float(days) * 24 * 60 * 60)
    protected = _protected_paths(media_root)
    deleted = 0
    skipped = 0

    if not os.path.isdir(target_root):
        _write(stdout, f"Directorio no existe: {target_root}")
        return {"deleted": deleted, "skipped": skipped, "target_root": target_root}

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
                _write(stdout, f"DRY-RUN borraria: {path}")
            else:
                try:
                    os.remove(path)
                    deleted += 1
                except OSError as exc:
                    skipped += 1
                    _write(stdout, f"No se pudo borrar {path}: {exc}")

        if root != target_root:
            try:
                if not os.listdir(root):
                    if dry_run:
                        _write(stdout, f"DRY-RUN removeria carpeta vacia: {root}")
                    else:
                        os.rmdir(root)
            except OSError:
                pass

    return {"deleted": deleted, "skipped": skipped, "target_root": target_root}

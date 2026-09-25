import os
import time

from django.conf import settings

from motor_firmas.cleanup import limpiar_media_descargada
from motor_firmas.n8n_monitor import reset_current_request, set_current_request


class N8NMonitorContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current_request(request)
        try:
            return self.get_response(request)
        finally:
            reset_current_request(token)


class MediaCleanupCronMiddleware:
    _running = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._maybe_cleanup()
        return self.get_response(request)

    def _maybe_cleanup(self):
        interval = int(getattr(settings, 'MEDIA_CLEANUP_INTERVAL_SECONDS', 6 * 60 * 60))
        if interval <= 0 or MediaCleanupCronMiddleware._running:
            return

        media_root = os.path.abspath(settings.MEDIA_ROOT)
        state_path = os.path.join(media_root, '.limpiar_media_descargas.last')
        now = time.time()

        try:
            os.makedirs(media_root, exist_ok=True)
            if os.path.exists(state_path):
                with open(state_path, 'r', encoding='utf-8') as state_file:
                    last_run = float((state_file.read() or '0').strip() or 0)
                if now - last_run < interval:
                    return
            with open(state_path, 'w', encoding='utf-8') as state_file:
                state_file.write(str(now))
        except (OSError, ValueError) as exc:
            print(f"No se pudo evaluar cron interno de limpieza: {exc}")
            return

        MediaCleanupCronMiddleware._running = True
        try:
            limpiar_media_descargada(
                days=getattr(settings, 'MEDIA_TEMP_MAX_AGE_DAYS', 1.0),
                dry_run=False,
                all_media=False,
            )
        except Exception as exc:
            print(f"Error en cron interno limpiar_media_descargas: {exc}")
        finally:
            MediaCleanupCronMiddleware._running = False

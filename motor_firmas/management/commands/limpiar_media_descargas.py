from django.core.management.base import BaseCommand

from motor_firmas.cleanup import limpiar_media_descargada


class Command(BaseCommand):
    help = "Elimina descargas temporales de MEDIA_ROOT mas antiguas que el limite indicado."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=float, default=1.0, help="Antiguedad minima en dias para borrar. Default: 1.")
        parser.add_argument("--dry-run", action="store_true", help="Muestra lo que se borraria sin eliminar archivos.")
        parser.add_argument("--all-media", action="store_true", help="Limpia todo MEDIA_ROOT en vez de solo media/descargas.")

    def handle(self, *args, **options):
        result = limpiar_media_descargada(
            days=options["days"],
            dry_run=options["dry_run"],
            all_media=options["all_media"],
            stdout=self.stdout,
        )
        action = "Detectados" if options["dry_run"] else "Borrados"
        self.stdout.write(self.style.SUCCESS(
            f"{action}: {result['deleted']}. Omitidos/protegidos: {result['skipped']}."
        ))

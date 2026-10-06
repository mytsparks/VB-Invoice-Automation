from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from intake.services import ingest_folder


class Command(BaseCommand):
    help = "Register invoice files from data/inbox in the database. Original files are never changed."

    def add_arguments(self, parser):
        parser.add_argument("--folder", help="Folder to read instead of data/inbox.")

    def handle(self, *args, **options):
        folder = Path(options["folder"]) if options["folder"] else settings.APP.data_dir / "inbox"
        if not folder.is_dir():
            raise CommandError(f"Folder not found: {folder}")
        self.stdout.write(f"Ingesting {folder}")
        summary = ingest_folder(folder, out=self.stdout.write)
        self.stdout.write(
            f"Done. {summary.added} added, {summary.duplicates} duplicates skipped, "
            f"{summary.unsupported} unsupported."
        )

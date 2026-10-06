from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from extraction.management.commands.extract import add_extract_arguments, run_extraction
from intake.services import ingest_folder


class Command(BaseCommand):
    help = "Ingest and extract in one step. Matching is added in a later phase."

    def add_arguments(self, parser):
        add_extract_arguments(parser)
        parser.add_argument("--folder", help="Folder to read instead of data/inbox.")

    def handle(self, *args, **options):
        folder = Path(options["folder"]) if options["folder"] else settings.APP.data_dir / "inbox"
        if not folder.is_dir():
            raise CommandError(f"Folder not found: {folder}")
        if options["dry_run"]:
            self.stdout.write("Dry run still registers files in the database, which is free and local.")
        summary = ingest_folder(folder, out=self.stdout.write)
        self.stdout.write(f"Ingest: {summary.added} added, {summary.duplicates} duplicates, {summary.unsupported} unsupported.")
        run_extraction(self, options, processing_command="run")

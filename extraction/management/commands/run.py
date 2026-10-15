from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from extraction.management.commands.extract import add_extract_arguments, run_extraction
from intake.services import ingest_folder


class Command(BaseCommand):
    help = "Ingest, extract and match in one step. Add --process to also send ready invoices to the TMS."

    def add_arguments(self, parser):
        add_extract_arguments(parser)
        parser.add_argument("--folder", help="Folder to read instead of data/inbox.")
        parser.add_argument("--process", action="store_true", help="After matching, send ready invoices to the TMS (asks before each unless --yes).")
        parser.add_argument("--yes", action="store_true", help="With --process, do not ask before each ready invoice.")
        parser.add_argument("--no-input", action="store_true", help="Never ask questions.")

    def handle(self, *args, **options):
        folder = Path(options["folder"]) if options["folder"] else settings.APP.data_dir / "inbox"
        if not folder.is_dir():
            raise CommandError(f"Folder not found: {folder}")
        if options["dry_run"]:
            self.stdout.write("Dry run still registers files in the database, which is free and local.")
        summary = ingest_folder(folder, out=self.stdout.write)
        self.stdout.write(f"Ingest: {summary.added} added, {summary.duplicates} duplicates, {summary.unsupported} unsupported.")
        run_extraction(self, options, processing_command="run")
        if options["dry_run"]:
            self.stdout.write("Dry run, so matching and processing are skipped.")
            return
        self.stdout.write("")
        call_command("match", file=options["file"], no_input=options["no_input"], stdout=self.stdout)
        if options["process"]:
            self.stdout.write("")
            call_command("process", file=options["file"], yes=options["yes"], no_input=options["no_input"], stdout=self.stdout)

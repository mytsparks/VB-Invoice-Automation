from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.checks import FAIL, run_checks


class Command(BaseCommand):
    help = "Validate settings and guardrails."

    def add_arguments(self, parser):
        parser.add_argument(
            "--require-llm",
            action="store_true",
            help="Treat a missing Claude API key as a failure.",
        )

    def handle(self, *args, **options):
        results = run_checks(settings.APP, settings.BASE_DIR, require_llm=options["require_llm"])
        for level, message in results:
            self.stdout.write(f"[{level.upper():4}] {message}")
        if any(level == FAIL for level, _ in results):
            raise CommandError("Configuration check failed.")
        self.stdout.write(self.style.SUCCESS("Configuration check passed."))

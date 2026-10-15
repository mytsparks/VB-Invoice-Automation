from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tms.base import TmsError
from tms.factory import get_tms_client


class Command(BaseCommand):
    help = "Test connectivity to the configured TMS. For the simulated TMS this loads and checks the fixture files."

    def handle(self, *args, **options):
        try:
            client = get_tms_client(settings.APP)
            description = client.check()
        except (ValueError, TmsError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"[{client.mode}] {description}."))
        for directory in settings.APP.tms_fixture_dirs:
            self.stdout.write(f"  fixtures: {directory} ({'found' if directory.is_dir() else 'not found'})")

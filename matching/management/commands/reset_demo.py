from django.core.management.base import BaseCommand

from matching.models import Flag, MatchResult, ShipmentCostLine, ShipmentRecord
from processing.models import TmsWrite


class Command(BaseCommand):
    help = "Clear match results and simulated TMS writes so the demo can be run again. Extractions are kept."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")

    def handle(self, *args, **options):
        counts = {
            "match results": MatchResult.objects.count(),
            "TMS write records": TmsWrite.objects.count(),
        }
        if not options["yes"]:
            answer = input(f"This deletes {counts['match results']} match result(s) and {counts['TMS write records']} TMS write record(s). Extractions are kept. Continue? [y/N] ")
            if answer.strip().lower() != "y":
                self.stdout.write("Nothing changed.")
                return
        TmsWrite.objects.all().delete()
        Flag.objects.all().delete()
        MatchResult.objects.all().delete()
        ShipmentCostLine.objects.all().delete()
        ShipmentRecord.objects.all().delete()
        self.stdout.write("Cleared match results, flags, shipment snapshots and TMS write records.")

from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.ui import Prompter
from extraction.services import current_invoices
from matching.models import MatchResult
from matching.render import render_match
from matching.services import evaluate, save_match
from processing.models import TmsWrite
from tms.base import TmsError
from tms.factory import get_tms_client


def tms_banner(client) -> str:
    return "SIMULATED TMS" if client.mode == "mock" else "TURVO SANDBOX"


class Command(BaseCommand):
    help = "Compare extracted invoices with shipments in the TMS and decide ready or needs review. Nothing is written to the TMS."

    def add_arguments(self, parser):
        parser.add_argument("--file", help="Only match invoices from files whose name contains this text.")
        parser.add_argument("--rematch", action="store_true", help="Match again even if a result exists.")
        parser.add_argument("--no-input", action="store_true", help="Never ask questions. Suggestions are listed but not applied.")

    def handle(self, *args, **options):
        config = settings.APP
        try:
            client = get_tms_client(config)
            description = client.check()
        except (ValueError, TmsError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"[{tms_banner(client)}] {description}. Matching is read only.")

        invoices = current_invoices().select_related("document")
        if options["file"]:
            invoices = invoices.filter(document__file_name__icontains=options["file"])
        invoices = list(invoices.order_by("pk"))
        if not invoices:
            self.stdout.write("No extracted invoices found. Run extract first.")
            return

        prompter = Prompter(self.stdout.write, interactive=False if options["no_input"] else None)
        counts, flag_counts = Counter(), Counter()
        for invoice in invoices:
            existing = MatchResult.objects.filter(invoice=invoice).first()
            if existing and not options["rematch"]:
                counts["skipped"] += 1
                continue
            if TmsWrite.objects.filter(invoice=invoice, status="success").exists():
                self.stdout.write(f"Invoice {invoice.invoice_number}: already processed to the TMS, not matched again.")
                counts["skipped"] += 1
                continue
            self.stdout.write("-" * 78)
            result = evaluate(invoice, client, config)
            if result.shipment is None and result.suggestions:
                result = self.offer_suggestions(invoice, client, config, result, prompter)
            match = save_match(invoice, result)
            render_match(self.stdout.write, self.style, invoice, match)
            counts[match.outcome] += 1
            flag_counts.update(flag.flag_type.name for flag in match.flags.select_related("flag_type"))

        self.stdout.write("=" * 78)
        self.stdout.write(
            f"Matched {sum(v for k, v in counts.items() if k != 'skipped')} invoice(s). "
            f"{counts['ready']} ready, {counts['needs_review']} need review"
            + (f", {counts['skipped']} already matched (use --rematch to redo)." if counts["skipped"] else ".")
        )
        for name, number in flag_counts.most_common():
            self.stdout.write(f"  {number} x {name}")
        if counts["ready"]:
            self.stdout.write("Next: python manage.py process (add --dry-run to preview the writes).")

    def offer_suggestions(self, invoice, client, config, result, prompter):
        label = invoice.shipment_id or "(none)"
        self.stdout.write(self.style.WARNING(f"Invoice {invoice.invoice_number}: shipment {label} was not found."))
        for suggestion in result.suggestions:
            candidate = client.find_shipment(suggestion)
            order = candidate.carrier_orders[0] if candidate and candidate.carrier_orders else None
            detail = f"{order.carrier_name}, total {order.total}" if order else "no carrier order"
            answer = prompter.ask(f"  Use shipment {suggestion} ({detail}) instead?", {"y": "yes", "n": "no"}, default="n")
            if answer == "y":
                return evaluate(invoice, client, config, shipment_id_override=suggestion)
        return result

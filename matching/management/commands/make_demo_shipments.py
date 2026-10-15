"""Builds simulated shipment fixtures from extracted invoices, so the compare and process steps
can be demonstrated before Turvo access exists. The shipments are invented. Each one is built to
give a different result, and every fixture is marked as generated.
"""
import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from extraction.normalize import normalize_shipment_id
from extraction.services import current_invoices

SCENARIOS = {
    "exact": "Matches the invoice. Expected to be ready.",
    "amount": "Shipment cost is lower than the invoice. Expected: amount over tolerance.",
    "accessorial": "Shipment lacks a charge the invoice bills. Expected: unknown accessorial.",
    "reject": "Matches, but the simulated TMS rejects the document upload. Expected: ready, then a failed write.",
    "typo": "Shipment ID differs by one digit from the invoice. Expected: not found, with a suggestion.",
    "currency": "Shipment is in CAD. Expected: currency mismatch.",
    "carrier": "Shipment belongs to a different carrier. Expected: carrier mismatch.",
    "missing": "No shipment is created. Expected: no matching shipment.",
}
DEFAULT_ORDER = ["exact", "amount", "accessorial", "reject", "typo", "currency", "carrier", "missing"]


def invoice_shipment_id(invoice) -> str:
    if invoice.shipment_id:
        return invoice.shipment_id
    for reference in invoice.other_references:
        found = normalize_shipment_id(reference.get("value"))
        if found:
            return found
    return ""


def build_fixture(invoice, shipment_id: str, scenario: str, index: int) -> dict:
    lines = [(line.charge_type or "Freight - flat", line.amount) for line in invoice.lines.all() if line.amount is not None]
    if not lines:
        lines = [("Freight - flat", invoice.total_amount or Decimal("0"))]
    carrier, currency = invoice.carrier_name or "Unknown Carrier", "USD"
    simulation = {"generated": True, "scenario": scenario}
    if scenario == "amount":
        lines = [(name, (amount * Decimal("0.93")).quantize(Decimal("0.01"))) for name, amount in lines]
    elif scenario == "accessorial":
        lines = lines[:-1] if len(lines) > 1 else [("Fuel surcharge", lines[0][1])]
    elif scenario == "currency":
        currency = "CAD"
    elif scenario == "carrier":
        carrier = "Pacific Coast Logistics"
    elif scenario == "reject":
        simulation["reject_attach_document"] = "Document type is not enabled for this account (simulated rejection)."
    if scenario == "typo":
        shipment_id = shipment_id[:-1] + str((int(shipment_id[-1]) + 1) % 10)
    container = next((r["value"] for r in invoice.other_references if "container" in r.get("label", "").lower()), "")
    total = sum((amount for _, amount in lines), Decimal("0"))
    return {
        "Status": "SUCCESS",
        "details": {
            "id": 90000000 + index,
            "customId": shipment_id,
            "status": {"code": {"key": "2101", "value": "Delivered"}},
            "modeInfo": [{"containerNumber": container}] if container else [],
            "carrierOrder": [{
                "id": 70000000 + index,
                "carrier": {"id": 5000 + index, "name": carrier},
                "costs": {
                    "totalAmount": float(total),
                    "transactionCurrency": {"key": "1500", "value": currency},
                    "lineItem": [
                        {"code": {"key": "1600", "value": name}, "qty": 1, "price": float(amount), "amount": float(amount), "id": 100 + i}
                        for i, (name, amount) in enumerate(lines)
                    ],
                },
                "payment": [],
            }],
        },
        "simulation": simulation,
    }


class Command(BaseCommand):
    help = "Create simulated shipment fixtures from extracted invoices, one scenario per invoice."

    def add_arguments(self, parser):
        parser.add_argument("--scenarios", help=f"Comma separated scenarios applied in order. Choices: {', '.join(SCENARIOS)}.")
        parser.add_argument("--output", help="Folder to write to. Default is data/fixtures/shipments.")

    def handle(self, *args, **options):
        order = [s.strip() for s in options["scenarios"].split(",")] if options["scenarios"] else DEFAULT_ORDER
        unknown = [s for s in order if s not in SCENARIOS]
        if unknown:
            raise CommandError(f"Unknown scenario(s): {', '.join(unknown)}.")
        output = Path(options["output"]) if options["output"] else settings.APP.tms_fixture_dirs[0]
        output.mkdir(parents=True, exist_ok=True)
        for path in output.glob("*.json"):
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("simulation", {}).get("generated"):
                    path.unlink()
            except (OSError, ValueError):
                continue

        invoices = list(current_invoices().select_related("document").order_by("pk"))
        if not invoices:
            raise CommandError("No extracted invoices found. Run extract first.")
        self.stdout.write(f"Writing simulated shipments to {output}")
        created, used_ids = 0, set()
        for position, invoice in enumerate(invoices):
            scenario = order[position % len(order)]
            label = f"{invoice.invoice_number or '(no number)'} [{invoice.document.file_name[:30]}]"
            shipment_id = invoice_shipment_id(invoice)
            if not shipment_id:
                self.stdout.write(f"  {label}: no shipment ID on the invoice, no fixture made.")
                continue
            if scenario == "missing":
                self.stdout.write(f"  {label}: scenario missing. {SCENARIOS[scenario]}")
                continue
            fixture = build_fixture(invoice, shipment_id, scenario, position + 1)
            fixture_id = fixture["details"]["customId"]
            if fixture_id in used_ids:
                self.stdout.write(f"  {label}: shipment {fixture_id} already has a fixture from another invoice, skipped.")
                continue
            used_ids.add(fixture_id)
            (output / f"{fixture_id}.json").write_text(json.dumps(fixture, indent=2), encoding="utf-8")
            created += 1
            self.stdout.write(f"  {label} -> shipment {fixture_id}, scenario {scenario}. {SCENARIOS[scenario]}")
        self.stdout.write(self.style.SUCCESS(f"Created {created} simulated shipment(s). These are invented data for the demo."))

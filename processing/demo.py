"""Builds the 50 case demo set used by the demo_run command.

Synthetic cases are created as already extracted invoices, with a matching simulated shipment
for each, so the run needs no API calls. Real invoices come from earlier extraction runs. Every
synthetic case is designed to pass or to fail for one known reason, which is what lets the run
check itself.
"""
import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from extraction.models import ExtractionRun, Invoice, InvoiceLine
from intake.models import Document
from scripts.make_synthetic import pdf

TOTAL_CASES = 50
EXPECTED_PASS = 35
EXPECTED_FAIL = 15

CARRIERS = [
    "Northwind Freight Lines", "Maple Leaf Haulage", "Sunrise Cargo Movers", "Bluewater Drayage",
    "Summit Intermodal", "Harborline Trucking", "Redwood Transport", "Granite State Carriers",
    "Lakeshore Freight", "Prairie Wind Logistics", "Cedar Point Express", "Ironbridge Logistics",
]
PASS_KINDS = ["exact", "tolerance", "no_currency", "legal_suffix", "factoring", "container", "cad", "single_line"]
# In priority order. Fewer are used when real invoices already supply some expected failures.
FAIL_KINDS = [
    "amount_over", "unknown_accessorial", "currency_mismatch", "carrier_mismatch", "typo", "duplicate",
    "math_mismatch", "missing_number", "low_confidence", "write_rejected", "amount_over",
    "unknown_accessorial", "duplicate", "typo", "write_rejected",
]
# What each failing kind is designed to trigger. write_rejected fails during processing instead.
EXPECTED_FLAG = {
    "amount_over": "amount_over_tolerance", "unknown_accessorial": "unknown_accessorial",
    "currency_mismatch": "currency_mismatch", "carrier_mismatch": "carrier_mismatch",
    "typo": "no_matching_shipment", "duplicate": "duplicate_invoice", "math_mismatch": "math_mismatch",
    "missing_number": "missing_required_field", "low_confidence": "low_confidence", "write_rejected": "",
}
FIELDS = ("shipment_id", "carrier_name", "factoring_company", "invoice_number", "invoice_date", "currency", "total_amount")


@dataclass
class Spec:
    index: int
    kind: str
    expected: str  # pass or fail
    carrier: str
    shipment_id: str
    values: dict
    lines: list  # (charge name, amount) as billed on the invoice
    fixture: dict | None
    confidence: float = 0.95
    note: str = ""


@dataclass
class Case:
    number: int
    source: str  # synthetic or real
    kind: str
    expected: str
    expected_flag: str
    invoice: Invoice
    note: str = ""
    result: dict = field(default_factory=dict)


def shipment_fixture(index, shipment_id, carrier, currency, lines, container="", **simulation):
    total = float(sum(amount for _, amount in lines))
    return {
        "Status": "SUCCESS",
        "details": {
            "id": 92000000 + index, "customId": shipment_id,
            "status": {"code": {"key": "2101", "value": "Delivered"}},
            "modeInfo": [{"containerNumber": container}] if container else [],
            "carrierOrder": [{
                "id": 72000000 + index, "carrier": {"id": 7000 + index, "name": carrier},
                "costs": {
                    "totalAmount": total,
                    "transactionCurrency": {"key": "1500", "value": currency},
                    "lineItem": [
                        {"code": {"key": "1600", "value": name}, "qty": 1, "price": float(amount), "amount": float(amount), "id": 300 + i}
                        for i, (name, amount) in enumerate(lines)
                    ],
                },
                "payment": [],
            }],
        },
        "simulation": {"generated": True, "demo_run": True, **simulation},
    }


def make_spec(index: int, kind: str, expected: str, rng: random.Random, earlier_pass: list[Spec]) -> Spec:
    carrier = CARRIERS[index % len(CARRIERS)]
    shipment_id = f"31{900 + index:03d}-{10000 + index * 7:05d}"
    base = Decimal(rng.randrange(800, 6000, 25))
    fuel = (base * Decimal("0.15")).quantize(Decimal("0.01"))
    lines = [("Linehaul", base), ("Fuel Surcharge", fuel)]
    if index % 3 == 0:
        lines.append(("Detention", Decimal("150.00")))
    shipment_lines = [("Freight - flat" if name == "Linehaul" else name, amount) for name, amount in lines]
    currency, ship_currency = "USD", "USD"
    invoice_carrier, factoring, container, simulation = carrier, "", "", {}
    shown_id, fixture_id, ship_carrier = shipment_id, shipment_id, carrier
    refs, number, confidence, note = [], f"DEMO-{index:04d}", 0.95, ""
    invoice_total = None

    if kind == "tolerance":
        lines[0] = ("Linehaul", base + Decimal("0.60"))
        note = "Linehaul is 0.60 above the shipment, inside the tolerance."
    elif kind == "no_currency":
        currency = ""
    elif kind == "legal_suffix":
        invoice_carrier = carrier.upper() + " LLC"
    elif kind == "factoring":
        invoice_carrier, factoring = f"Independent Hauler {index}", carrier + " Capital LLC"
    elif kind == "container":
        container = f"DEMU{1000000 + index * 13}"
        refs = [{"label": "Container Number", "value": container}]
    elif kind == "cad":
        currency = ship_currency = "CAD"
    elif kind == "single_line":
        lines, shipment_lines = [("Linehaul", base)], [("Freight - flat", base)]
    elif kind == "amount_over":
        lines[0] = ("Linehaul", (base * Decimal("1.12")).quantize(Decimal("0.01")))
        note = "Linehaul is 12 percent above the shipment."
    elif kind == "unknown_accessorial":
        lines.append(("Lumper fee", Decimal("75.00")))
        note = "Lumper fee is not on the shipment."
    elif kind == "currency_mismatch":
        ship_currency = "CAD"
        note = "The invoice is in USD and the shipment is in CAD."
    elif kind == "carrier_mismatch":
        ship_carrier = "Pacific Coast Logistics"
        note = "The shipment belongs to Pacific Coast Logistics."
    elif kind == "typo":
        fixture_id = shipment_id[:-1] + str((int(shipment_id[-1]) + 1) % 10)
        note = f"The invoice prints {shipment_id}. The TMS has {fixture_id}."
    elif kind == "duplicate":
        original = earlier_pass[-1]
        number, invoice_carrier = original.values["invoice_number"], original.values["carrier_name"]
        ship_carrier = invoice_carrier
        note = f"Same invoice number and carrier as case {original.index}."
    elif kind == "math_mismatch":
        invoice_total = sum(amount for _, amount in lines) + Decimal("40.00")
        note = "Line items add up to 40.00 less than the printed total."
    elif kind == "missing_number":
        number = ""
        note = "No invoice number is printed."
    elif kind == "low_confidence":
        confidence = 0.6
        note = "The reader was unsure about every field, as with a poor scan."
    elif kind == "write_rejected":
        simulation = {"reject_attach_document": "Document type is not enabled for this account (simulated rejection)."}
        note = "The simulated TMS rejects the document upload."

    total = invoice_total if invoice_total is not None else sum(amount for _, amount in lines)
    values = {
        "shipment_id": shown_id, "carrier_name": invoice_carrier, "factoring_company": factoring,
        "invoice_number": number, "invoice_date": date(2026, 9, 1) + timedelta(days=index % 25),
        "currency": currency, "total_amount": total, "overall_confidence": confidence, "other_references": refs,
    }
    fixture = shipment_fixture(index, fixture_id, ship_carrier, ship_currency, shipment_lines, container, **simulation)
    return Spec(index, kind, expected, carrier, shipment_id, values, lines, fixture, confidence, note)


def invoice_pdf_lines(spec: Spec) -> list[str]:
    v = spec.values
    out = [(v["factoring_company"] or v["carrier_name"]).upper(), "INVOICE", ""]
    if v["invoice_number"]:
        out.append(f"Invoice No: {v['invoice_number']}    Invoice Date: {v['invoice_date']}")
    else:
        out.append(f"Invoice Date: {v['invoice_date']}")
    out += [f"Shipment Ref: {v['shipment_id']}", f"Carrier: {v['carrier_name']}"]
    out += [f"{r['label']}: {r['value']}" for r in v["other_references"]]
    out.append("")
    out += [f"{name:<30}{amount:>12,.2f}" for name, amount in spec.lines]
    out += ["", f"Total Due {v['currency']}".strip() + f"   {v['total_amount']:,.2f}"]
    return out


def store_spec(spec: Spec, folder: Path) -> Invoice:
    """Write the invoice PDF and create the extracted records, as if extraction had already run."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"demo_{spec.index:03d}_{spec.kind}.pdf"
    path.write_bytes(pdf(invoice_pdf_lines(spec)))
    data = path.read_bytes()
    try:
        stored = path.resolve().relative_to(Path(settings.BASE_DIR).resolve()).as_posix()
    except ValueError:
        stored = str(path.resolve())
    document = Document.objects.create(
        path=stored, file_name=path.name, content_hash=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
        media_type="application/pdf", page_count=1, source=Document.Source.SYNTHETIC, status=Document.Status.EXTRACTED,
    )
    run = ExtractionRun.objects.create(
        document=document, model="demo", prompt_version="demo", status=ExtractionRun.Status.SUCCESS, raw_output="{}"
    )
    v = spec.values
    details = {
        name: {"value": str(v[name]) if v[name] else None, "confidence": spec.confidence, "rationale": "demo case", "page": 1}
        for name in FIELDS
    }
    invoice = Invoice.objects.create(
        document=document, extraction_run=run, shipment_id=v["shipment_id"], shipment_id_raw=v["shipment_id"],
        carrier_name=v["carrier_name"], factoring_company=v["factoring_company"], invoice_number=v["invoice_number"],
        invoice_date=v["invoice_date"], currency=v["currency"], total_amount=v["total_amount"],
        overall_confidence=v["overall_confidence"], other_references=v["other_references"], field_details=details,
    )
    InvoiceLine.objects.bulk_create(
        InvoiceLine(invoice=invoice, position=i, charge_type=name, amount=amount, confidence=0.9, page=1)
        for i, (name, amount) in enumerate(spec.lines, start=1)
    )
    return invoice


def plan_kinds(pass_count: int, fail_count: int) -> list[tuple[str, str]]:
    """Mix passes and failures evenly. Failing kinds that need an earlier case come after some passes."""
    passes = [("pass", PASS_KINDS[i % len(PASS_KINDS)]) for i in range(pass_count)]
    fails = [("fail", kind) for kind in FAIL_KINDS[:fail_count]]
    order, p, f = [], 0, 0
    total = pass_count + fail_count
    for position in range(total):
        want_fail = f < fail_count and (position + 1) * fail_count // total > f
        if want_fail and fails[f][1] == "duplicate" and p == 0:
            want_fail = False
        if want_fail or p >= pass_count:
            order.append(fails[f]); f += 1
        else:
            order.append(passes[p]); p += 1
    return order

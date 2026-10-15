"""Helpers shared by tests. Builds extracted invoices without calling any API."""
import dataclasses
import hashlib
import itertools
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from config.env import load_config
from extraction.models import ExtractionRun, Invoice, InvoiceLine
from intake.models import Document

BASE = Path(settings.BASE_DIR)
SYNTHETIC_SHIPMENTS = BASE / "data" / "synthetic" / "shipments"
_counter = itertools.count(1)

DEFAULT_LINES = [("Linehaul", "1250.00"), ("Fuel Surcharge", "187.50"), ("Detention", "150.00")]


def sample_config(**changes):
    """Config that reads only the synthetic shipment fixtures."""
    config = load_config(BASE, {})
    return dataclasses.replace(config, tms_fixture_dirs=(SYNTHETIC_SHIPMENTS,), **changes)


def make_invoice(lines=None, directory: Path | None = None, confidence=0.95, **values) -> Invoice:
    """An extracted invoice that matches synthetic shipment 31000-00001 unless values say otherwise."""
    n = next(_counter)
    directory = directory or Path(tempfile.mkdtemp())
    path = directory / f"invoice_{n}.pdf"
    path.write_bytes(f"%PDF-1.4 test invoice {n}".encode())
    document = Document.objects.create(
        path=str(path), file_name=path.name, content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size, media_type="application/pdf", source="synthetic", status="extracted",
    )
    run = ExtractionRun.objects.create(document=document, model="test", prompt_version="test", status="success")
    data = {
        "shipment_id": "31000-00001", "carrier_name": "Northwind Freight Lines", "factoring_company": "",
        "invoice_number": f"NW-{n}", "invoice_date": date(2026, 8, 14), "currency": "USD", "total_amount": Decimal("1587.50"),
        "overall_confidence": 0.95, "other_references": [],
    }
    data.update(values)
    details = {
        name: {"value": str(data[name]) if data[name] else None, "confidence": confidence, "rationale": "test", "page": 1}
        for name in ("shipment_id", "carrier_name", "invoice_number", "invoice_date", "currency", "total_amount")
    }
    invoice = Invoice.objects.create(document=document, extraction_run=run, field_details=details, **data)
    for position, (charge, amount) in enumerate(DEFAULT_LINES if lines is None else lines, start=1):
        InvoiceLine.objects.create(invoice=invoice, position=position, charge_type=charge, amount=Decimal(amount), confidence=0.9)
    return invoice

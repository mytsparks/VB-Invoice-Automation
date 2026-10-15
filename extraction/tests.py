import dataclasses
import json
import tempfile
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from config.env import load_config
from extraction.adapter import ExtractorAuthError, ExtractorResponse, Usage
from extraction.models import ExtractionRun, Invoice
from extraction.normalize import normalize_shipment_id, parse_amount, parse_date
from extraction.pricing import cost_usd
from extraction.services import RunAborted, extract_documents
from intake.models import Document
from intake.services import ingest_folder

BASE = Path(settings.BASE_DIR)


def field(value, confidence=0.95):
    return {"value": value, "confidence": confidence, "rationale": "test", "page": 1}


def invoice_json(**overrides):
    invoice = {
        "shipment_id": field("31000-00001"),
        "carrier_name": field("Northwind Freight Lines"),
        "factoring_company": field(None),
        "invoice_number": field("NW-1"),
        "invoice_date": field("2026-08-14"),
        "currency": field("USD"),
        "total_amount": field("1,587.50"),
        "other_references": [{"label": "Container", "value": "TEST1234567"}],
        "line_items": [
            {"charge_type": "Linehaul", "description": None, "amount": "1250.00", "confidence": 0.9, "page": 1},
            {"charge_type": "Fuel", "description": None, "amount": "337.50", "confidence": 0.9, "page": 1},
        ],
        "overall_confidence": 0.93,
        "notes": None,
    }
    invoice.update(overrides)
    return {"document_type": "carrier_invoice", "page_count": 1, "invoices": [invoice], "notes": None}


class FakeExtractor:
    model = "claude-sonnet-5-5"
    prompt_version = "invoice_extraction/v1"

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def extract(self, data, media_type):
        self.calls += 1
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        text = output if isinstance(output, str) else json.dumps(output)
        return ExtractorResponse(text, Usage(input_tokens=4000, output_tokens=800))


class NormalizeTests(SimpleTestCase):
    def test_amounts(self):
        self.assertEqual(parse_amount("1,587.50"), Decimal("1587.50"))
        self.assertEqual(parse_amount("$1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse_amount("(45.00)"), Decimal("-45.00"))
        self.assertEqual(parse_amount("-12.5"), Decimal("-12.5"))
        self.assertIsNone(parse_amount("n/a"))
        self.assertIsNone(parse_amount(None))

    def test_ambiguous_dates_are_not_guessed(self):
        self.assertEqual(parse_date("2026-08-14").isoformat(), "2026-08-14")
        self.assertIsNone(parse_date("03/04/2026"))

    def test_dates_with_a_clear_order_are_parsed(self):
        self.assertEqual(parse_date("9/14/2026").isoformat(), "2026-09-14")
        self.assertEqual(parse_date("14/09/2026").isoformat(), "2026-09-14")
        self.assertEqual(parse_date("Sep 14, 2026").isoformat(), "2026-09-14")
        self.assertIsNone(parse_date("31/31/2026"))

    def test_shipment_id(self):
        self.assertEqual(normalize_shipment_id("Ref 31234 - 56789"), "31234-56789")
        self.assertEqual(normalize_shipment_id("41234-56789"), "")

    def test_cost(self):
        self.assertEqual(cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000), Decimal("12"))


class ExtractionServiceTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        (self.folder / "a.pdf").write_bytes(b"%PDF-1.4 /Type /Page a")
        (self.folder / "b.pdf").write_bytes(b"%PDF-1.4 /Type /Page b")
        ingest_folder(self.folder)
        # Files outside data/synthetic are real, so allow them for these tests.
        self.config = dataclasses.replace(
            load_config(BASE, {}), allow_real_invoices_to_llm=True
        )

    def run_extract(self, extractor, config=None, **kwargs):
        with override_settings(APP=config or self.config):
            return extract_documents(list(Document.objects.all()), extractor, **kwargs)

    def test_extracts_and_stores_normalized_values(self):
        summary = self.run_extract(FakeExtractor(invoice_json(), invoice_json()))
        self.assertEqual(summary.extracted, 2)
        invoice = Invoice.objects.first()
        self.assertEqual(invoice.shipment_id, "31000-00001")
        self.assertEqual(invoice.total_amount, Decimal("1587.50"))
        self.assertEqual(invoice.invoice_date.isoformat(), "2026-08-14")
        self.assertEqual(invoice.lines.count(), 2)
        self.assertEqual(invoice.review_reasons, [])
        run = ExtractionRun.objects.first()
        self.assertEqual(run.status, "success")
        self.assertIn("31000-00001", run.raw_output)
        self.assertGreater(run.estimated_cost_usd, 0)

    def test_second_run_is_served_from_cache(self):
        self.run_extract(FakeExtractor(invoice_json(), invoice_json()))
        extractor = FakeExtractor()
        summary = self.run_extract(extractor)
        self.assertEqual(summary.cached, 2)
        self.assertEqual(extractor.calls, 0)

    def test_low_confidence_and_missing_fields_route_to_review(self):
        data = invoice_json(total_amount=field("1587.50", 0.4), shipment_id=field(None, 0.2))
        self.run_extract(FakeExtractor(data, data))
        reasons = " ".join(Invoice.objects.first().review_reasons)
        self.assertIn("total_amount has low confidence", reasons)
        self.assertIn("shipment_id is missing", reasons)

    def test_malformed_output_is_retried_once(self):
        extractor = FakeExtractor("not json", invoice_json(), invoice_json())
        summary = self.run_extract(extractor)
        self.assertEqual(summary.extracted, 2)
        self.assertEqual(extractor.calls, 3)
        self.assertEqual(ExtractionRun.objects.first().attempts, 2)

    def test_repeated_malformed_output_marks_document_for_review(self):
        summary = self.run_extract(FakeExtractor("bad", "bad", "bad", "bad"))
        self.assertEqual(summary.failed, 2)
        self.assertEqual(Document.objects.filter(status="needs_review").count(), 2)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_non_invoice_is_kept_visible(self):
        other = {"document_type": "bill_of_lading", "page_count": 1, "invoices": [], "notes": "BOL"}
        self.run_extract(FakeExtractor(other, other))
        self.assertEqual(Document.objects.filter(status="non_invoice").count(), 2)

    def test_real_files_blocked_unless_allowed(self):
        blocked = dataclasses.replace(self.config, allow_real_invoices_to_llm=False)
        extractor = FakeExtractor()
        summary = self.run_extract(extractor, blocked)
        self.assertEqual(summary.blocked, 2)
        self.assertEqual(extractor.calls, 0)

    def test_synthetic_files_are_always_allowed(self):
        Document.objects.update(source="synthetic")
        blocked = dataclasses.replace(self.config, allow_real_invoices_to_llm=False)
        summary = self.run_extract(FakeExtractor(invoice_json(), invoice_json()), blocked)
        self.assertEqual(summary.extracted, 2)

    def test_document_cap_stops_run(self):
        capped = dataclasses.replace(self.config, max_docs_per_run=1)
        extractor = FakeExtractor(invoice_json())
        summary = self.run_extract(extractor, capped)
        self.assertEqual(extractor.calls, 1)
        self.assertIn("document cap", summary.stopped_reason)

    def test_cost_cap_stops_run_before_calling(self):
        capped = dataclasses.replace(self.config, run_cost_cap_usd=Decimal("0.001"))
        extractor = FakeExtractor()
        summary = self.run_extract(extractor, capped)
        self.assertEqual(extractor.calls, 0)
        self.assertIn("cost cap", summary.stopped_reason)

    def test_dry_run_never_calls_extractor(self):
        summary = self.run_extract(None, dry_run=True)
        self.assertEqual(summary.sent, 2)
        self.assertGreater(summary.estimated, 0)
        self.assertEqual(ExtractionRun.objects.count(), 0)

    def test_rejected_key_aborts_run(self):
        with self.assertRaises(RunAborted):
            self.run_extract(FakeExtractor(ExtractorAuthError("401")))

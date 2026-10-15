import json
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from config.samples import make_invoice, sample_config
from matching.services import evaluate, override, save_match
from processing.models import TmsWrite
from processing.services import ProcessAborted, WriteBudget, is_processed, process_match
from tms.factory import get_tms_client


class FakeTty:
    def isatty(self):
        return True


def matched(config, tms, **values):
    invoice = make_invoice(**values)
    return save_match(invoice, evaluate(invoice, tms, config))


class ProcessServiceTests(TestCase):
    def setUp(self):
        self.config = sample_config()
        self.tms = get_tms_client(self.config)

    def process(self, match, dry_run=False, limit=50):
        return process_match(match, self.tms, WriteBudget(limit), dry_run=dry_run)

    def test_ready_invoice_is_written_once_and_read_back(self):
        match = matched(self.config, self.tms)
        result = self.process(match)
        self.assertEqual(result.status, "processed")
        writes = TmsWrite.objects.filter(status="success")
        self.assertEqual(sorted(w.operation for w in writes), ["attach_document", "record_invoice"])
        self.assertTrue(all(w.readback_ok for w in writes))
        self.assertTrue(is_processed(match, "mock"))

    def test_rerun_writes_nothing_new(self):
        match = matched(self.config, self.tms)
        self.process(match)
        count = TmsWrite.objects.count()
        self.assertEqual(self.process(match).status, "already_done")
        self.assertEqual(TmsWrite.objects.count(), count)

    def test_dry_run_writes_nothing(self):
        match = matched(self.config, self.tms)
        result = self.process(match, dry_run=True)
        self.assertEqual(result.status, "dry_run")
        self.assertEqual(TmsWrite.objects.count(), 0)

    def test_rejected_write_is_recorded_and_stops_that_invoice(self):
        match = matched(self.config, self.tms, shipment_id="31000-00003", carrier_name="Sunrise Cargo Movers", total_amount=Decimal("900.00"), lines=[("Drayage", "800.00"), ("Chassis fee", "100.00")])
        result = self.process(match)
        self.assertEqual(result.status, "failed")
        write = TmsWrite.objects.get()
        self.assertEqual((write.operation, write.status, write.http_status), ("attach_document", "failed", 422))
        self.assertIn("simulated rejection", write.error)

    def test_write_cap_stops_before_finishing(self):
        match = matched(self.config, self.tms)
        self.assertEqual(self.process(match, limit=1).status, "stopped")
        self.assertEqual(TmsWrite.objects.filter(status="success").count(), 1)
        # A later run with budget finishes only the remaining write.
        self.assertEqual(self.process(match).status, "processed")
        self.assertEqual(TmsWrite.objects.filter(status="success").count(), 2)

    def test_auth_error_aborts_the_run(self):
        folder = Path(tempfile.mkdtemp())
        source = json.loads((self.config.tms_fixture_dirs[0] / "31000-00001.json").read_text())
        source["simulation"] = {"auth_error": True}
        (folder / "31000-00001.json").write_text(json.dumps(source))
        import dataclasses
        config = dataclasses.replace(self.config, tms_fixture_dirs=(folder,))
        tms = get_tms_client(config)
        match = matched(config, tms)
        with self.assertRaises(ProcessAborted):
            process_match(match, tms, WriteBudget(10))
        self.assertEqual(TmsWrite.objects.get().status, "failed")

    def test_processed_invoice_is_seen_as_duplicate_by_later_matching(self):
        first = matched(self.config, self.tms, invoice_number="SAME-1")
        self.process(first)
        second = make_invoice(invoice_number="SAME-1")
        flags = {f.code for f in evaluate(second, self.tms, self.config).flags}
        self.assertIn("duplicate_invoice", flags)


@override_settings(APP=sample_config())
class ProcessCommandTests(TestCase):
    def setUp(self):
        self.config = sample_config()
        self.tms = get_tms_client(self.config)

    def run_process(self, answers=(), **options):
        out = StringIO()
        with mock.patch("config.ui.sys.stdin", FakeTty()), mock.patch("builtins.input", side_effect=list(answers)):
            call_command("process", stdout=out, **options)
        return out.getvalue()

    def test_interactive_yes_sends_the_invoice(self):
        matched(self.config, self.tms)
        output = self.run_process(["y"])
        self.assertIn("1 invoice(s) processed", output)
        self.assertEqual(TmsWrite.objects.filter(status="success").count(), 2)

    def test_interactive_no_sends_nothing(self):
        matched(self.config, self.tms)
        output = self.run_process(["n"])
        self.assertIn("1 declined by you", output)
        self.assertEqual(TmsWrite.objects.count(), 0)

    def test_held_invoice_needs_a_note_to_override(self):
        match = matched(self.config, self.tms, currency="CAD")
        output = self.run_process(["y", "o", "Confirmed with the carrier"])
        match.refresh_from_db()
        self.assertEqual(match.outcome, "overridden")
        self.assertEqual(match.override_note, "Confirmed with the carrier")
        self.assertIn("approved despite flags", output)
        self.assertEqual(TmsWrite.objects.filter(status="success").count(), 2)

    def test_held_invoice_is_not_sent_when_skipped(self):
        matched(self.config, self.tms, currency="CAD")
        self.run_process(["y", "s"])
        self.assertEqual(TmsWrite.objects.count(), 0)

    def test_yes_never_sends_held_invoices(self):
        matched(self.config, self.tms)
        matched(self.config, self.tms, currency="CAD")
        with mock.patch("config.ui.sys.stdin", FakeTty()):
            out = StringIO()
            call_command("process", yes=True, no_input=True, stdout=out)
        self.assertEqual(TmsWrite.objects.filter(status="success").count(), 2)
        self.assertIn("1 held for review", out.getvalue())

    def test_non_interactive_without_yes_is_refused(self):
        matched(self.config, self.tms)
        with self.assertRaises(CommandError):
            call_command("process", no_input=True, stdout=StringIO())

    def test_dry_run_changes_nothing(self):
        matched(self.config, self.tms)
        output = self.run_process(dry_run=True)
        self.assertIn("Dry run. 1 invoice(s) would be written", output)
        self.assertEqual(TmsWrite.objects.count(), 0)


class DemoRunTests(TestCase):
    def run_demo(self):
        import csv
        folder = Path(tempfile.mkdtemp())
        out = StringIO()
        call_command("demo_run", workdir=str(folder / "work"), output_dir=str(folder / "reports"), stdout=out)
        failures = next((folder / "reports").glob("*_failures.csv"))
        with failures.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return out.getvalue(), rows

    def make_real(self, number, **values):
        invoice = make_invoice(invoice_number=number, shipment_id=f"31{700 + int(number[-1])}-00001", **values)
        invoice.document.source = "real"
        invoice.document.save()
        return invoice

    def test_runs_35_passes_and_15_logged_failures_without_real_invoices(self):
        output, rows = self.run_demo()
        self.assertIn("35 processed successfully (expected 35)", output)
        self.assertIn("15 failed (expected 15)", output)
        self.assertEqual(len(rows), 15)
        self.assertEqual(TmsWrite.objects.filter(status="success").count(), 70)
        self.assertTrue(all(row["reasons"] and row["failed_at"] in ("match", "process") for row in rows))

    def test_real_invoices_count_toward_the_split(self):
        clean_a, clean_b = self.make_real("R-1"), self.make_real("R-2")
        dirty = self.make_real("R-3", confidence=0.5)
        output, rows = self.run_demo()
        self.assertIn("50 invoices", output)
        self.assertIn("35 processed successfully (expected 35)", output)
        self.assertEqual(len(rows), 15)
        self.assertIn("R-3", [row["invoice_number"] for row in rows])
        self.assertEqual(TmsWrite.objects.filter(invoice__in=[clean_a, clean_b], status="success").count(), 4)
        self.assertFalse(TmsWrite.objects.filter(invoice=dirty).exists())

    def test_second_run_gives_the_same_result(self):
        self.make_real("R-1")
        first, _ = self.run_demo()
        second, rows = self.run_demo()
        self.assertIn("35 processed successfully (expected 35)", second)
        self.assertEqual(len(rows), 15)

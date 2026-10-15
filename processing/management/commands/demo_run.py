"""One command demo. Runs 50 invoices through match and process against the simulated TMS.

    python manage.py demo_run

35 are built to pass and 15 to fail. Real invoices already extracted into the database are included
first, and synthetic cases fill the rest. Nothing is sent to the Claude API and nothing is written
to a real TMS. Failures are written to a CSV in reports/.
"""
import csv
import dataclasses
import json
import random
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from extraction.services import current_invoices
from intake.models import Document
from matching.management.commands.make_demo_shipments import build_fixture, invoice_shipment_id
from matching.models import MatchResult, ShipmentRecord
from matching.services import evaluate, save_match
from processing.demo import (
    EXPECTED_FAIL, EXPECTED_FLAG, EXPECTED_PASS, TOTAL_CASES, Case, make_spec, plan_kinds, store_spec,
)
from processing.models import TmsWrite
from processing.services import WriteBudget, process_match
from tms.base import TmsError
from tms.factory import get_tms_client

FAILURE_COLUMNS = [
    "case", "source", "file_name", "invoice_number", "carrier", "factoring_company", "shipment_id_on_invoice",
    "invoice_date", "currency", "invoice_total", "tms_shipment", "tms_carrier", "tms_total", "difference",
    "failed_at", "flags", "reasons", "suggested_shipments", "tms_error", "expected", "designed_reason",
]
ALL_COLUMNS = ["case", "source", "file_name", "invoice_number", "carrier", "invoice_total", "expected", "actual", "failed_at", "flags", "matches_expectation"]


class Command(BaseCommand):
    help = "Run 50 invoices (35 built to pass, 15 to fail) through match and process on the simulated TMS, and log the failures to CSV."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", help="Where to write the CSV logs. Default is reports/.")
        parser.add_argument("--cleanup", action="store_true", help="Remove the demo invoices from the database afterwards, so later match and show commands do not list them.")
        parser.add_argument("--workdir", help="Where the generated PDFs and shipments go. Default is data/demo_run.")

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        workdir = Path(options["workdir"]) if options["workdir"] else base / "data" / "demo_run"
        output_dir = Path(options["output_dir"]) if options["output_dir"] else base / "reports"
        shipments_dir = workdir / "shipments"

        self.clean_previous(workdir)
        real_invoices = list(current_invoices().filter(document__source=Document.Source.REAL).select_related("document").order_by("pk"))
        real_cases = self.prepare_real(real_invoices, shipments_dir, workdir)
        cases = real_cases + self.prepare_synthetic(real_cases, shipments_dir, workdir)

        config = dataclasses.replace(settings.APP, tms_fixture_dirs=(shipments_dir,))
        try:
            client = get_tms_client(config)
            client.check()
        except (ValueError, TmsError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"[SIMULATED TMS] {len(cases)} invoices: {len(real_cases)} real, {len(cases) - len(real_cases)} synthetic. "
                          f"Built to give {sum(c.expected == 'pass' for c in cases)} passes and {sum(c.expected == 'fail' for c in cases)} failures.\n")
        budget = WriteBudget(len(cases) * 2 + 10)
        for case in sorted(cases, key=lambda c: c.invoice.pk):
            self.run_case(case, client, config, budget)
            self.print_case(case, len(cases))

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir.mkdir(parents=True, exist_ok=True)
        failures_path = output_dir / f"demo_run_{stamp}_failures.csv"
        all_path = output_dir / f"demo_run_{stamp}_all_results.csv"
        ordered = sorted(cases, key=lambda c: c.number)
        self.write_csv(failures_path, FAILURE_COLUMNS, [self.failure_row(c) for c in ordered if c.result["actual"] == "fail"])
        self.write_csv(all_path, ALL_COLUMNS, [self.all_row(c) for c in ordered])
        try:
            self.summary(ordered, failures_path, all_path)
        finally:
            if options["cleanup"]:
                Document.objects.filter(extraction_runs__model="demo").delete()
                self.stdout.write("Demo invoices removed from the database.")

    # Setup -----------------------------------------------------------------------------------

    def clean_previous(self, workdir: Path) -> None:
        """Remove the last demo run and any match state on real invoices, so every run starts the same."""
        # Demo documents are marked by their extraction run, wherever the work folder was.
        Document.objects.filter(extraction_runs__model="demo").delete()
        real = current_invoices().filter(document__source=Document.Source.REAL)
        TmsWrite.objects.filter(invoice__in=real).delete()
        MatchResult.objects.filter(invoice__in=real).delete()
        ShipmentRecord.objects.filter(matchresult__isnull=True).delete()
        # Delete files only. Synced folders such as OneDrive can refuse to remove a directory.
        for path in sorted(workdir.rglob("*"), reverse=True) if workdir.exists() else []:
            if path.is_file():
                path.unlink(missing_ok=True)
        (workdir / "shipments").mkdir(parents=True, exist_ok=True)

    def prepare_real(self, invoices, shipments_dir: Path, workdir: Path) -> list[Case]:
        """Build an exact shipment for each real invoice. It passes if the extraction was clean."""
        cases = []
        for position, invoice in enumerate(invoices, start=1):
            shipment_id = invoice_shipment_id(invoice)
            if shipment_id:
                fixture = build_fixture(invoice, shipment_id, "exact", 800 + position)
                (shipments_dir / f"{shipment_id}.json").write_text(json.dumps(fixture, indent=2), encoding="utf-8")
            cases.append(Case(0, "real", "real invoice", "pass", "", invoice))
        # A real invoice is expected to pass only when it evaluates cleanly against its own shipment.
        if cases:
            client = get_tms_client(dataclasses.replace(settings.APP, tms_fixture_dirs=(shipments_dir,)))
            for case in cases:
                baseline = evaluate(case.invoice, client, settings.APP)
                if baseline.flags or baseline.shipment is None:
                    case.expected = "fail"
                    case.expected_flag = baseline.flags[0].code if baseline.flags else "no_matching_shipment"
                    case.note = "Real invoice with extraction or data concerns: " + ", ".join(sorted({f.code for f in baseline.flags}))
                else:
                    case.note = "Real invoice, shipment built from its own extracted values."
        return cases

    def prepare_synthetic(self, real_cases: list[Case], shipments_dir: Path, workdir: Path) -> list[Case]:
        real_pass = sum(c.expected == "pass" for c in real_cases)
        real_fail = len(real_cases) - real_pass
        pass_count, fail_count = EXPECTED_PASS - real_pass, EXPECTED_FAIL - real_fail
        if len(real_cases) > TOTAL_CASES or pass_count < 0 or fail_count < 0:
            raise CommandError(
                f"The {len(real_cases)} real invoices ({real_pass} expected to pass, {real_fail} to fail) do not fit in a "
                f"{EXPECTED_PASS} pass and {EXPECTED_FAIL} fail run."
            )
        rng = random.Random(2026)
        cases, earlier_pass = [], []
        for offset, (expected, kind) in enumerate(plan_kinds(pass_count, fail_count)):
            index = len(real_cases) + offset + 1
            spec = make_spec(index, kind, expected, rng, earlier_pass)
            invoice = store_spec(spec, workdir / "invoices")
            fixture_id = spec.fixture["details"]["customId"]
            (shipments_dir / f"{fixture_id}.json").write_text(json.dumps(spec.fixture, indent=2), encoding="utf-8")
            if expected == "pass":
                earlier_pass.append(spec)
            cases.append(Case(index, "synthetic", kind, expected, EXPECTED_FLAG.get(kind, ""), invoice, spec.note))
        for number, case in enumerate(real_cases, start=1):
            case.number = number
        return cases

    # Running ---------------------------------------------------------------------------------

    def run_case(self, case: Case, client, config, budget) -> None:
        invoice = case.invoice
        result = evaluate(invoice, client, config)
        match = save_match(invoice, result)
        flags = list(match.flags.select_related("flag_type"))
        outcome = {"actual": "pass", "failed_at": "", "flags": flags, "match": match, "tms_error": "", "writes": 0}
        if match.outcome != "ready":
            outcome.update(actual="fail", failed_at="match")
        else:
            processed = process_match(match, client, budget, processing_run=None)
            outcome["writes"] = TmsWrite.objects.filter(invoice=invoice, status="success").count()
            if processed.status != "processed":
                errors = list(TmsWrite.objects.filter(invoice=invoice, status="failed").values_list("error", flat=True))
                outcome.update(actual="fail", failed_at="process", tms_error="; ".join(errors) or "; ".join(processed.messages))
        expectation_met = outcome["actual"] == case.expected
        if expectation_met and case.expected == "fail" and case.expected_flag:
            expectation_met = case.expected_flag in {f.flag_type.code for f in flags}
        if expectation_met and case.expected == "fail" and not case.expected_flag and case.kind == "write_rejected":
            expectation_met = outcome["failed_at"] == "process"
        outcome["matches_expectation"] = expectation_met
        case.result = outcome

    def print_case(self, case: Case, total: int) -> None:
        invoice, result = case.invoice, case.result
        label = f"[{case.number:>2}/{total}] {case.source[:5]:<5} {invoice.invoice_number or '(no number)':<12} {(invoice.carrier_name or invoice.factoring_company)[:26]:<26} {invoice.total_amount or 0:>10,.2f}  "
        if result["actual"] == "pass":
            line = self.style.SUCCESS("OK   ") + label + f"processed successfully ({result['writes']} writes)"
        else:
            if result["failed_at"] == "match":
                reason = "; ".join(dict.fromkeys(f.flag_type.name for f in result["flags"])) or "no shipment"
            else:
                reason = "write failed: " + result["tms_error"]
            line = self.style.ERROR("FAIL ") + label + reason[:70]
        if not result["matches_expectation"]:
            line += self.style.WARNING("  <- not what this case was built to do")
        self.stdout.write(line)

    # Reports ---------------------------------------------------------------------------------

    def failure_row(self, case: Case) -> dict:
        invoice, result = case.invoice, case.result
        match = result["match"]
        shipment = match.shipment
        difference = ""
        if shipment and shipment.total_cost is not None and invoice.total_amount is not None:
            difference = f"{invoice.total_amount - shipment.total_cost:.2f}"
        reasons = " | ".join(f.explanation for f in result["flags"]) or result["tms_error"]
        return {
            "case": case.number, "source": case.source, "file_name": invoice.document.file_name,
            "invoice_number": invoice.invoice_number, "carrier": invoice.carrier_name, "factoring_company": invoice.factoring_company,
            "shipment_id_on_invoice": invoice.shipment_id or invoice.shipment_id_raw,
            "invoice_date": invoice.invoice_date or "", "currency": invoice.currency,
            "invoice_total": f"{invoice.total_amount:.2f}" if invoice.total_amount is not None else "",
            "tms_shipment": shipment.shipment_id if shipment else "Not found",
            "tms_carrier": shipment.carrier_name if shipment else "",
            "tms_total": f"{shipment.total_cost:.2f}" if shipment and shipment.total_cost is not None else "",
            "difference": difference, "failed_at": result["failed_at"],
            "flags": "; ".join(dict.fromkeys(f.flag_type.name for f in result["flags"])), "reasons": reasons,
            "suggested_shipments": ", ".join(match.suggestions), "tms_error": result["tms_error"],
            "expected": case.expected, "designed_reason": case.note,
        }

    def all_row(self, case: Case) -> dict:
        invoice, result = case.invoice, case.result
        return {
            "case": case.number, "source": case.source, "file_name": invoice.document.file_name,
            "invoice_number": invoice.invoice_number, "carrier": invoice.carrier_name or invoice.factoring_company,
            "invoice_total": f"{invoice.total_amount:.2f}" if invoice.total_amount is not None else "",
            "expected": case.expected, "actual": result["actual"], "failed_at": result["failed_at"],
            "flags": "; ".join(dict.fromkeys(f.flag_type.name for f in result["flags"])),
            "matches_expectation": "yes" if result["matches_expectation"] else "NO",
        }

    @staticmethod
    def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
        # utf-8-sig so Excel opens the file with the right encoding.
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def summary(self, cases: list[Case], failures_path: Path, all_path: Path) -> None:
        passed = [c for c in cases if c.result["actual"] == "pass"]
        failed = [c for c in cases if c.result["actual"] == "fail"]
        unexpected = [c for c in cases if not c.result["matches_expectation"]]
        expected_pass = sum(c.expected == "pass" for c in cases)
        expected_fail = len(cases) - expected_pass
        write = self.stdout.write
        write("\n" + "=" * 78)
        write(f"{len(cases)} invoices run.")
        write(f"  {len(passed)} processed successfully (expected {expected_pass}).")
        write(f"  {len(failed)} failed (expected {expected_fail}) and were written to the log.")
        by_stage = {stage: sum(c.result["failed_at"] == stage for c in failed) for stage in ("match", "process")}
        write(f"    {by_stage['match']} held at matching, {by_stage['process']} failed when writing to the TMS.")
        write(f"  Failure log: {failures_path}")
        write(f"  All results: {all_path}")
        if unexpected:
            write(self.style.ERROR(f"\n{len(unexpected)} case(s) did not behave as designed:"))
            for case in unexpected:
                write(f"  case {case.number} ({case.kind}): expected {case.expected}, got {case.result['actual']}")
            raise CommandError("The run did not match its expected 35 pass and 15 fail split.")
        write(self.style.SUCCESS("\nEvery case behaved as designed."))

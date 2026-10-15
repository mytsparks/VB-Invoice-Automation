from django.conf import settings
from django.core.management.base import BaseCommand

from extraction.models import ExtractionRun, Invoice
from intake.models import Document
from matching.models import MatchResult
from matching.render import render_match


def money(value) -> str:
    return "-" if value is None else f"{value:,.2f}"


class Command(BaseCommand):
    help = "Display extracted invoice data for review, with confidence and source page for each value."

    def add_arguments(self, parser):
        parser.add_argument("--file", help="Only show documents whose file name contains this text.")
        parser.add_argument("--raw", action="store_true", help="Also print the raw model output.")

    def handle(self, *args, **options):
        documents = Document.objects.all()
        if options["file"]:
            documents = documents.filter(file_name__icontains=options["file"])
        if not documents:
            self.stdout.write("No documents found.")
            return
        threshold = settings.APP.low_confidence_threshold
        for document in documents:
            self.show_document(document, threshold, options["raw"])
        self.show_totals(documents)

    def show_document(self, document, threshold, raw):
        out = self.stdout.write
        out("=" * 78)
        out(f"{document.file_name}  [{document.get_status_display()}]  source: {document.source}")
        run = document.extraction_runs.order_by("-id").first()
        if run is None:
            out("  Not extracted yet.")
            return
        out(f"  Run {run.pk}: {run.status}, {run.model}, prompt {run.prompt_version}, "
            f"{run.input_tokens} in / {run.output_tokens} out tokens, ${run.estimated_cost_usd:.3f}")
        if run.error:
            out(f"  Problem: {run.error}")
        if raw and run.raw_output:
            out(run.raw_output)
        good_run = document.extraction_runs.filter(status=ExtractionRun.Status.SUCCESS).order_by("-id").first()
        for invoice in Invoice.objects.filter(extraction_run=good_run):
            self.show_invoice(invoice, threshold)

    def show_invoice(self, invoice, threshold):
        out = self.stdout.write
        verdict = "NEEDS REVIEW" if invoice.needs_review else "no extraction concerns"
        out(f"\n  Invoice {invoice.position}  ({verdict}, overall confidence {invoice.overall_confidence:.2f})")
        shown = {
            "shipment_id": invoice.shipment_id or invoice.shipment_id_raw,
            "carrier_name": invoice.carrier_name,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date or "",
            "currency": invoice.currency,
            "total_amount": money(invoice.total_amount) if invoice.total_amount is not None else "",
        }
        for name, value in shown.items():
            detail = invoice.field_details.get(name, {})
            confidence = detail.get("confidence", 0)
            marker = "!" if detail.get("value") is None or confidence < threshold else " "
            page = f"p{detail['page']}" if detail.get("page") else "--"
            out(f" {marker} {name:15} {str(value) or '(none)':28} conf {confidence:.2f}  {page:4} {detail.get('rationale', '')}")
        for reference in invoice.other_references:
            out(f"    ref {reference['label']}: {reference['value']}")
        lines = list(invoice.lines.all())
        if lines:
            out("    Line items")
            for line in lines:
                label = line.charge_type or line.description or "(no label)"
                out(f"      {line.position:>2}. {label:38} {money(line.amount):>12}  conf {line.confidence:.2f}")
            line_sum = sum((line.amount for line in lines if line.amount is not None), start=0)
            out(f"      Lines add up to {money(line_sum)}; printed total {money(invoice.total_amount)}.")
        if invoice.notes:
            out(f"    Notes: {invoice.notes}")
        for reason in invoice.review_reasons:
            out(f"    Review reason: {reason}")
        match = MatchResult.objects.filter(invoice=invoice).first()
        if match is None:
            out("    Not matched yet. Run python manage.py match.")
        else:
            out("")
            render_match(out, self.style, invoice, match)
            for write in invoice.tms_writes.all():
                detail = write.reference or write.error
                out(f"    TMS write: {write.get_operation_display()} on {write.shipment_id} [{write.mode}] {write.status} {detail}")

    def show_totals(self, documents):
        runs = ExtractionRun.objects.filter(document__in=documents)
        total = sum((run.estimated_cost_usd for run in runs), start=0)
        self.stdout.write("=" * 78)
        self.stdout.write(f"{documents.count()} document(s), {runs.count()} extraction run(s), total estimated cost ${total:.3f}")

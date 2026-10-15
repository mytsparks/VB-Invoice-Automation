"""Runs extraction over registered documents and stores the results."""
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import transaction
from pydantic import ValidationError

from extraction.adapter import (
    Extractor,
    ExtractorAuthError,
    ExtractorError,
    ExtractorRefused,
    Usage,
)
from extraction.models import ExtractionRun, Invoice, InvoiceLine
from extraction.normalize import (
    normalize_currency,
    normalize_shipment_id,
    parse_amount,
    parse_date,
)
from extraction.pricing import cost_usd, estimate_document_cost
from extraction.prompts import CURRENT_PROMPT
from extraction.schema import CRITICAL_FIELDS, ExtractionResult
from intake.models import Document, ProcessingRun

log = logging.getLogger(__name__)

# 4/3 base64 growth has to fit in the 32 MB request limit.
MAX_FILE_BYTES = 20 * 1024 * 1024


class RunAborted(Exception):
    pass


@dataclass
class ExtractSummary:
    extracted: int = 0
    cached: int = 0
    blocked: int = 0
    failed: int = 0
    non_invoice: int = 0
    sent: int = 0
    spent: Decimal = Decimal("0")
    estimated: Decimal = Decimal("0")
    stopped_reason: str = ""
    lines: list[str] = field(default_factory=list)


def current_invoices():
    """Invoices from the latest successful extraction of each document. Older runs are history."""
    latest = {}
    for run_id, document_id in ExtractionRun.objects.filter(status=ExtractionRun.Status.SUCCESS).order_by("id").values_list("id", "document_id"):
        latest[document_id] = run_id
    return Invoice.objects.filter(extraction_run_id__in=latest.values())


def review_reasons(fields: dict, threshold: float) -> list[str]:
    reasons = []
    for name in CRITICAL_FIELDS:
        detail = fields[name]
        if detail["value"] is None:
            if name != "currency":  # a missing currency is assumed from the shipment during matching
                reasons.append(f"{name} is missing")
        elif detail["confidence"] < threshold:
            reasons.append(f"{name} has low confidence ({detail['confidence']:.2f})")
    return reasons


def store_invoices(document: Document, run: ExtractionRun, result: ExtractionResult, threshold: float) -> None:
    for position, data in enumerate(result.invoices, start=1):
        fields = {
            name: {
                "value": getattr(data, name).value,
                "confidence": getattr(data, name).confidence,
                "rationale": getattr(data, name).rationale,
                "page": getattr(data, name).page,
            }
            for name in (*CRITICAL_FIELDS, "factoring_company")
        }
        reasons = review_reasons(fields, threshold)
        total = parse_amount(fields["total_amount"]["value"])
        invoice_date = parse_date(fields["invoice_date"]["value"])
        shipment_id = normalize_shipment_id(fields["shipment_id"]["value"])
        if fields["shipment_id"]["value"] and not shipment_id:
            reasons.append("shipment_id does not match the 31xxx-xxxxx format")
        if fields["total_amount"]["value"] and total is None:
            reasons.append("total_amount could not be read as a number")
        if fields["invoice_date"]["value"] and invoice_date is None:
            reasons.append("invoice_date is not an unambiguous date, check the printed value")
        if data.overall_confidence < threshold:
            reasons.append(f"overall confidence is low ({data.overall_confidence:.2f})")

        invoice = Invoice.objects.create(
            document=document,
            extraction_run=run,
            position=position,
            shipment_id=shipment_id,
            shipment_id_raw=fields["shipment_id"]["value"] or "",
            carrier_name=fields["carrier_name"]["value"] or "",
            factoring_company=fields["factoring_company"]["value"] or "",
            invoice_number=fields["invoice_number"]["value"] or "",
            invoice_date=invoice_date,
            currency=normalize_currency(fields["currency"]["value"]),
            total_amount=total,
            other_references=[{"label": r.label, "value": r.value} for r in data.other_references],
            overall_confidence=data.overall_confidence,
            field_details=fields,
            notes=data.notes or "",
            review_reasons=reasons,
        )
        InvoiceLine.objects.bulk_create(
            InvoiceLine(
                invoice=invoice,
                position=index,
                charge_type=line.charge_type or "",
                description=line.description or "",
                amount=parse_amount(line.amount),
                confidence=line.confidence,
                page=line.page,
            )
            for index, line in enumerate(data.line_items, start=1)
        )


def _call_with_retry(extractor: Extractor, data: bytes, media_type: str):
    """Call the extractor, retrying once when the output is malformed. Returns (result, raw, usage, attempts, request_id, error)."""
    total = Usage()
    raw, request_id, error, result = "", "", "", None
    attempts = 0
    for attempts in (1, 2):
        response = extractor.extract(data, media_type)
        raw, request_id = response.raw_text, response.request_id
        total.input_tokens += response.usage.input_tokens
        total.output_tokens += response.usage.output_tokens
        total.cache_read_tokens += response.usage.cache_read_tokens
        total.cache_write_tokens += response.usage.cache_write_tokens
        try:
            result = ExtractionResult.model_validate_json(raw)
            error = ""
            break
        except ValidationError as exc:
            error = f"Output did not match the schema ({exc.error_count()} problems)."
    return result, raw, total, attempts, request_id, error


def extract_documents(
    documents,
    extractor: Extractor | None,
    dry_run: bool = False,
    force: bool = False,
    processing_run: ProcessingRun | None = None,
    write=lambda message: None,
) -> ExtractSummary:
    config = settings.APP
    model = config.claude_model
    summary = ExtractSummary()

    for document in documents:
        if document.status == Document.Status.UNSUPPORTED:
            continue
        if document.source == Document.Source.REAL and not config.allow_real_invoices_to_llm:
            summary.blocked += 1
            write(f"  blocked: {document.file_name} is a real file and ALLOW_REAL_INVOICES_TO_LLM is false")
            continue

        prompt_version = extractor.prompt_version if extractor else CURRENT_PROMPT
        if not force and document.extraction_runs.filter(
            status=ExtractionRun.Status.SUCCESS, model=model, prompt_version=prompt_version
        ).exists():
            summary.cached += 1
            write(f"  cached, not sent again: {document.file_name}")
            continue

        estimate = estimate_document_cost(model, document.media_type, document.page_count)
        if summary.sent >= config.max_docs_per_run:
            summary.stopped_reason = f"Reached the per-run document cap of {config.max_docs_per_run}."
            break
        if summary.spent + summary.estimated + estimate > config.run_cost_cap_usd:
            summary.stopped_reason = f"The next document would exceed the ${config.run_cost_cap_usd} run cost cap."
            break

        if dry_run:
            summary.sent += 1
            summary.estimated += estimate
            write(f"  would send: {document.file_name} (about ${estimate:.3f})")
            continue

        path = Path(document.path)
        path = path if path.is_absolute() else Path(settings.BASE_DIR) / path
        if not path.exists() or path.stat().st_size > MAX_FILE_BYTES:
            summary.failed += 1
            document.status = Document.Status.NEEDS_REVIEW
            document.save(update_fields=["status"])
            write(f"  failed: {document.file_name} is missing or larger than 20 MB")
            continue

        summary.sent += 1
        run = ExtractionRun(
            document=document,
            processing_run=processing_run,
            model=model,
            prompt_version=prompt_version,
        )
        try:
            result, raw, usage, attempts, request_id, error = _call_with_retry(
                extractor, path.read_bytes(), document.media_type
            )
        except ExtractorAuthError as exc:
            raise RunAborted(str(exc)) from exc
        except (ExtractorRefused, ExtractorError) as exc:
            run.status = (
                ExtractionRun.Status.REFUSED if isinstance(exc, ExtractorRefused) else ExtractionRun.Status.ERROR
            )
            run.error = str(exc)
            run.save()
            document.status = Document.Status.NEEDS_REVIEW
            document.save(update_fields=["status"])
            summary.failed += 1
            write(f"  failed: {document.file_name} ({exc})")
            continue

        run.raw_output = raw
        run.attempts = attempts
        run.request_id = request_id
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.cache_read_tokens = usage.cache_read_tokens
        run.cache_write_tokens = usage.cache_write_tokens
        run.estimated_cost_usd = cost_usd(
            model, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.cache_write_tokens
        )
        summary.spent += run.estimated_cost_usd
        # Only usage numbers are logged, never document content or extracted values.
        log.info(
            "extraction document_id=%s tokens_in=%s tokens_out=%s cost=%s",
            document.pk, usage.input_tokens, usage.output_tokens, run.estimated_cost_usd,
        )

        with transaction.atomic():
            if result is None:
                run.status = ExtractionRun.Status.INVALID
                run.error = error
                run.save()
                document.status = Document.Status.NEEDS_REVIEW
                document.save(update_fields=["status"])
                summary.failed += 1
                write(f"  failed: {document.file_name} ({error})")
                continue
            run.status = ExtractionRun.Status.SUCCESS
            run.save()
            if result.invoices:
                store_invoices(document, run, result, config.low_confidence_threshold)
                document.status = Document.Status.EXTRACTED
                summary.extracted += 1
                write(f"  extracted: {document.file_name} ({len(result.invoices)} invoice(s), ${run.estimated_cost_usd:.3f})")
            else:
                document.status = Document.Status.NON_INVOICE
                summary.non_invoice += 1
                write(f"  not an invoice ({result.document_type}): {document.file_name}")
            document.save(update_fields=["status"])

    return summary

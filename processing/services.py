"""Sends invoices that passed matching (or were approved by a person) to the TMS.

Each invoice produces two writes, attaching the original file and recording the carrier invoice.
An idempotency key per invoice and operation means a rerun never writes the same thing twice.
Failures are recorded and the run continues, because sandbox errors are expected.
"""
from dataclasses import dataclass, field

from django.conf import settings
from pathlib import Path

from processing.models import TmsWrite
from tms.base import TmsAuthError, TmsClient, TmsError

OPERATIONS = (TmsWrite.Operation.ATTACH_DOCUMENT, TmsWrite.Operation.RECORD_INVOICE)


class ProcessAborted(Exception):
    """The run must stop, for example because credentials were rejected."""


class WriteBudget:
    def __init__(self, limit: int):
        self.remaining = limit

    def use(self) -> None:
        self.remaining -= 1


@dataclass
class ProcessResult:
    status: str  # processed, discrepancy, already_done, failed, dry_run, stopped
    messages: list[str] = field(default_factory=list)


def key_for(invoice, operation) -> str:
    return f"invoice-{invoice.pk}-{operation}"


def is_processed(match, mode: str) -> bool:
    done = set(TmsWrite.objects.filter(invoice=match.invoice, mode=mode, status=TmsWrite.Status.SUCCESS).values_list("operation", flat=True))
    return all(op in done for op in OPERATIONS)


def build_summaries(match) -> dict:
    invoice, document = match.invoice, match.invoice.document
    shipment = match.shipment
    return {
        TmsWrite.Operation.ATTACH_DOCUMENT: {
            "shipment_id": shipment.shipment_id,
            "file_name": document.file_name,
            "media_type": document.media_type,
            "bytes": document.size_bytes,
            "document_type": "Carrier invoice",
        },
        TmsWrite.Operation.RECORD_INVOICE: {
            "shipment_id": shipment.shipment_id,
            "order_id": match.order_id,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            "amount": str(invoice.total_amount),
            "currency": invoice.currency or shipment.currency,
            "carrier": invoice.carrier_name,
            "lines": [{"charge_type": line.charge_type or line.description, "amount": str(line.amount)} for line in invoice.lines.all()],
        },
    }


def _record(match, run, mode, operation, status, summary, **extra) -> TmsWrite:
    return TmsWrite.objects.create(
        invoice=match.invoice, processing_run=run, operation=operation, idempotency_key=key_for(match.invoice, operation),
        mode=mode, shipment_id=match.shipment.shipment_id, status=status, request_summary=summary, **extra,
    )


def process_match(match, tms: TmsClient, budget: WriteBudget, dry_run: bool = False, processing_run=None) -> ProcessResult:
    invoice, mode = match.invoice, tms.mode
    summaries = build_summaries(match)
    done = set(TmsWrite.objects.filter(invoice=invoice, mode=mode, status=TmsWrite.Status.SUCCESS).values_list("operation", flat=True))
    pending = [op for op in OPERATIONS if op not in done]
    if not pending:
        return ProcessResult("already_done", ["Already written to the TMS in an earlier run. Nothing sent."])
    if dry_run:
        return ProcessResult("dry_run", [f"Would {TmsWrite.Operation(op).label.lower()} on {summaries[op]['shipment_id']}" for op in pending])

    shipment = tms.find_shipment(match.shipment.shipment_id)
    if shipment is None:
        error = f"Shipment {match.shipment.shipment_id} no longer exists in the TMS."
        _record(match, processing_run, mode, pending[0], TmsWrite.Status.FAILED, summaries[pending[0]], error=error, http_status=404)
        return ProcessResult("failed", [error])

    result = ProcessResult("processed")
    for operation in pending:
        if budget.remaining <= 0:
            result.status = "stopped"
            result.messages.append("The per-run write cap was reached before this invoice finished.")
            return result
        budget.use()
        summary = summaries[operation]
        try:
            if operation == TmsWrite.Operation.ATTACH_DOCUMENT:
                path = Path(invoice.document.path)
                path = path if path.is_absolute() else Path(settings.BASE_DIR) / path
                if not path.exists():
                    raise TmsError(f"The original file {invoice.document.file_name} is missing from disk.")
                write = tms.attach_document(shipment, invoice.document.file_name, invoice.document.media_type, path.read_bytes(), summary)
            else:
                write = tms.record_invoice(shipment, match.order_id, summary)
        except TmsAuthError as exc:
            _record(match, processing_run, mode, operation, TmsWrite.Status.FAILED, summary, error=str(exc), http_status=401)
            raise ProcessAborted(str(exc)) from exc
        except TmsError as exc:
            _record(match, processing_run, mode, operation, TmsWrite.Status.FAILED, summary, error=str(exc), http_status=getattr(exc, "status_code", None))
            result.status = "failed"
            result.messages.append(f"{TmsWrite.Operation(operation).label} failed: {exc}")
            return result
        _record(match, processing_run, mode, operation, TmsWrite.Status.SUCCESS, summary,
                http_status=write.status_code, reference=write.reference, response=write.response)
        result.messages.append(f"{TmsWrite.Operation(operation).label}: ok ({write.reference})")

    # Read the shipment back and confirm both changes are visible.
    refreshed = tms.find_shipment(match.shipment.shipment_id)
    visible_document = refreshed is not None and invoice.document.file_name in refreshed.documents
    visible_invoice = refreshed is not None and any(
        existing.invoice_number == invoice.invoice_number for order in refreshed.carrier_orders for existing in order.invoices
    )
    TmsWrite.objects.filter(invoice=invoice, mode=mode, status=TmsWrite.Status.SUCCESS).update(readback_ok=visible_document and visible_invoice)
    if not (visible_document and visible_invoice):
        result.status = "discrepancy"
        missing = [name for name, seen in (("document", visible_document), ("invoice", visible_invoice)) if not seen]
        result.messages.append(f"Read back from the TMS did not show the {' or '.join(missing)}. Check the shipment.")
    else:
        result.messages.append("Read back confirmed the document and invoice are on the shipment.")
    return result

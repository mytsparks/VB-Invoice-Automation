"""Typed output schema the model must follow. Validated in code after every call.

Values are returned as printed text. Turning them into dates and decimals is
done in normalize.py, and arithmetic checks belong to deterministic code, so the
model is never asked to calculate or correct anything.
"""
from typing import Literal

from pydantic import BaseModel, field_validator

DocumentType = Literal["carrier_invoice", "bill_of_lading", "proof_of_delivery", "statement", "other"]


def _check_confidence(value: float) -> float:
    if not 0 <= value <= 1:
        raise ValueError("confidence must be between 0 and 1")
    return value


class FieldValue(BaseModel):
    value: str | None
    confidence: float
    rationale: str
    page: int | None

    _confidence = field_validator("confidence")(_check_confidence)


class Reference(BaseModel):
    label: str
    value: str


class LineItem(BaseModel):
    charge_type: str | None
    description: str | None
    amount: str | None
    confidence: float
    page: int | None

    _confidence = field_validator("confidence")(_check_confidence)


class InvoiceData(BaseModel):
    shipment_id: FieldValue
    carrier_name: FieldValue
    invoice_number: FieldValue
    invoice_date: FieldValue
    currency: FieldValue
    total_amount: FieldValue
    other_references: list[Reference]
    line_items: list[LineItem]
    overall_confidence: float
    notes: str | None

    _confidence = field_validator("overall_confidence")(_check_confidence)


class ExtractionResult(BaseModel):
    document_type: DocumentType
    page_count: int
    invoices: list[InvoiceData]
    notes: str | None


# Fields checked against the confidence threshold and for presence.
CRITICAL_FIELDS = ("shipment_id", "carrier_name", "invoice_number", "invoice_date", "currency", "total_amount")

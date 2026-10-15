"""The TMS client interface. Matching and processing depend only on this shape, so the
simulated client and the Turvo sandbox client are interchangeable."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


class TmsError(Exception):
    """Base class for TMS failures. Messages must never contain secrets."""


class TmsAuthError(TmsError):
    """Credentials were rejected (401 or 403). The run stops instead of retrying."""


class TmsRejected(TmsError):
    """The TMS refused a request, for example a validation error on a write."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class TmsUnavailable(TmsError):
    """The TMS could not be reached or returned a server error."""


@dataclass(frozen=True)
class CostLine:
    charge_type: str
    amount: Decimal
    qty: Decimal = Decimal("1")


@dataclass(frozen=True)
class ExistingInvoice:
    invoice_number: str
    amount: Decimal | None = None
    document_id: str = ""


@dataclass
class CarrierOrder:
    order_id: int | None
    carrier_name: str
    carrier_id: int | None = None
    currency: str = ""
    total: Decimal | None = None
    lines: list[CostLine] = field(default_factory=list)
    invoices: list[ExistingInvoice] = field(default_factory=list)


@dataclass
class Shipment:
    turvo_id: int | None
    shipment_id: str
    status: str = ""
    container_number: str = ""
    carrier_orders: list[CarrierOrder] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)


@dataclass
class WriteResult:
    operation: str
    status_code: int
    reference: str
    response: dict


class TmsClient(Protocol):
    mode: str

    def check(self) -> str:
        """Return a short description of what is reachable, or raise TmsError."""
        ...

    def find_shipment(self, shipment_id: str) -> Shipment | None:
        """Exact lookup by the 31xxx-xxxxx shipment ID. None when it does not exist."""
        ...

    def search_shipments(self, text: str, limit: int = 5) -> list[Shipment]:
        """Shipments whose ID is close to the text. Used to suggest corrections, never to auto match."""
        ...

    def attach_document(self, shipment: Shipment, file_name: str, media_type: str, data: bytes, metadata: dict) -> WriteResult:
        """Attach the original invoice file to the shipment."""
        ...

    def record_invoice(self, shipment: Shipment, order_id: int | None, invoice: dict) -> WriteResult:
        """Record the carrier invoice (number, date, amount, currency, lines) against the carrier order."""
        ...

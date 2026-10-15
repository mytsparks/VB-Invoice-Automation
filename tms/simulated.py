"""A stand-in for the Turvo sandbox, built from fixture files.

Each fixture is a Turvo style shipment response saved as JSON. An optional top level
"simulation" object can make writes fail, so error handling is exercised before
sandbox access exists, for example
    "simulation": {"reject_attach_document": "Document type not allowed"}
    "simulation": {"auth_error": true}
Fixture files are only read. Writes are never applied to them.
"""
import copy
import json
import uuid
from collections.abc import Callable
from pathlib import Path

from tms.base import (
    ExistingInvoice,
    Shipment,
    TmsAuthError,
    TmsError,
    TmsRejected,
    WriteResult,
)
from tms.turvo_format import parse_shipment


def close_ids(text: str, known: list[str], limit: int = 5) -> list[str]:
    """IDs that differ from the text by one wrong character, one swap of neighbors, or a shared prefix."""
    text = text.strip()
    found = []
    for candidate in known:
        if candidate == text:
            continue
        substitutions = len(candidate) == len(text) and sum(a != b for a, b in zip(candidate, text)) == 1
        swapped = False
        if len(candidate) == len(text):
            diffs = [i for i, (a, b) in enumerate(zip(candidate, text)) if a != b]
            swapped = len(diffs) == 2 and diffs[1] == diffs[0] + 1 and candidate[diffs[0]] == text[diffs[1]] and candidate[diffs[1]] == text[diffs[0]]
        if substitutions or swapped:
            found.append(candidate)
    return found[:limit]


class SimulatedTms:
    mode = "mock"

    def __init__(self, fixture_dirs: list[Path], ledger: Callable[[str], list[dict]] | None = None):
        """ledger returns the successful writes already recorded for a shipment ID, so reads
        reflect earlier processing runs the way the real sandbox would."""
        self._payloads: dict[str, dict] = {}
        self.load_errors: list[str] = []
        for directory in fixture_dirs:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    shipment_id = payload.get("details", payload).get("customId")
                    if not shipment_id:
                        raise ValueError("no customId")
                    self._payloads[shipment_id] = payload
                except (OSError, ValueError) as exc:
                    self.load_errors.append(f"{path.name}: {exc}")
        self._ledger = ledger or (lambda shipment_id: [])

    def check(self) -> str:
        message = f"Simulated TMS with {len(self._payloads)} shipment fixture(s)"
        if self.load_errors:
            raise TmsError(f"{message}, but {len(self.load_errors)} file(s) could not be read: {'; '.join(self.load_errors)}")
        return message

    def find_shipment(self, shipment_id: str) -> Shipment | None:
        payload = self._payloads.get(shipment_id)
        if payload is None:
            return None
        shipment = parse_shipment(copy.deepcopy(payload))
        for write in self._ledger(shipment_id):
            if write["operation"] == "attach_document":
                shipment.documents.append(write["request_summary"].get("file_name", write["reference"]))
            elif write["operation"] == "record_invoice" and shipment.carrier_orders:
                summary = write["request_summary"]
                order = next((o for o in shipment.carrier_orders if o.order_id == summary.get("order_id")), shipment.carrier_orders[0])
                order.invoices.append(ExistingInvoice(invoice_number=summary.get("invoice_number", ""), document_id=write["reference"]))
        return shipment

    def search_shipments(self, text: str, limit: int = 5) -> list[Shipment]:
        ids = close_ids(text, list(self._payloads), limit)
        return [self.find_shipment(shipment_id) for shipment_id in ids]

    def _simulation(self, shipment: Shipment) -> dict:
        return self._payloads.get(shipment.shipment_id, {}).get("simulation", {})

    def _check_writable(self, shipment: Shipment, operation: str) -> None:
        simulation = self._simulation(shipment)
        if simulation.get("auth_error"):
            raise TmsAuthError("The simulated TMS rejected the credentials (401).")
        if shipment.shipment_id not in self._payloads:
            raise TmsRejected(f"Shipment {shipment.shipment_id} does not exist.", 404)
        message = simulation.get(f"reject_{operation}")
        if message:
            raise TmsRejected(message, 422)

    def attach_document(self, shipment, file_name, media_type, data, metadata) -> WriteResult:
        self._check_writable(shipment, "attach_document")
        reference = f"SIM-DOC-{uuid.uuid4().hex[:10]}"
        return WriteResult("attach_document", 200, reference, {
            "Status": "SUCCESS",
            "details": {"documentId": reference, "contextType": "SHIPMENT", "contextId": shipment.turvo_id, "documentName": file_name, "bytes": len(data)},
        })

    def record_invoice(self, shipment, order_id, invoice) -> WriteResult:
        self._check_writable(shipment, "record_invoice")
        reference = f"SIM-INV-{uuid.uuid4().hex[:10]}"
        return WriteResult("record_invoice", 201, reference, {
            "Status": "SUCCESS",
            "details": {"respMsg": "SUCCESS_SAVE", "shipmentId": shipment.turvo_id, "accountOrderId": order_id, "invoiceNo": invoice.get("invoice_number")},
        })

"""Reads a Turvo "Retrieve a Shipment" response (docs/reference/APIspec.json) into our Shipment type.

The simulated TMS fixtures use the same JSON shape as the real API, so this parser is
shared and the sandbox client will not need a second mapping.
"""
from decimal import Decimal, InvalidOperation

from tms.base import CarrierOrder, CostLine, ExistingInvoice, Shipment


def _money(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _key_value(node) -> str:
    return (node or {}).get("value", "") if isinstance(node, dict) else ""


def _parse_order(order: dict) -> CarrierOrder:
    costs = order.get("costs") or {}
    lines = []
    for item in costs.get("lineItem") or []:
        if item.get("deleted"):
            continue
        amount = _money(item.get("amount"))
        if amount is None:
            continue
        lines.append(CostLine(
            charge_type=_key_value(item.get("code")),
            amount=amount,
            qty=_money(item.get("qty")) or Decimal("1"),
        ))
    total = _money(costs.get("totalAmount"))
    if total is None and lines:
        total = sum((line.amount for line in lines), Decimal("0"))
    invoices = []
    for payment in order.get("payment") or []:
        invoice = payment.get("invoice") or {}
        if invoice.get("invoiceNo"):
            invoices.append(ExistingInvoice(
                invoice_number=str(invoice["invoiceNo"]),
                amount=_money(payment.get("amount")),
                document_id=str(invoice.get("documentId", "")),
            ))
    carrier = order.get("carrier") or {}
    return CarrierOrder(
        order_id=order.get("id"),
        carrier_name=carrier.get("name", ""),
        carrier_id=carrier.get("id"),
        currency=_key_value(costs.get("transactionCurrency")),
        total=total,
        lines=lines,
        invoices=invoices,
    )


def parse_shipment(payload: dict) -> Shipment:
    details = payload.get("details", payload)
    containers = [m.get("containerNumber") for m in details.get("modeInfo") or [] if m.get("containerNumber")]
    status = details.get("status") or {}
    return Shipment(
        turvo_id=details.get("id"),
        shipment_id=details.get("customId", ""),
        status=_key_value(status.get("code")),
        container_number=containers[0] if containers else "",
        carrier_orders=[_parse_order(o) for o in details.get("carrierOrder") or [] if not o.get("deleted")],
    )

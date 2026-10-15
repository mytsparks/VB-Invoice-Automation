"""Compares an extracted invoice with the shipment in the TMS and decides ready or needs review.

Everything here is deterministic. The model is never asked to judge money, identity or duplicates.
Any flag, or a missing shipment, means the invoice needs review.
"""
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from extraction.normalize import normalize_shipment_id
from extraction.schema import CRITICAL_FIELDS
from extraction.services import current_invoices
from matching.models import CarrierAlias, Flag, FlagType, MatchResult, ShipmentCostLine, ShipmentRecord, ToleranceRule
from matching.names import charge_key, names_match, normalize_name
from tms.base import CarrierOrder, Shipment

REQUIRED_FIELDS = ("shipment_id", "carrier_name", "invoice_number", "invoice_date", "total_amount")
PASS, FAIL, WARN, SKIP = "pass", "fail", "warn", "skip"


@dataclass
class DefaultRule:
    """Used only when the tolerance table is empty."""

    amount_pct: Decimal = Decimal("1")
    amount_fixed: Decimal = Decimal("5")
    min_confidence: float = 0.85
    pk = None


@dataclass
class FlagData:
    code: str
    field: str = ""
    invoice_value: str = ""
    shipment_value: str = ""
    rule: str = ""
    explanation: str = ""


@dataclass
class Row:
    field: str
    invoice: str
    turvo: str
    result: str


@dataclass
class Evaluation:
    shipment: Shipment | None = None
    order: CarrierOrder | None = None
    rows: list[Row] = field(default_factory=list)
    flags: list[FlagData] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    rule: object = None
    shipment_confirmed: bool = False

    @property
    def outcome(self) -> str:
        return MatchResult.Outcome.NEEDS_REVIEW if self.flags or self.shipment is None else MatchResult.Outcome.READY


def money(value) -> str:
    return "-" if value is None else f"{value:,.2f}"


def get_rule():
    rule = ToleranceRule.objects.filter(active=True, carrier=None).order_by("-version").first()
    return rule or DefaultRule()


def allowed_difference(rule, reference: Decimal) -> Decimal:
    """Percentage of the TMS amount or the fixed amount, whichever is greater."""
    return max(abs(reference) * Decimal(rule.amount_pct) / Decimal(100), Decimal(rule.amount_fixed))


def _aliases() -> dict[str, str]:
    return {normalize_name(a.alias): normalize_name(a.carrier.name) for a in CarrierAlias.objects.select_related("carrier")}


def suggest_shipments(invoice, tms, tried: str) -> list[str]:
    """Possible corrections for a shipment ID that was missing or not found. A person confirms any of them."""
    aliases = _aliases()
    shipments: dict[str, Shipment] = {}
    for text in (tried, normalize_shipment_id(invoice.shipment_id_raw), invoice.shipment_id_raw):
        if text:
            for shipment in tms.search_shipments(text):
                shipments[shipment.shipment_id] = shipment
    for reference in invoice.other_references:
        found = normalize_shipment_id(reference.get("value"))
        if found and found != tried and found not in shipments:
            shipment = tms.find_shipment(found)
            if shipment:
                shipments[found] = shipment
    # Neighboring IDs are often one digit apart, so prefer shipments whose carrier fits the invoice.
    names = [name for name in (invoice.carrier_name, invoice.factoring_company) if name]
    same_carrier = [
        sid for sid, shipment in shipments.items()
        if any(names_match(names, order.carrier_name, aliases)[0] for order in shipment.carrier_orders)
    ] if names else []
    pool = same_carrier or list(shipments)
    if invoice.total_amount is not None:
        rule = get_rule()
        fits_amount = [
            sid for sid in pool
            if any(o.total is not None and abs(invoice.total_amount - o.total) <= allowed_difference(rule, o.total) for o in shipments[sid].carrier_orders)
        ]
        pool = fits_amount or pool
    return pool


def duplicate_reasons(invoice, order: CarrierOrder | None, shipment: Shipment | None) -> list[str]:
    reasons = []
    number = invoice.invoice_number.strip()
    if number:
        same_number = current_invoices().filter(invoice_number__iexact=number, pk__lt=invoice.pk).exclude(pk=invoice.pk)
        for other in same_number:
            if names_match([invoice.carrier_name], other.carrier_name)[0]:
                reasons.append(f"Invoice {number} from the same carrier was already extracted from {other.document.file_name}.")
        if order:
            for existing in order.invoices:
                if existing.invoice_number.strip().lower() == number.lower():
                    reasons.append(f"Invoice {number} is already recorded on shipment {shipment.shipment_id} in the TMS.")
    if shipment and invoice.total_amount is not None:
        twins = MatchResult.objects.filter(
            shipment__shipment_id=shipment.shipment_id, invoice__total_amount=invoice.total_amount, invoice__pk__lt=invoice.pk
        ).exclude(invoice=invoice)
        current = set(current_invoices().values_list("pk", flat=True))
        for twin in twins:
            if twin.invoice_id in current and twin.invoice.invoice_number != invoice.invoice_number:
                reasons.append(
                    f"Possible duplicate. Invoice {twin.invoice.invoice_number or twin.invoice_id} already covers the same shipment for the same amount."
                )
    return reasons


def _invoice_container(invoice) -> str:
    for reference in invoice.other_references:
        if "container" in reference.get("label", "").lower():
            return reference.get("value", "").strip()
    return ""


def evaluate(invoice, tms, config, shipment_id_override: str = "") -> Evaluation:
    rule = get_rule()
    result = Evaluation(rule=rule)
    details = invoice.field_details
    tolerance_text = f"{rule.amount_pct}% or {rule.amount_fixed}, whichever is greater"

    missing = [
        name for name, value in (
            ("shipment_id", invoice.shipment_id), ("carrier_name", invoice.carrier_name),
            ("invoice_number", invoice.invoice_number), ("invoice_date", invoice.invoice_date),
            ("total_amount", invoice.total_amount),
        ) if not value and value != 0
    ]
    if missing:
        result.flags.append(FlagData(
            "missing_required_field", ", ".join(missing), rule="Required fields must be present",
            explanation=f"Not found or not readable on the invoice: {', '.join(missing)}.",
        ))

    uncertain = [
        f"{name} ({details[name]['confidence']:.2f})" for name in CRITICAL_FIELDS
        if name in details and details[name]["value"] is not None and details[name]["confidence"] < rule.min_confidence
    ]
    if invoice.overall_confidence < rule.min_confidence:
        uncertain.append(f"overall ({invoice.overall_confidence:.2f})")
    if uncertain:
        result.flags.append(FlagData(
            "low_confidence", ", ".join(uncertain), rule=f"Confidence below {rule.min_confidence}",
            explanation="The reader was unsure about " + ", ".join(uncertain) + ". Check these against the document.",
        ))

    sid = shipment_id_override or invoice.shipment_id
    shipment = tms.find_shipment(sid) if sid else None
    result.shipment_confirmed = bool(shipment_id_override and shipment)
    if shipment is None:
        result.suggestions = suggest_shipments(invoice, tms, sid)
        reason = f"Shipment {sid} was not found in the TMS." if sid else "No shipment ID in the 31xxx-xxxxx format was found on the invoice."
        if result.suggestions:
            reason += " Possible matches: " + ", ".join(result.suggestions) + "."
        result.flags.append(FlagData("no_matching_shipment", "shipment_id", sid, "", "Exact match on shipment ID", reason))
        result.rows.append(Row("Shipment number", sid or "Not found", "Not found", FAIL))
        for reason_text in duplicate_reasons(invoice, None, None):
            result.flags.append(FlagData("duplicate_invoice", "invoice_number", invoice.invoice_number, "", "Same carrier and invoice number", reason_text))
        return result

    result.shipment = shipment
    if result.shipment_confirmed:
        result.notes.append(f"Shipment {sid} was chosen by a person, not read from the invoice.")
    result.rows.append(Row("Shipment number", sid, shipment.shipment_id, PASS))

    # Carrier. The invoice can name the carrier, a factoring company, or both.
    aliases = _aliases()
    invoice_names = [name for name in (invoice.carrier_name, invoice.factoring_company) if name]
    best = (False, -1.0, "", None)
    for order in shipment.carrier_orders:
        matched, score, which = names_match(invoice_names, order.carrier_name, aliases)
        if (matched, score) > best[:2]:
            best = (matched, score, which, order)
    matched, _, which, order = best
    order = order or (shipment.carrier_orders[0] if shipment.carrier_orders else None)
    result.order = order
    shown_invoice_carrier = invoice.carrier_name or invoice.factoring_company or "Not found"
    if invoice.factoring_company and invoice.carrier_name:
        shown_invoice_carrier += f" (via {invoice.factoring_company})"
    if order is None:
        result.flags.append(FlagData("carrier_mismatch", "carrier", shown_invoice_carrier, "None", "Shipment needs a carrier order", "The shipment has no carrier order to compare with."))
        result.rows.append(Row("Carrier", shown_invoice_carrier, "None", FAIL))
        return result
    if matched:
        result.rows.append(Row("Carrier", shown_invoice_carrier, order.carrier_name, PASS))
        if which and which != invoice.carrier_name:
            result.notes.append(f"Carrier matched on the factoring company name '{which}'.")
    else:
        result.rows.append(Row("Carrier", shown_invoice_carrier, order.carrier_name, FAIL))
        result.flags.append(FlagData(
            "carrier_mismatch", "carrier", shown_invoice_carrier, order.carrier_name, "Carrier identity must match",
            f"The invoice is from '{shown_invoice_carrier}' but the shipment's carrier is '{order.carrier_name}'.",
        ))

    # Currency. A missing currency is assumed from the shipment and noted, never silently accepted as a mismatch.
    if invoice.currency and order.currency and invoice.currency != order.currency:
        result.rows.append(Row("Currency", invoice.currency, order.currency, FAIL))
        result.flags.append(FlagData(
            "currency_mismatch", "currency", invoice.currency, order.currency, "Currency must match exactly, no conversion",
            f"The invoice is in {invoice.currency} and the shipment is in {order.currency}.",
        ))
    elif not invoice.currency:
        result.rows.append(Row("Currency", f"Not printed (assumed {order.currency or 'unknown'})", order.currency or "Not set", WARN))
        result.notes.append(f"No currency was printed on the invoice. {order.currency or 'No currency'} was assumed from the shipment.")
    else:
        result.rows.append(Row("Currency", invoice.currency, order.currency or "Not set", PASS))

    # Total amount
    if invoice.total_amount is not None and order.total is not None:
        diff = invoice.total_amount - order.total
        allowed = allowed_difference(rule, order.total)
        if abs(diff) > allowed:
            direction = "above" if diff > 0 else "below"
            result.rows.append(Row("Total amount", money(invoice.total_amount), money(order.total), FAIL))
            result.flags.append(FlagData(
                "amount_over_tolerance", "total_amount", money(invoice.total_amount), money(order.total), tolerance_text,
                f"The invoice is {money(abs(diff))} {direction} the shipment total. The allowed difference is {money(allowed)}.",
            ))
        else:
            result.rows.append(Row("Total amount", money(invoice.total_amount), money(order.total), PASS))
    else:
        result.rows.append(Row("Total amount", money(invoice.total_amount), money(order.total), SKIP))

    # Container is never required on the invoice. When it is printed, it must agree with the shipment.
    container = _invoice_container(invoice)
    if container and shipment.container_number:
        same = container.replace(" ", "").upper() == shipment.container_number.replace(" ", "").upper()
        result.rows.append(Row("Container number", container, shipment.container_number, PASS if same else FAIL))
        if not same:
            result.flags.append(FlagData(
                "no_matching_shipment", "container_number", container, shipment.container_number, "Printed container must agree with the shipment",
                "The container printed on the invoice differs from the one on the shipment, so this may be the wrong shipment.",
            ))
    else:
        result.rows.append(Row("Container number", container or "Not printed", shipment.container_number or "Not set", SKIP))

    # Line items
    lines = list(invoice.lines.all())
    if lines:
        invoice_totals: dict[str, Decimal] = {}
        labels: dict[str, str] = {}
        for line in lines:
            if line.amount is None:
                continue
            key = charge_key(line.charge_type, line.description)
            invoice_totals[key] = invoice_totals.get(key, Decimal("0")) + line.amount
            labels.setdefault(key, line.charge_type or line.description or "Freight")
        shipment_totals: dict[str, Decimal] = {}
        shipment_labels: dict[str, str] = {}
        for line in order.lines:
            key = charge_key(line.charge_type)
            shipment_totals[key] = shipment_totals.get(key, Decimal("0")) + line.amount
            shipment_labels.setdefault(key, line.charge_type)
        for key, amount in invoice_totals.items():
            label = labels[key]
            if key in shipment_totals:
                diff = amount - shipment_totals[key]
                allowed = allowed_difference(rule, shipment_totals[key])
                if abs(diff) > allowed:
                    result.flags.append(FlagData(
                        "amount_over_tolerance", f"line: {label}", money(amount), money(shipment_totals[key]), tolerance_text,
                        f"The {label} charge is {money(abs(diff))} {'above' if diff > 0 else 'below'} the shipment. The allowed difference is {money(allowed)}.",
                    ))
                    result.rows.append(Row(f"  {label}", money(amount), money(shipment_totals[key]), FAIL))
                else:
                    result.rows.append(Row(f"  {label}", money(amount), money(shipment_totals[key]), PASS))
            else:
                result.rows.append(Row(f"  {label}", money(amount), "Not on shipment", FAIL))
                result.flags.append(FlagData(
                    "unknown_accessorial", f"line: {label}", money(amount), "", "Charges must exist on the shipment",
                    f"The invoice bills {label} ({money(amount)}), which is not on the shipment's cost lines.",
                ))
        for key, amount in shipment_totals.items():
            if key not in invoice_totals:
                result.notes.append(f"The shipment lists {shipment_labels[key]} ({money(amount)}) that this invoice does not bill.")
        if invoice.total_amount is not None:
            line_sum = sum(invoice_totals.values(), Decimal("0"))
            if abs(line_sum - invoice.total_amount) > Decimal("0.01"):
                result.flags.append(FlagData(
                    "math_mismatch", "total_amount", money(invoice.total_amount), money(line_sum), "Lines must add up to the total",
                    f"The line items add up to {money(line_sum)} but the invoice total is {money(invoice.total_amount)}.",
                ))
    else:
        result.notes.append("No line items were extracted, so charge level checks were skipped.")

    for reason in duplicate_reasons(invoice, order, shipment):
        result.flags.append(FlagData("duplicate_invoice", "invoice_number", invoice.invoice_number, "", "Same carrier and invoice number, or same shipment and amount", reason))

    # A possible_fraud detector is not built yet. The flag type exists for the later phase.
    return result


@transaction.atomic
def save_match(invoice, result: Evaluation) -> MatchResult:
    record = None
    if result.shipment:
        shipment, order = result.shipment, result.order
        raw = json.loads(json.dumps(asdict(shipment), default=str))
        record, _ = ShipmentRecord.objects.update_or_create(
            shipment_id=shipment.shipment_id,
            defaults={
                "turvo_id": str(shipment.turvo_id or ""),
                "carrier_name": order.carrier_name if order else "",
                "container_number": shipment.container_number,
                "currency": order.currency if order else "",
                "total_cost": order.total if order else None,
                "status": shipment.status,
                "raw": raw,
            },
        )
        record.cost_lines.all().delete()
        if order:
            ShipmentCostLine.objects.bulk_create(
                ShipmentCostLine(shipment=record, charge_type=line.charge_type, amount=line.amount, currency=order.currency)
                for line in order.lines
            )
    rule = result.rule if isinstance(result.rule, ToleranceRule) else None
    match, _ = MatchResult.objects.update_or_create(
        invoice=invoice,
        defaults={
            "shipment": record,
            "tolerance_rule": rule,
            "outcome": result.outcome,
            "order_id": result.order.order_id if result.order else None,
            "comparison": [asdict(row) for row in result.rows],
            "notes": result.notes,
            "suggestions": result.suggestions,
            "shipment_confirmed_by_user": result.shipment_confirmed,
            "override_note": "",
            "overridden_at": None,
        },
    )
    match.flags.all().delete()
    flag_types = {flag_type.code: flag_type for flag_type in FlagType.objects.all()}
    Flag.objects.bulk_create(
        Flag(
            match_result=match, flag_type=flag_types[flag.code], field=flag.field, invoice_value=flag.invoice_value,
            shipment_value=flag.shipment_value, rule=flag.rule, explanation=flag.explanation,
        )
        for flag in result.flags
    )
    return match


def override(match: MatchResult, note: str) -> None:
    """A person approves an invoice that has flags. The note is required and kept."""
    match.outcome = MatchResult.Outcome.OVERRIDDEN
    match.override_note = note
    match.overridden_at = timezone.now()
    match.save(update_fields=["outcome", "override_note", "overridden_at"])

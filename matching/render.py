"""Text layout for match results. The comparison table mirrors the invoice review wireframe."""
RESULT_LABEL = {"pass": "PASS", "fail": "FAIL", "warn": "ASSUMED", "skip": "SKIP"}


def result_text(style, result: str) -> str:
    label = RESULT_LABEL.get(result, result.upper())
    if result == "pass":
        return style.SUCCESS(label)
    if result == "fail":
        return style.ERROR(label)
    if result == "warn":
        return style.WARNING(label)
    return label


def render_header(write, style, invoice) -> None:
    shown = [invoice.carrier_name or invoice.factoring_company or "Unknown carrier"]
    write(f"Invoice {invoice.invoice_number or '(no number)'}  {shown[0]}  [{invoice.document.file_name}]")


def render_match(write, style, invoice, match, show_comparison: bool = True) -> None:
    render_header(write, style, invoice)
    if match.shipment:
        extra = f"  Turvo ID {match.shipment.turvo_id}" if match.shipment.turvo_id else ""
        write(f"  Shipment {match.shipment.shipment_id}{extra}  status: {match.shipment.status or 'unknown'}")
    else:
        write("  No shipment matched.")
    if show_comparison and match.comparison:
        write(f"  {'Field':<18}{'Invoice':<34}{'TMS':<30}Result")
        for row in match.comparison:
            write(f"  {row['field']:<18}{row['invoice'][:32]:<34}{row['turvo'][:28]:<30}{result_text(style, row['result'])}")
    for flag in match.flags.select_related("flag_type"):
        where = f" ({flag.field})" if flag.field else ""
        write(style.ERROR(f"  ! {flag.flag_type.name}") + where)
        write(f"      {flag.explanation}")
        if flag.rule:
            write(f"      Rule: {flag.rule}")
    for note in match.notes:
        write(f"  Note: {note}")
    if match.suggestions:
        write("  Suggested shipments: " + ", ".join(match.suggestions))
    outcome = match.get_outcome_display().upper()
    colored = style.SUCCESS(outcome) if match.outcome == "ready" else style.WARNING(outcome)
    if match.outcome == "overridden":
        write(f"  Outcome: {colored}. Note: {match.override_note}")
    else:
        write(f"  Outcome: {colored}")

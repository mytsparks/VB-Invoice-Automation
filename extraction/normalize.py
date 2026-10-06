"""Turn printed text into typed values. Anything that cannot be read cleanly becomes None."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

SHIPMENT_ID_PATTERN = re.compile(r"\b(31\d{3})\s*-\s*(\d{5})\b")


def parse_amount(text: str | None) -> Decimal | None:
    if not text:
        return None
    cleaned = text.strip()
    negative = cleaned.startswith("(") and cleaned.endswith(")") or cleaned.endswith("-") or cleaned.upper().endswith("CR")
    cleaned = re.sub(r"[^\d.,-]", "", cleaned).strip("-")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):  # European style 1.234,56
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        head, _, tail = cleaned.rpartition(",")
        cleaned = head.replace(",", "") + "." + tail if len(tail) == 2 else cleaned.replace(",", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if text.strip().startswith("-"):
        negative = True
    return -abs(amount) if negative else amount


def parse_date(text: str | None) -> date | None:
    """Only ISO dates are trusted. The prompt asks for ISO and null when the order is ambiguous."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_shipment_id(text: str | None) -> str:
    match = SHIPMENT_ID_PATTERN.search(text or "")
    return f"{match.group(1)}-{match.group(2)}" if match else ""


def normalize_currency(text: str | None) -> str:
    code = (text or "").strip().upper()
    return code if re.fullmatch(r"[A-Z]{3}", code) else ""

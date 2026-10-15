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
    """Parse a printed date. Numeric dates are accepted only when the day and month order is clear.

    A date like 03/04/2026 returns None so it goes to review instead of being guessed.
    """
    if not text:
        return None
    cleaned = text.strip()
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", cleaned)
    if not match:
        return None
    first, second, year = (int(part) for part in match.groups())
    if first > 12 >= second:
        day, month = first, second
    elif second > 12 >= first:
        month, day = first, second
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def normalize_shipment_id(text: str | None) -> str:
    match = SHIPMENT_ID_PATTERN.search(text or "")
    return f"{match.group(1)}-{match.group(2)}" if match else ""


def normalize_currency(text: str | None) -> str:
    code = (text or "").strip().upper()
    return code if re.fullmatch(r"[A-Z]{3}", code) else ""

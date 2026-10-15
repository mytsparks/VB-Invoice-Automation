"""Carrier name and charge type normalization used by matching."""
import re
from difflib import SequenceMatcher

LEGAL_WORDS = {"llc", "inc", "ltd", "co", "corp", "corporation", "company", "lp", "llp", "limited", "incorporated", "the"}
DBA_SPLIT = re.compile(r"\bd\s*/\s*b\s*/\s*a\b|\bdba\b|\bc/o\b", re.IGNORECASE)


def normalize_name(name: str) -> str:
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(word for word in text.split() if word not in LEGAL_WORDS)


def name_variants(name: str) -> list[str]:
    """A name like 'A LLC d/b/a B' stands for both A and B."""
    parts = [part for part in DBA_SPLIT.split(name or "") if part.strip()]
    return [normalized for normalized in (normalize_name(part) for part in parts) if normalized]


def names_match(invoice_names: list[str], shipment_name: str, aliases: dict[str, str] | None = None) -> tuple[bool, float, str]:
    """Return (matched, best score, which invoice name matched).

    aliases maps a normalized alias to a normalized canonical name, filled from CarrierAlias.
    """
    aliases = aliases or {}
    target = normalize_name(shipment_name)
    target = aliases.get(target, target)
    best, best_name = 0.0, ""
    for original in invoice_names:
        for variant in name_variants(original):
            variant = aliases.get(variant, variant)
            if not variant or not target:
                continue
            if variant == target:
                return True, 1.0, original
            score = SequenceMatcher(None, variant, target).ratio()
            if f" {variant} " in f" {target} " or f" {target} " in f" {variant} ":
                score = max(score, 0.9)
            if score > best:
                best, best_name = score, original
    return best >= 0.88, best, best_name


FREIGHT_WORDS = {"freight", "linehaul", "haul", "transportation", "trucking", "drayage", "flat", "base", "line"}


def charge_key(charge_type: str | None, description: str | None = "") -> str:
    """Group printed charge names so 'Fuel Surcharge' and 'FSC' compare as the same charge.

    A line with no charge name is treated as the base freight charge.
    """
    text = re.sub(r"[^a-z0-9 ]+", " ", (charge_type or "").lower())
    words = set(text.split())
    if not words:
        return "freight"
    if "fuel" in words or "fsc" in words:
        return "fuel"
    if "chassis" in words:
        return "chassis"
    if "detention" in words or "demurrage" in words:
        return "detention"
    if words & FREIGHT_WORDS:
        return "freight"
    return " ".join(sorted(words))

"""Estimated API cost. Prices are USD per million tokens (input, output)."""
from decimal import Decimal

PRICES = {
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-sonnet-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "claude-fable-5-1": (Decimal("10.00"), Decimal("50.00")),
}

# Rough per-document token guesses for a dry run. Real usage is recorded after each call.
PROMPT_TOKENS = 3000
TOKENS_PER_PAGE = 2500
TOKENS_PER_IMAGE = 1600
EXPECTED_OUTPUT_TOKENS = 3000


def is_known_model(model: str) -> bool:
    return model in PRICES


def _rates(model: str) -> tuple[Decimal, Decimal]:
    if model in PRICES:
        return PRICES[model]
    # Unknown model. Assume the most expensive rate so caps stay conservative.
    return max(p[0] for p in PRICES.values()), max(p[1] for p in PRICES.values())


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> Decimal:
    rate_in, rate_out = _rates(model)
    billed_input = Decimal(input_tokens) + Decimal(cache_read) * Decimal("0.1") + Decimal(cache_write) * Decimal("1.25")
    return (billed_input * rate_in + Decimal(output_tokens) * rate_out) / Decimal(1_000_000)


def estimate_document_cost(model: str, media_type: str, page_count: int) -> Decimal:
    if media_type == "application/pdf":
        input_tokens = PROMPT_TOKENS + TOKENS_PER_PAGE * max(page_count, 1)
    else:
        input_tokens = PROMPT_TOKENS + TOKENS_PER_IMAGE
    return cost_usd(model, input_tokens, EXPECTED_OUTPUT_TOKENS)

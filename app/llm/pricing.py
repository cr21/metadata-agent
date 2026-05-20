"""OpenAI model pricing — cost per 1M tokens (input, output)."""

import logging

logger = logging.getLogger(__name__)

# USD per 1M tokens: (input, output)
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
}


def compute_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return USD cost for a single API call. Returns 0.0 for unknown models."""
    # Strip snapshot suffixes like "gpt-4o-2024-08-06" → "gpt-4o".
    # Check longer names first so "gpt-4o-mini" is not shadowed by "gpt-4o".
    base = model
    for known in sorted(_PRICING, key=len, reverse=True):
        if model == known or model.startswith(known + "-"):
            base = known
            break
    else:
        logger.warning("Unknown model '%s' — USD cost will be 0.0", model)
        return 0.0

    inp_price, out_price = _PRICING[base]
    return (prompt_tokens * inp_price + completion_tokens * out_price) / 1_000_000

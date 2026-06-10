# USD per 1M tokens (input, output, cache_read) — update when pricing changes
_RATES = {
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-sonnet-4-20250514": (3.0, 15.0, 0.30),
}


def estimate_cost(model: str, usage: dict) -> float:
    rates = _RATES.get(model, (3.0, 15.0, 0.30))
    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_create = usage.get("cache_creation_input_tokens", 0)
    billable_in = max(0, inp - cache_read)
    return (
        billable_in * rates[0] / 1_000_000
        + out * rates[1] / 1_000_000
        + cache_read * rates[2] / 1_000_000
        + cache_create * rates[0] / 1_000_000
    )

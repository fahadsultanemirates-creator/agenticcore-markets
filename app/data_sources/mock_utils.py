"""Shared helpers for generating deterministic sample data.

Used by every data-source client when no API key is configured, so the full
agent pipeline runs end-to-end (and tests stay deterministic) without live
network access. Real provider integrations live alongside these in each
client module and are picked automatically once the matching API key is set.
"""

import random


def rng_for(symbol: str, salt: str = "") -> random.Random:
    """A reproducible RNG per symbol (+ optional salt for a distinct series
    within the same symbol, e.g. price vs. on-chain metrics)."""
    return random.Random(f"{symbol.upper()}::{salt}")

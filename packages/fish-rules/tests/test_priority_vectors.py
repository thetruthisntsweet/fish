"""Frozen vectors for fish_rules.priority (T2.2 subtask 2; Implementation Environment §6).

``vectors/priority_v1.json`` was written once by ``scripts/make_priority_vectors.py`` and is
checked by an independent JavaScript implementation (``scripts/verify_rng_vectors.mjs``).
These tests never regenerate it: if one fails, the priority draws changed, and that breaks
replay of recorded games.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from fish_rules.priority import priority_order
from fish_rules.rng import RNG_ALGORITHM

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "vectors" / "priority_v1.json").read_text(encoding="utf-8")
)


def test_vectors_are_for_this_algorithm() -> None:
    assert VECTORS["algorithm"] == RNG_ALGORITHM


def test_fifty_three_cases() -> None:
    assert len(VECTORS["orders"]) == 53


@pytest.mark.parametrize(
    "case", VECTORS["orders"], ids=lambda c: f"seed={c['seed']},window={c['window']}"
)
def test_r8_1_priority_order(case: dict[str, Any]) -> None:
    """R.8.1: the priority order for each frozen (seed, window index)."""
    assert list(priority_order(int(case["seed"]), int(case["window"]))) == case["order"]

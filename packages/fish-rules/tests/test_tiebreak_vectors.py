"""Frozen vectors for fish_rules.engine.tiebreak_seat (T2.2 subtask 6).

``vectors/tiebreak_v1.json`` was written once by ``scripts/make_tiebreak_vectors.py`` and is
checked by an independent JavaScript implementation (``scripts/verify_rng_vectors.mjs``).
These tests never regenerate it: if one fails, the tie-break changed, and that breaks replay
of recorded games.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from fish_rules.engine import tiebreak_seat
from fish_rules.rng import RNG_ALGORITHM

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "vectors" / "tiebreak_v1.json").read_text(encoding="utf-8")
)


def test_vectors_are_for_this_algorithm() -> None:
    assert VECTORS["algorithm"] == RNG_ALGORITHM


def test_sixty_five_cases() -> None:
    assert len(VECTORS["choices"]) == 65


@pytest.mark.parametrize(
    "case",
    VECTORS["choices"],
    ids=lambda c: f"seed={c['seed']},event={c['call_event']},among={c['among']}",
)
def test_r5_2_tiebreak(case: dict[str, Any]) -> None:
    """R.5.2: the seat the seed chooses for each frozen (seed, call event, seats)."""
    chosen = tiebreak_seat(int(case["seed"]), int(case["call_event"]), case["among"])
    assert chosen == case["chosen"]

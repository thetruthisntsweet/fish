"""Frozen vectors for fish_rules.cards (T2.2 subtask 1; Implementation Environment §6).

``vectors/deal_v1.json`` was written once by ``scripts/make_deal_vectors.py`` and is checked
by an independent JavaScript implementation (``scripts/verify_rng_vectors.mjs``). These tests
never regenerate it: if one fails, the card numbering or the deal changed, and that breaks
replay of recorded games.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from fish_rules.cards import CARD_NAMES, SET_NAMES, deal, first_player
from fish_rules.rng import RNG_ALGORITHM

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "vectors" / "deal_v1.json").read_text(encoding="utf-8")
)


def test_vectors_are_for_this_algorithm() -> None:
    assert VECTORS["algorithm"] == RNG_ALGORITHM


def test_card_and_set_names() -> None:
    """R.1.2, R.1.3: the frozen card and set numbering."""
    assert VECTORS["card_names"] == list(CARD_NAMES)
    assert VECTORS["set_names"] == list(SET_NAMES)


def test_ten_seeds() -> None:
    assert len(VECTORS["deals"]) == 10


@pytest.mark.parametrize("case", VECTORS["deals"], ids=lambda c: f"seed={c['seed']}")
def test_r1_4_deal(case: dict[str, Any]) -> None:
    """R.1.4: the deal and first player for each frozen seed."""
    seed = int(case["seed"])
    assert [list(hand) for hand in deal(seed)] == case["hands"]
    assert first_player(seed) == case["first_player"]

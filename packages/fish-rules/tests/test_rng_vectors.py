"""Frozen vectors for fish_rules.rng (T2.1 subtask 6.6).

``vectors/rng_v1.json`` was written once by ``scripts/make_rng_vectors.py`` and checked by an
independent JavaScript implementation (``scripts/verify_rng_vectors.mjs``). These tests never
regenerate it: if one fails, the generator changed, and that breaks replay of recorded games.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from fish_rules.rng import RNG_ALGORITHM, StreamName, stream

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "vectors" / "rng_v1.json").read_text(encoding="utf-8")
)


def test_vectors_are_for_this_algorithm() -> None:
    assert VECTORS["algorithm"] == RNG_ALGORITHM


@pytest.mark.parametrize("case", VECTORS["next_u64"]["cases"], ids=lambda c: f"seed={c['seed']}")
def test_next_u64(case: dict[str, Any]) -> None:
    rng = stream(int(case["seed"]), VECTORS["next_u64"]["stream"])
    assert [str(rng.next_u64()) for _ in case["outputs"]] == case["outputs"]


@pytest.mark.parametrize(
    "case", VECTORS["stream_first_output"], ids=lambda c: f"{c['name']}/{c['index']}"
)
def test_stream_first_output(case: dict[str, Any]) -> None:
    name: StreamName = case["name"]
    assert str(stream(int(case["seed"]), name, int(case["index"])).next_u64()) == case["first"]


@pytest.mark.parametrize("case", VECTORS["below"]["cases"], ids=lambda c: f"n={c['n']}")
def test_below(case: dict[str, Any]) -> None:
    block = VECTORS["below"]
    rng = stream(int(block["seed"]), block["stream"])
    assert [str(rng.below(int(case["n"]))) for _ in case["outputs"]] == case["outputs"]


@pytest.mark.parametrize(
    "case", VECTORS["shuffled_range_54"]["cases"], ids=lambda c: f"seed={c['seed']}"
)
def test_shuffled_range_54(case: dict[str, Any]) -> None:
    rng = stream(int(case["seed"]), VECTORS["shuffled_range_54"]["stream"])
    assert rng.shuffled(range(54)) == case["order"]

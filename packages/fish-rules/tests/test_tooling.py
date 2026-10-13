"""Checks that the test tooling itself is wired up (T2.1 subtask 4)."""

import os

from hypothesis import given, settings
from hypothesis import strategies as st

EXPECTED_EXAMPLES = {"dev": 100, "ci": 1_000, "nightly": 50_000}


def test_hypothesis_profile_loaded() -> None:
    profile = os.environ.get("HYPOTHESIS_PROFILE", "dev")
    # Hypothesis's settings attributes are only partly typed; this one line is exempt.
    loaded = settings().max_examples  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    assert loaded == EXPECTED_EXAMPLES[profile]


@given(st.integers())
def test_hypothesis_runs(n: int) -> None:
    assert n + 0 == n

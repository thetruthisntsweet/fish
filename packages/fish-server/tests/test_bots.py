"""The website bots' waits (fish_server.bots, fish_agents.delays; R.8.8): drawn from the game's
``bot_delay`` stream at event number x 6 + seat, so they follow from the seed and the table's
version; ``uniform-1.5-4s-v1`` is 1.5 to 4 seconds whatever the decision, and a percentile
table draws each kind of decision from its own row."""

import pytest

from fish_agents.delays import KINDS, UNIFORM, DelayTable, load
from fish_rules.rng import SplitMix64, stream
from fish_server.bots import DelayStreams

FROZEN = [3_430_445, 1_991_486, 1_758_791, 2_625_257]
"""Seed 0, uniform: seat 0 twice after no events, then seat 5, then seat 0 after three events.
If these change, a recorded game's bot waits no longer follow from its seed."""
FROZEN_STAND_IN = [1_510_849, 1_599_389, 2_432_200, 2_482_814]
"""The same draws on ``stand-in-v1``, whose percentiles spread 1.5 to 4 seconds evenly. If these
change, a game recorded with a percentile table no longer follows from its seed."""


def test_the_waits_follow_from_the_seed() -> None:
    delays = DelayStreams(0)
    assert delays.table.version == UNIFORM
    assert [
        delays.delay(0, 0, "turn"),
        delays.delay(0, 0, "press"),
        delays.delay(5, 0, "assign"),
        delays.delay(0, 3, "choice"),
    ] == FROZEN
    assert DelayStreams(2**64 - 1).delay(3, 10, "turn") == 2_716_828


def test_each_wait_is_the_stream_at_event_times_six_plus_seat() -> None:
    table = load("stand-in-v1")
    rng = stream(7, "bot_delay", 4 * 6 + 2)
    assert DelayStreams(7, table).delay(2, 4, "assign") == table.draw(rng, "assign")


def test_uniform_waits_run_from_one_and_a_half_to_four_seconds_whatever_the_decision() -> None:
    table = load(UNIFORM)
    for kind in KINDS:
        rng = SplitMix64(11)
        waits = [table.draw(rng, kind) for _ in range(20_000)]
        assert min(waits) >= 1_500_000
        assert max(waits) <= 4_000_000
        assert abs(sum(waits) / len(waits) - 2_750_000) < 20_000  # 4 standard errors
        low = sum(w < 1_500_000 + 625_000 for w in waits)
        assert abs(low - 5_000) < 4 * (20_000 * 0.25 * 0.75) ** 0.5
    same = [SplitMix64(3) for _ in KINDS]
    assert len({table.draw(rng, kind) for rng, kind in zip(same, KINDS, strict=True)}) == 1


def test_a_percentile_table_draws_its_kinds_own_distribution() -> None:
    """Each kind from its own row: below the 25th percentile a quarter of the time, between
    neighbouring percentiles linearly, never outside the 0th and 100th."""
    rows = {kind: tuple(1_000_000 * (n + 1) + 10_000 * p for p in range(101)) for n, kind in
            enumerate(KINDS)}  # fmt: skip
    table = DelayTable("test-v1", rows)
    rng = SplitMix64(5)
    for kind, row in rows.items():
        waits = [table.draw(rng, kind) for _ in range(20_000)]
        assert row[0] <= min(waits)
        assert max(waits) <= row[100]
        quarter = sum(w < row[25] for w in waits)
        assert abs(quarter - 5_000) < 4 * (20_000 * 0.25 * 0.75) ** 0.5
    steep = DelayTable("steep-v1", dict.fromkeys(KINDS, (0,) * 100 + (100_000_000,)))
    waits = [steep.draw(rng, "turn") for _ in range(20_000)]  # the last 1% runs to 100 s
    assert 100 < sum(w > 0 for w in waits) < 300


def test_the_stand_in_matches_the_uniform_wait_and_says_it_is_a_stand_in() -> None:
    table = load("stand-in-v1")
    assert table.stand_in
    delays = DelayStreams(0, table)
    waits = [delays.delay(0, 0, "turn"), delays.delay(0, 0, "press"), delays.delay(5, 0, "assign"),
             delays.delay(0, 3, "choice")]  # fmt: skip
    assert waits == FROZEN_STAND_IN
    assert all(1_500_000 <= w <= 4_000_000 for w in waits)


def test_unknown_kinds_and_tables_are_refused() -> None:
    with pytest.raises(ValueError, match="no kind of decision 'ask'"):
        load(UNIFORM).draw(SplitMix64(0), "ask")
    with pytest.raises(ValueError, match="no delay table 'pilot-v9'"):
        load("pilot-v9")


def test_event_numbers_never_go_back() -> None:
    delays = DelayStreams(0)
    delays.delay(0, 5, "turn")
    with pytest.raises(ValueError, match="went back from 5 to 4"):
        delays.delay(0, 4, "turn")
    with pytest.raises(ValueError, match="seat"):
        delays.delay(6, 5, "turn")

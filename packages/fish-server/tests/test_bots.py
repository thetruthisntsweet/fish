"""The website bots' waits (fish_server.bots; R.8.8): 1.5 to 4 seconds, uniform, drawn from
the game's ``bot_delay`` stream at event number x 6 + seat, so they follow from the seed."""

import pytest

from fish_rules.rng import SplitMix64, stream
from fish_server.bots import BOT_DELAY_MAX_US, BOT_DELAY_MIN_US, DelayStreams, draw_delay

FROZEN = [3_430_445, 1_991_486, 1_758_791, 2_625_257]
"""Seed 0: seat 0 twice after no events, then seat 5, then seat 0 after three events. If these
change, a recorded game's bot waits no longer follow from its seed."""


def test_the_waits_follow_from_the_seed() -> None:
    delays = DelayStreams(0)
    assert [delays.delay(0, 0), delays.delay(0, 0), delays.delay(5, 0), delays.delay(0, 3)] == (
        FROZEN
    )
    assert DelayStreams(2**64 - 1).delay(3, 10) == 2_716_828


def test_each_wait_is_the_stream_at_event_times_six_plus_seat() -> None:
    rng = stream(7, "bot_delay", 4 * 6 + 2)
    assert DelayStreams(7).delay(2, 4) == draw_delay(rng)


def test_waits_are_uniform_from_one_and_a_half_to_four_seconds() -> None:
    rng = SplitMix64(11)
    waits = [draw_delay(rng) for _ in range(20_000)]
    assert min(waits) >= BOT_DELAY_MIN_US
    assert max(waits) <= BOT_DELAY_MAX_US
    assert (BOT_DELAY_MIN_US, BOT_DELAY_MAX_US) == (1_500_000, 4_000_000)
    middle = (BOT_DELAY_MIN_US + BOT_DELAY_MAX_US) / 2
    assert abs(sum(waits) / len(waits) - middle) < 20_000  # 4 standard errors is about 20,000
    quarter = (BOT_DELAY_MAX_US - BOT_DELAY_MIN_US) / 4
    low = sum(w < BOT_DELAY_MIN_US + quarter for w in waits)
    assert abs(low - 5_000) < 4 * (20_000 * 0.25 * 0.75) ** 0.5


def test_event_numbers_never_go_back() -> None:
    delays = DelayStreams(0)
    delays.delay(0, 5)
    with pytest.raises(ValueError, match="went back from 5 to 4"):
        delays.delay(0, 4)
    with pytest.raises(ValueError, match="seat"):
        delays.delay(6, 5)

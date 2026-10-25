"""Tests for fish_agents.base: the bot_policy generators an agent draws from."""

import pytest

from fish_agents import PolicyStreams
from fish_rules.rng import stream


def test_a_decision_draws_from_its_bot_policy_stream() -> None:
    """The generator for seat s after e events is stream bot_policy, index e x 6 + s
    (docs/determinism.md §2)."""
    streams = PolicyStreams(77)
    assert streams.for_decision(4, 10).next_u64() == stream(77, "bot_policy", 64).next_u64()


def test_a_seat_keeps_drawing_until_the_next_event() -> None:
    """Two decisions of one seat before the next event continue one generator, so the second
    does not repeat the first's draws; the next event starts a fresh one."""
    streams = PolicyStreams(5)
    reference = stream(5, "bot_policy", 2 * 6 + 1)
    first = streams.for_decision(1, 2).next_u64()
    second = streams.for_decision(1, 2).next_u64()
    assert (first, second) == (reference.next_u64(), reference.next_u64())
    assert streams.for_decision(1, 3).next_u64() == stream(5, "bot_policy", 3 * 6 + 1).next_u64()


def test_seats_and_games_have_their_own_streams() -> None:
    draws = {
        PolicyStreams(seed).for_decision(seat, 0).next_u64() for seed in (1, 2) for seat in range(6)
    }
    assert len(draws) == 12


def test_events_never_go_back() -> None:
    streams = PolicyStreams(1)
    streams.for_decision(0, 4)
    with pytest.raises(ValueError, match="went back"):
        streams.for_decision(0, 3)


def test_seats_are_checked() -> None:
    with pytest.raises(ValueError, match="seat must be in"):
        PolicyStreams(1).for_decision(6, 0)

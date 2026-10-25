"""Tests for fish_agents.play: six agents play a whole environment game, each seeing only its
own view, and the same agents and seed always give the same game."""

import pytest

from fish_agents import Agent
from fish_agents.play import play_game
from fish_rules.action_index import PASS_INDEX
from fish_rules.engine import IllegalActionError
from fish_rules.record import replay_record
from fish_rules.rng import SplitMix64
from fish_rules.state import Outcome
from fish_rules.view import PlayerView


class FirstLegal:
    """Always the lowest legal index (in a window, that is a pass)."""

    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        return view.legal[0]


class RandomLegal:
    """Uniform over legal actions, passing in windows 9 times in 10, with a log of what it saw."""

    def __init__(self) -> None:
        self.seen: list[PlayerView] = []

    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        self.seen.append(view)
        if PASS_INDEX in view.legal and rng.below(10):
            return PASS_INDEX
        return rng.choice(view.legal)


class Illegal:
    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        return 0  # an ask, which is never legal in the opening window


def test_a_whole_game_is_played_and_recorded() -> None:
    agents: list[Agent] = [FirstLegal() for _ in range(6)]
    record = play_game(agents, 3)
    assert record["seed"] == "3"
    assert replay_record(record).outcome in (Outcome.FINISHED, Outcome.UNFINISHED)


def test_r2_1_each_agent_sees_only_its_own_view() -> None:
    """R.2.1: every view an agent is given is its own seat's, and it is asked only when it may
    act."""
    agents = [RandomLegal() for _ in range(6)]
    play_game(agents, 11)
    for seat, agent in enumerate(agents):
        assert agent.seen
        assert all(view.seat == seat and view.legal for view in agent.seen)


@pytest.mark.parametrize("game_seed", [0, 9, 2**64 - 1])
def test_same_agents_and_seed_give_the_same_game(game_seed: int) -> None:
    first = play_game([RandomLegal() for _ in range(6)], game_seed)
    second = play_game([RandomLegal() for _ in range(6)], game_seed)
    assert first == second
    assert replay_record(first) == replay_record(second)


def test_different_seeds_give_different_games() -> None:
    records = [play_game([RandomLegal() for _ in range(6)], seed) for seed in range(5)]
    assert len({str(record["actions"]) for record in records}) == 5


def test_an_illegal_action_is_an_error() -> None:
    agents: list[Agent] = [Illegal(), *(FirstLegal() for _ in range(5))]
    with pytest.raises(IllegalActionError):
        play_game(agents, 1)


def test_a_game_needs_six_agents() -> None:
    with pytest.raises(ValueError, match="6 agents"):
        play_game([FirstLegal()], 1)

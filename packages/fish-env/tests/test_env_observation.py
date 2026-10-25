"""The environment observes through the projection (R.2): every agent's observation is its
view encoded as fish-obs-v1, carries only the most recent event, and never reflects what is
hidden from it."""

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_env import AGENTS, FishEnv
from fish_env.env import seat_of
from fish_rules.action_index import DECLARE_BASE, PASS_INDEX, legal_mask
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent
from fish_rules.observation import OBS_LAYOUT, OBS_SIZE, OFFSETS, encode
from fish_rules.state import Phase
from fish_rules.view import project

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Every seat at every step of whole games is costly: a fortieth of the profile's examples
(10 in dev, 25 in CI, 1,250 nightly)."""

KINDS = (AskEvent, CallEvent, ChoiceEvent)
"""The order of the observation's ``event`` block."""


def block(observation: np.ndarray, name: str) -> list[int]:  # pyright: ignore[reportMissingTypeArgument, reportUnknownParameterType]
    start = OFFSETS[name]
    return [int(i) for i in np.flatnonzero(observation[start : start + dict(OBS_LAYOUT)[name]])]


@settings(max_examples=GAMES, deadline=None)  # every agent at every step of a whole game
@given(U64, U64)
def test_r2_2_every_observation_is_the_encoded_view(game_seed: int, policy_seed: int) -> None:
    """R.2.2: at every agent step, every agent's observation is exactly its view encoded as
    fish-obs-v1, its mask is exactly its legal actions, and the view's most recent event is
    the game's."""
    game = FishEnv()
    game.reset(seed=game_seed)
    rng = np.random.default_rng(policy_seed)
    while game.game.phase is not Phase.OVER:
        for agent in AGENTS:
            observation = game.observe(agent)
            view = game.view(agent)
            assert view == project(game.game, seat_of(agent), view.last_event)
            assert observation["observation"].shape == (OBS_SIZE,)
            assert observation["observation"].tobytes() == encode(view)
            assert observation["action_mask"].tobytes() == legal_mask(game.game, seat_of(agent))
        assert game.view(AGENTS[0]).last_event is not None or game.game.events == 0
        mask = game.observe(game.agent_selection)["action_mask"]
        game.step(int(rng.choice(np.flatnonzero(mask))))


def test_r4_3_window_answers_stay_hidden() -> None:
    """R.4.3, R.8.3: whether seat 0 declared or passed, seats 1 to 5 observe the same."""
    declared, passed = FishEnv(), FishEnv()
    declared.reset(seed=42)
    passed.reset(seed=42)
    declared.step(DECLARE_BASE + 4)
    passed.step(PASS_INDEX)
    for agent in AGENTS[1:]:
        assert np.array_equal(
            declared.observe(agent)["observation"], passed.observe(agent)["observation"]
        )
    assert block(declared.observe("seat_0")["observation"], "own_declaration") == [4]
    assert block(passed.observe("seat_0")["observation"], "own_declaration") == []


def test_r2_2_only_the_most_recent_event_is_observed() -> None:
    """R.2.2: after an ask, every agent observes that ask; after the next event, only that."""
    game = FishEnv()
    game.reset(seed=42)
    rng = np.random.default_rng(1)
    seen: list[int] = []
    while len(seen) < 3 and game.game.phase is not Phase.OVER:
        last = game.view(AGENTS[0]).last_event
        if last is not None and (not seen or last.number != seen[-1]):
            seen.append(last.number)
            for agent in AGENTS:
                assert game.view(agent).last_event == last
                kind = block(game.observe(agent)["observation"], "event")
                assert kind == [KINDS.index(type(last))]
        mask = game.observe(game.agent_selection)["action_mask"]
        game.step(int(rng.choice(np.flatnonzero(mask))))
    assert seen == sorted(seen)
    assert len(seen) == 3

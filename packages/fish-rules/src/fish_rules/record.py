"""A game record: everything needed to replay a game exactly (docs/determinism.md §8).

A record is the ruleset version, the action encoding, the game seed and every action in
order, plus the outcome and winner once the game is over. It is plain data (strings, ints,
lists and dicts), ready for JSON; the seed is a decimal string so that languages without
64-bit integers read it exactly. Replaying a record checks that it was made under this
ruleset and encoding, applies every action to ``new_game(seed)``, and checks the result
against the recorded outcome.

The environment writes records (``fish_env.FishEnv.record``); the golden replays use the same
keys and add the state hash after every action. The corpus schema (T1.6) may wrap a record
with more fields; ``replay_record`` ignores keys it does not know.
"""

from collections.abc import Mapping, Sequence

from fish_rules.codec import ACTION_ENCODING, action_from_data, action_to_data
from fish_rules.engine import replay
from fish_rules.events import Action
from fish_rules.state import Outcome, State, new_game
from fish_rules.version import RULESET_VERSION

_SEED_BOUND = 2**64


def game_record(seed: int, actions: Sequence[Action], state: State) -> dict[str, object]:
    """The record of the game that ``actions`` played from ``seed``, now in ``state``. The
    outcome and winner are None until the game is over."""
    over = state.outcome is not None
    return {
        "ruleset": RULESET_VERSION,
        "action_encoding": ACTION_ENCODING,
        "seed": str(seed),
        "outcome": str(state.outcome) if over else None,
        "winner": state.winner() if over else None,
        "actions": [action_to_data(action) for action in actions],
    }


def _seed(value: object) -> int:
    if not isinstance(value, str) or not value.isdecimal() or not value.isascii():
        raise ValueError(f"a record's seed is a decimal string, got {value!r}")
    seed = int(value)
    if seed >= _SEED_BOUND:
        raise ValueError(f"a game seed is in [0, 2**64), got {seed}")
    return seed


def replay_record(data: Mapping[str, object]) -> State:
    """Replay ``data`` and return the final state. Raises ValueError if it was recorded under
    another ruleset version or action encoding, is malformed, does not end in the recorded
    outcome and winner, or contains an action the rules do not allow (``IllegalActionError``
    is a ValueError)."""
    for key, expected in (("ruleset", RULESET_VERSION), ("action_encoding", ACTION_ENCODING)):
        if data.get(key) != expected:
            raise ValueError(
                f"recorded with {key} {data.get(key)!r}; this engine reads {expected!r}"
            )
    seed = _seed(data.get("seed"))
    actions = data.get("actions")
    if not isinstance(actions, list):
        raise ValueError("a record's actions are a list")
    items: list[object] = list(actions)  # pyright: ignore[reportUnknownArgumentType]
    parsed: list[Action] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"each recorded action is a dict, got {item!r}")
        parsed.append(action_from_data(item))  # pyright: ignore[reportUnknownArgumentType]
    state = new_game(seed)
    for step in replay(seed, parsed):
        state = step[0]
    outcome = data.get("outcome")
    winner = data.get("winner")
    if outcome != (str(state.outcome) if state.outcome is not None else None):
        raise ValueError(f"the record says outcome {outcome!r}; the replay ends {state.outcome}")
    actual_winner = state.winner() if state.outcome is Outcome.FINISHED else None
    if winner != actual_winner or isinstance(winner, bool):
        raise ValueError(f"the record says winner {winner!r}; the replay gives {actual_winner}")
    return state

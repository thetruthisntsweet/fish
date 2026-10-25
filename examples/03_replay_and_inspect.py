"""Save a game as a record, load it back, replay it, and read it event by event.

A record is the ruleset version, the seed and every action; replaying it recreates every
state and every public event exactly. This also shows what one seat could see at a moment:
the view an agent receives, built by the same projection the website uses.
Run: python 03_replay_and_inspect.py
"""

import json
import tempfile
from pathlib import Path

from fish_agents.b0 import B0
from fish_agents.play import play_game
from fish_rules.cards import card_name
from fish_rules.codec import action_from_data
from fish_rules.engine import replay
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent, Event
from fish_rules.record import replay_record
from fish_rules.view import latest_event, project

record = play_game([B0()] * 6, 2026)
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "game.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))

final = replay_record(loaded)  # checks the versions, replays, and checks the outcome
print(f"ruleset {loaded['ruleset']}, seed {loaded['seed']}, {len(loaded['actions'])} actions")
print(
    f"final score: team 0 {final.score(0)}, team 1 {final.score(1)}; winner team {final.winner()}"
)


def describe(event: Event) -> str:
    match event:
        case AskEvent():
            answer = "yes" if event.success else "no"
            return (
                f"seat {event.asker} asks seat {event.target} for {card_name(event.card)}: {answer}"
            )
        case CallEvent():
            verdict = "correct" if event.correct else "wrong"
            return (
                f"seat {event.caller} calls set {event.set_id}: {verdict}, "
                f"to team {event.scored_by}"
            )
        case ChoiceEvent():
            return f"team {event.team} gives the turn to seat {event.seat}"


actions = [action_from_data(item) for item in loaded["actions"]]
last: Event | None = None
shown = 0
for state, records in replay(int(loaded["seed"]), actions):
    newest = latest_event(records, last)
    if newest is not last and newest is not None:
        last = newest
        if shown < 8:
            print(" ", describe(newest))
            shown += 1
            if shown == 8:
                view = project(state, 0, last)
                print(
                    f"  -- seat 0 now holds {[card_name(c) for c in view.hand]}, sees hand "
                    f"sizes {view.hand_sizes} and the event above, and nothing else"
                )

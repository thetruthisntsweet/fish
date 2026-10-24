"""Write the frozen fish-obs-v1 vectors for fish_rules.observation.encode (T2.4 subtask 4).

Run once: ``uv run python scripts/make_obs_vectors.py``. Trained agents depend on the layout,
so this script refuses to overwrite the file. It encodes the views of the fish-view-v1
vectors (the same golden-game states and seats) and writes, for each, the indices of the bits
that are set, one case per line.
"""

import json
import sys
from pathlib import Path

from fish_rules.codec import action_from_data
from fish_rules.engine import replay
from fish_rules.events import Event
from fish_rules.observation import OBS_ENCODING, OBS_SIZE, encode
from fish_rules.state import State, new_game
from fish_rules.view import latest_event, project

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "packages/fish-rules/tests"
VIEWS = TESTS / "vectors/view_v1.json"
OUT = TESTS / "vectors/obs_v1.json"


def golden_state(game: str, step: int) -> tuple[State, Event | None]:
    data = json.loads((TESTS / "golden" / f"{game}.json").read_text(encoding="utf-8"))
    seed = int(data["seed"])
    actions = [action_from_data(item) for item in data["actions"][:step]]
    state, last = new_game(seed), None
    for after, records in replay(seed, actions):
        state, last = after, latest_event(records, last)
    return state, last


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} already exists. Frozen vectors are never regenerated.")
    lines: list[str] = []
    for case in json.loads(VIEWS.read_text(encoding="utf-8"))["cases"]:
        state, last = golden_state(case["game"], case["step"])
        bits = encode(project(state, case["seat"], last))
        ones = [i for i, bit in enumerate(bits) if bit]
        entry = {"game": case["game"], "step": case["step"], "seat": case["seat"], "ones": ones}
        lines.append(json.dumps(entry, separators=(", ", ": ")))
    body = ",\n    ".join(lines)
    OUT.write_text(
        f'{{\n  "encoding": "{OBS_ENCODING}",\n  "size": {OBS_SIZE},\n'
        f'  "cases": [\n    {body}\n  ]\n}}\n',
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({len(lines)} cases)")


if __name__ == "__main__":
    main()

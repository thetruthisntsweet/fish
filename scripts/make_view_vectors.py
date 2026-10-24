"""Write the frozen fish-view-v1 vectors for fish_rules.view.view_to_data (T2.4 subtask 3).

Run once: ``uv run python scripts/make_view_vectors.py``. Clients depend on the layout, so this
script refuses to overwrite the file. From every golden game it takes the first state in each
phase and the first state after each kind of event, and writes the view of seats 0 and 4 there,
one case per line. ``step`` is the number of actions applied (0 is the deal).
"""

import json
import sys
from pathlib import Path

from fish_rules.codec import action_from_data
from fish_rules.engine import replay
from fish_rules.events import Event
from fish_rules.state import State, new_game
from fish_rules.view import VIEW_ENCODING, latest_event, project, view_to_data

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "packages/fish-rules/tests/golden"
OUT = ROOT / "packages/fish-rules/tests/vectors/view_v1.json"
SEATS = (0, 4)


def steps(path: Path) -> list[tuple[State, Event | None]]:
    game = json.loads(path.read_text(encoding="utf-8"))
    seed = int(game["seed"])
    actions = [action_from_data(data) for data in game["actions"]]
    out: list[tuple[State, Event | None]] = [(new_game(seed), None)]
    last: Event | None = None
    for state, records in replay(seed, actions):
        last = latest_event(records, last)
        out.append((state, last))
    return out


def cases() -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for path in sorted(GOLDEN.glob("*.json")):
        seen: set[str] = set()
        for step, (state, last) in enumerate(steps(path)):
            keys = {f"phase:{state.phase}", f"event:{type(last).__name__}"}
            if keys <= seen:
                continue
            seen |= keys
            for seat in SEATS:
                view = view_to_data(project(state, seat, last))
                found.append({"game": path.stem, "step": step, "seat": seat, "view": view})
    return found


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} already exists. Frozen vectors are never regenerated.")
    lines = [json.dumps(case, separators=(", ", ": ")) for case in cases()]
    body = ",\n    ".join(lines)
    OUT.write_text(
        f'{{\n  "encoding": "{VIEW_ENCODING}",\n  "cases": [\n    {body}\n  ]\n}}\n',
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({len(lines)} cases)")


if __name__ == "__main__":
    main()

"""Write the frozen action-index vectors for fish_rules.action_index (T2.3 subtask 1).

Run once: ``uv run python scripts/make_action_index_vectors.py``. Agents trained on the layout
depend on it, so this script refuses to overwrite the file. It lists every index for seat 1
(team 0) and seat 4 (team 1), decoded outside the team vote and written with the action codec,
one entry per line so a change shows as a readable diff.
"""

import json
import sys
from pathlib import Path

from fish_rules.action_index import ACTION_INDEX_ENCODING, NUM_ACTIONS, decode
from fish_rules.codec import ACTION_ENCODING, action_to_data
from fish_rules.state import Phase

OUT = (
    Path(__file__).resolve().parent.parent
    / "packages/fish-rules/tests/vectors/action_index_v1.json"
)
SEATS = (1, 4)


def build() -> str:
    lines = [
        "{",
        f'  "encoding": {json.dumps(ACTION_INDEX_ENCODING)},',
        f'  "action_encoding": {json.dumps(ACTION_ENCODING)},',
        f'  "num_actions": {NUM_ACTIONS},',
        '  "seats": {',
    ]
    for n, seat in enumerate(SEATS):
        lines.append(f'    "{seat}": [')
        for index in range(NUM_ACTIONS):
            action = action_to_data(decode(seat, index, Phase.CHOOSE))
            comma = "," if index < NUM_ACTIONS - 1 else ""
            lines.append(f"      [{index}, {json.dumps(action, separators=(', ', ': '))}]{comma}")
        lines.append("    ]" + ("," if n < len(SEATS) - 1 else ""))
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} already exists. Frozen vectors are never regenerated.")
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

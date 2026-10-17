"""Write the frozen tie-break vectors for fish_rules.engine.tiebreak_seat (T2.2 subtask 6).

Run once: ``uv run python scripts/make_tiebreak_vectors.py``. The file it writes is part of
the ruleset's definition, so this script refuses to overwrite it. Seeds and event numbers are
stored as decimal strings so that languages without big integers read them exactly.
"""

import json
import sys
from pathlib import Path

from fish_rules.engine import tiebreak_seat
from fish_rules.rng import RNG_ALGORITHM

OUT = Path(__file__).resolve().parent.parent / "packages/fish-rules/tests/vectors/tiebreak_v1.json"
U64_MAX = 2**64 - 1
AMONG = ((3, 4, 5), (0, 2), (1, 2), (4,))
CASES = (
    *((seed, event, among) for seed in range(4) for event in (0, 1, 7, 99) for among in AMONG),
    (U64_MAX, U64_MAX, (0, 1, 2)),
)


def build() -> dict[str, object]:
    return {
        "algorithm": RNG_ALGORITHM,
        "choices": [
            {
                "seed": str(seed),
                "call_event": str(event),
                "among": list(among),
                "chosen": tiebreak_seat(seed, event, among),
            }
            for seed, event, among in CASES
        ],
    }


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} already exists. Frozen vectors are never regenerated.")
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

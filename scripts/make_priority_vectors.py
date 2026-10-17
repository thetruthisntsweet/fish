"""Write the frozen priority vectors for fish_rules.priority (T2.2 subtask 2).

Run once: ``uv run python scripts/make_priority_vectors.py``. The file it writes is part of
the ruleset's definition, so this script refuses to overwrite it. Seeds and window indices
are stored as decimal strings so that languages without big integers read them exactly.
"""

import json
import sys
from pathlib import Path

from fish_rules.priority import priority_order
from fish_rules.rng import RNG_ALGORITHM

OUT = Path(__file__).resolve().parent.parent / "packages/fish-rules/tests/vectors/priority_v1.json"
U64_MAX = 2**64 - 1
CASES = (
    *((seed, window) for seed in range(5) for window in range(10)),
    (42, U64_MAX),
    (U64_MAX, 0),
    (U64_MAX, U64_MAX),
)


def build() -> dict[str, object]:
    return {
        "algorithm": RNG_ALGORITHM,
        "orders": [
            {"seed": str(seed), "window": str(window), "order": list(priority_order(seed, window))}
            for seed, window in CASES
        ],
    }


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} already exists. Frozen vectors are never regenerated.")
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

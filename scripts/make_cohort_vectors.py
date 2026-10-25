"""Write the frozen cohort vectors for fish_rules.cohort (T1.6 subtask 2).

Run once: ``uv run python scripts/make_cohort_vectors.py``. The file it writes freezes the
held-out cohort draw (fish-cohort-v1), so this script refuses to overwrite it. Seeds and
block numbers are stored as decimal strings so that languages without big integers read them
exactly.
"""

import json
import sys
from pathlib import Path

from fish_rules.cohort import BLOCK, COHORT_DRAW, PER_BLOCK, cohort_positions
from fish_rules.rng import RNG_ALGORITHM

OUT = Path(__file__).resolve().parent.parent / "packages/fish-rules/tests/vectors/cohort_v1.json"
U64_MAX = 2**64 - 1
CASES = (
    *((seed, block) for seed in (0, 1, 2026, U64_MAX) for block in (0, 1, 2, 249)),
    (12345, U64_MAX),
)


def build() -> dict[str, object]:
    return {
        "algorithm": RNG_ALGORITHM,
        "draw": COHORT_DRAW,
        "block": BLOCK,
        "per_block": PER_BLOCK,
        "positions": [
            {
                "seed": str(seed),
                "block": str(block),
                "positions": list(cohort_positions(seed, block)),
            }
            for seed, block in CASES
        ],
    }


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} already exists. Frozen vectors are never regenerated.")
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

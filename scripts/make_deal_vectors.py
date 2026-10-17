"""Write the frozen deal vectors for fish_rules.cards (T2.2 subtask 1).

Run once: ``uv run python scripts/make_deal_vectors.py``. The file it writes is part of the
ruleset's definition, so this script refuses to overwrite it. Seeds are stored as decimal
strings so that languages without big integers read them exactly.
"""

import json
import sys
from pathlib import Path

from fish_rules.cards import CARD_NAMES, SET_NAMES, deal, first_player
from fish_rules.rng import RNG_ALGORITHM

OUT = Path(__file__).resolve().parent.parent / "packages/fish-rules/tests/vectors/deal_v1.json"
SEEDS = (*range(9), 2**64 - 1)


def build() -> dict[str, object]:
    return {
        "algorithm": RNG_ALGORITHM,
        "card_names": list(CARD_NAMES),
        "set_names": list(SET_NAMES),
        "deals": [
            {
                "seed": str(seed),
                "hands": [list(hand) for hand in deal(seed)],
                "first_player": first_player(seed),
            }
            for seed in SEEDS
        ],
    }


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} already exists. Frozen vectors are never regenerated.")
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

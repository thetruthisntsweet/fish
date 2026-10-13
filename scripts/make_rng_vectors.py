"""Write the frozen test vectors for fish_rules.rng (T2.1 subtask 6.6).

Run once: ``uv run python scripts/make_rng_vectors.py``. The file it writes is part of
the ruleset's definition, so this script refuses to overwrite it. 64-bit values are
stored as decimal strings so that languages without big integers read them exactly.
"""

import json
import sys
from pathlib import Path

from fish_rules.rng import RNG_ALGORITHM, STREAM_NAMES, stream

OUT = Path(__file__).resolve().parent.parent / "packages/fish-rules/tests/vectors/rng_v1.json"
U64_MAX = 2**64 - 1


def build() -> dict[str, object]:
    next_u64 = []
    for seed in (0, 1, U64_MAX):
        rng = stream(seed, "deal")
        next_u64.append({"seed": str(seed), "outputs": [str(rng.next_u64()) for _ in range(20)]})

    first_outputs = [
        {
            "seed": "42",
            "name": name,
            "index": str(index),
            "first": str(stream(42, name, index).next_u64()),
        }
        for name in STREAM_NAMES
        for index in (0, 7)
    ]

    below = []
    for n in (1, 2, 3, 6, 54, 2**63 + 1, 2**64):
        rng = stream(42, "tiebreak")
        below.append({"n": str(n), "outputs": [str(rng.below(n)) for _ in range(20)]})

    shuffles = [
        {"seed": str(seed), "order": stream(seed, "deal").shuffled(range(54))} for seed in range(10)
    ]

    return {
        "algorithm": RNG_ALGORITHM,
        "next_u64": {"stream": "deal", "index": "0", "cases": next_u64},
        "stream_first_output": first_outputs,
        "below": {"seed": "42", "stream": "tiebreak", "index": "0", "cases": below},
        "shuffled_range_54": {"stream": "deal", "index": "0", "cases": shuffles},
    }


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} already exists. Frozen vectors are never regenerated.")
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

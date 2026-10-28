"""Rule traceability (Implementation Environment §8, §9): every rule of the Canonical Ruleset
is cited by at least one test, or is listed below as owed by a later task.

A test cites a rule by naming it in its docstring or comments ("R.4.3", or a range such as
"R.4.4-R.4.5") or in its name ("test_r4_3_..."). The script scans the tests of every package,
so a rule owed by the server (T3.1) stops being owed once a server test cites it.

It fails if a rule is neither cited nor owed, if an owed rule is now cited (remove it from
OWED, so the list stays true), if a test cites a rule that does not exist, or if the ruleset
version has changed (update RULES to the new version first).

Run: ``uv run python scripts/check_rule_citations.py``. Runs in scripts/check.sh and as a
pre-commit hook, so CI runs it in the hooks job.
"""

import re
import sys
from pathlib import Path
from typing import Final

from fish_rules.version import RULESET_VERSION

ROOT: Final = Path(__file__).resolve().parent.parent

RULES_VERSION: Final = "1.1"
"""The ruleset version RULES lists. A new version needs RULES checked against it."""

RULES: Final[tuple[str, ...]] = (
    *(f"R.1.{n}" for n in range(1, 5)),
    *(f"R.2.{n}" for n in range(1, 7)),
    *(f"R.3.{n}" for n in range(1, 4)),
    *(f"R.4.{n}" for n in range(1, 7)),
    *(f"R.5.{n}" for n in range(1, 3)),
    *(f"R.6.{n}" for n in range(1, 3)),
    *(f"R.7.{n}" for n in range(1, 3)),
    *(f"R.8.{n}" for n in range(1, 10)),
    "R.9",
    *(f"R.10.{n}" for n in range(1, 3)),
)
"""Every rule of Canonical Ruleset v1.1. R.9's bullets are unnumbered, so R.9 is one rule."""

OWED: Final[dict[str, str]] = {
    "R.2.5": "T3.4: the client never redisplays past events (notes are T1.5's attestation)",
    "R.2.6": "T3.4: events shown the moment they arrive, and a visible turn timer",
    "R.8.4": "T3.1: the 60-second turn timer, reconnection and bot handover",
    "R.8.8": "T3.5: website bot delays and when bots press Call",
}
"""Rules about the website or the client, which no engine test can check, and the task that
owes a test for each. Remove an entry when that task's test cites the rule."""

_ONE: Final = re.compile(r"\bR\.(\d+)(?:\.(\d+))?\b")
_RANGE: Final = re.compile(r"\bR\.(\d+)\.(\d+)\s*[-\u2013]\s*R\.\1\.(\d+)\b")
_NAME: Final = re.compile(r"def test_\w+")
_NAMED: Final = re.compile(r"_r(\d+)_(\d+)(?=_)")


def citations(text: str) -> set[str]:
    """Every rule ``text`` cites: single references, ranges and test names."""
    found: set[str] = set()
    for match in _RANGE.finditer(text):
        section, first, last = (int(group) for group in match.groups())
        found.update(f"R.{section}.{n}" for n in range(first, last + 1))
    for match in _ONE.finditer(text):
        section, item = match.groups()
        found.add(f"R.{section}" if item is None else f"R.{section}.{item}")
    for name in _NAME.findall(text):
        found.update(f"R.{section}.{item}" for section, item in _NAMED.findall(f"{name}_"))
    return found


def main() -> int:
    if RULESET_VERSION != RULES_VERSION:
        print(f"RULES lists ruleset v{RULES_VERSION}, but the code is v{RULESET_VERSION}.")
        print("Check RULES and OWED against the new version, then update RULES_VERSION.")
        return 1

    cited_by: dict[str, set[str]] = {}
    for path in sorted(ROOT.glob("packages/*/tests/**/*.py")):
        for rule in citations(path.read_text(encoding="utf-8")):
            cited_by.setdefault(rule, set()).add(path.relative_to(ROOT).as_posix())

    sections = {rule.rsplit(".", 1)[0] for rule in RULES if rule.count(".") == 2} | {"R.9"}
    unknown = sorted(r for r in cited_by if r not in RULES and r not in sections)
    missing = [r for r in RULES if r not in cited_by and r not in OWED]
    stale = [r for r in OWED if r in cited_by]

    width = max(len(rule) for rule in RULES)
    for rule in RULES:
        files = cited_by.get(rule, set())
        status = (
            f"{len(files)} test file(s)"
            if files
            else f"owed by {OWED[rule]}"
            if rule in OWED
            else "NOT CITED"
        )
        print(f"{rule:<{width}}  {status}")

    problems = [
        *(f"{rule} is not cited by any test and not owed by a later task" for rule in missing),
        *(f"{rule} is cited now; remove it from OWED" for rule in stale),
        *(f"a test cites {rule}, which is not a rule of v{RULES_VERSION}" for rule in unknown),
    ]
    for problem in problems:
        print(f"FAIL: {problem}")
    if not problems:
        cited = sum(1 for rule in RULES if rule in cited_by)
        print(f"OK: {cited} of {len(RULES)} rules cited by tests, {len(OWED)} owed by later tasks.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""Make the bots' delay table from the pilot report (T4.2; docs/runbooks/pilot.md §4 step 3).

    uv run python scripts/make_bot_delays.py ~/Downloads/pilot.json pilot-2026-12-v1

Reads the file ``python -m fish_server.pilot_report --out`` wrote, and writes
``packages/fish-agents/src/fish_agents/delay_tables/<version>.json``: each kind's 101
percentiles of people's response times (any below zero raised to zero), the count behind each,
and where they came from. It refuses a version that exists already, since a table is never
changed once a game has used it, and a kind with fewer than 50 times. Then set
``fish_server.study.BOT_DELAYS`` to the version, as it prints.
"""

import argparse
import json
import sys
from pathlib import Path

from fish_agents.delays import from_report

TABLES = Path(__file__).parents[1] / "packages/fish-agents/src/fish_agents/delay_tables"


def main(argv: list[str] | None = None, tables: Path = TABLES) -> int:
    parser = argparse.ArgumentParser(description="Make the bots' delay table from the pilot.")
    parser.add_argument("report", type=Path, help="the pilot report's --out file")
    parser.add_argument("version", help="the new table's version, e.g. pilot-2026-12-v1")
    args = parser.parse_args(argv)
    out = tables / f"{args.version}.json"
    if out.exists():
        parser.error(f"{out.name} exists already: a table never changes, so choose a new version")
    figures = json.loads(args.report.read_text())
    since = figures.get("since") or "the start"
    games = figures.get("games", {}).get("exported", "?")
    source = f"The pilot: {games} corpus games started from {since} (fish_server.pilot_report)."
    try:
        data = from_report(figures, args.version, source)
    except ValueError as problem:
        print(f"Not made: {problem}", file=sys.stderr)
        return 1
    out.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    print(f"Wrote {out}.")
    study = "packages/fish-server/src/fish_server/study.py"
    print(f'Now set BOT_DELAYS = "{args.version}" in {study}.')
    return 0


if __name__ == "__main__":
    sys.exit(main())

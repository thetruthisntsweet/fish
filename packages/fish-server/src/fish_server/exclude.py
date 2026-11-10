"""Leave a game out of the corpus after a fault (T4.4; docs/runbooks/collection.md §4).

    python -m fish_server.exclude 1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed \\
        --reason "D140: its actions were stored with a gap; it cannot be replayed"

Records that the game is excluded, with why. From the next export it is left out and counted
as "excluded after a fault", and the integrity check lists its faults as known. The game's own
rows are not touched. The record is append-only: an exclusion cannot be changed or undone, so
decide first, write the decision in docs/decisions.md, and name it in the reason. Run it on
Render from the service's Shell. It connects as the server's own login, which may add the
record but nothing more.
"""

import argparse
import sys
import uuid

from sqlalchemy import Engine, create_engine, insert, pool, select

from fish_server import db
from fish_server.corpus_export import membership
from fish_server.settings import database_url

MIN_REASON = 10


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.exclude",
        description="Leave a game out of the corpus after a fault. It cannot be undone.",
    )
    parser.add_argument(
        "game", type=uuid.UUID, help="the game's ID, as the integrity check prints it"
    )
    parser.add_argument("--reason", required=True, help="why, naming the decision")
    args = parser.parse_args(argv)
    reason = args.reason.strip()
    if len(reason) < MIN_REASON:
        parser.error("--reason says why in a sentence, and names the decision")
    engine = engine or create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.begin() as conn:
            standing = membership(conn).get(args.game)
            if standing is None:
                print(f"No game {args.game} is stored; nothing recorded.")
                return 1
            already = conn.execute(
                select(db.game_exclusions.c.reason).where(db.game_exclusions.c.game_id == args.game)
            ).scalar_one_or_none()
            if already is not None:
                print(f"Game {args.game} is excluded already ({already}); nothing more recorded.")
                return 0
            conn.execute(insert(db.game_exclusions).values(game_id=args.game, reason=reason))
    finally:
        engine.dispose()
    was = "in the corpus" if standing == "exported" else f"left out already ({standing})"
    print(f"Excluded game {args.game}, which was {was}. It is left out from the next export.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

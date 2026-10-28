"""Record a withdrawal that came by email (Consent Screen §2.7; T3.2).

    python -m fish_server.withdraw someone@example.org

Finds the player with that address and records their withdrawal, as one that came by email.
Every game they played leaves the corpus at the next export, and they can no longer play. It
connects as the server's own login, which may add the record but never change or remove one,
so a withdrawal cannot be undone from here either. Run it on Render from the service's Shell.
"""

import argparse
import sys

from sqlalchemy import Engine, create_engine, pool, select

from fish_server import db
from fish_server.consent import standing, withdraw
from fish_server.settings import consent_version, database_url
from fish_server.signin import normalize_email


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.withdraw", description="Record a withdrawal sent by email."
    )
    parser.add_argument("email", help="the address the request came from")
    args = parser.parse_args(argv)
    try:
        email = normalize_email(args.email)
    except ValueError:
        parser.error(f"{args.email!r} is not an email address")
    engine = engine or create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.begin() as conn:
            player = conn.execute(
                select(db.player_contacts.c.player_id).where(db.player_contacts.c.email == email)
            ).scalar_one_or_none()
            if player is None:
                print(f"No player has the address {email}; nothing recorded.")
                return 1
            if standing(conn, player, consent_version()).withdrawn:
                print(f"{email} had already withdrawn; nothing more recorded.")
                return 0
            withdraw(conn, player, "email")
    finally:
        engine.dispose()
    print(f"Recorded the withdrawal of {email}. Their games leave the corpus at the next export.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

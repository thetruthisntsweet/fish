"""Requests about a person's email address, and the 31 March deletion (T3.8; Terms and Privacy
§2 "What you can do" and "How long it is kept"; docs/runbooks/requests.md).

    python -m fish_server.contacts show someone@example.org
    python -m fish_server.contacts correct old@example.org new@example.org
    python -m fish_server.contacts forget someone@example.org
    python -m fish_server.contacts forget-everyone --yes        # 31 March 2027 only

- ``show``: what the study holds about the person with that address, to send them.
- ``correct``: their address becomes the new one, which no one else may have; sign-in links
  to the old one are deleted, so it is kept nowhere.
- ``forget``: their address is deleted, from ``player_contacts`` and every sign-in link, and
  every sign-in they have is ended, so they can no longer sign in or be emailed. Their games
  and acceptances stay: a person who wants those gone too withdraws first.
- ``forget-everyone``: every address and every sign-in record is deleted, the email list's
  deletion on 31 March 2027 (Research Plan §6). Resend's copy is deleted by hand that day
  (docs/runbooks/email.md §5).

These change private tables, which the server's own login may only add to, so they connect as
the owner (``FISH_ADMIN_DATABASE_URL``). Run them on Render from the service's Shell. Nothing
here touches the corpus or any append-only table.
"""

import argparse
import sys
import uuid
from datetime import datetime

from sqlalchemy import Connection, Engine, create_engine, delete, func, pool, select, update
from sqlalchemy.dialects.postgresql import insert as upsert

from fish_server import db
from fish_server.settings import admin_database_url
from fish_server.signin import normalize_email


class NotFoundError(Exception):
    """No player has the address."""


def player_with(conn: Connection, email: str) -> uuid.UUID:
    player = conn.execute(
        select(db.player_contacts.c.player_id).where(db.player_contacts.c.email == email)
    ).scalar_one_or_none()
    if player is None:
        raise NotFoundError(f"No player has the address {email}.")
    return player


def _day(moment: datetime) -> str:
    return f"{moment.day} {moment:%B %Y}"


def held(conn: Connection, email: str) -> list[str]:
    """What the study holds about the person with ``email``, as lines to send them."""
    player = player_with(conn, email)
    p = db.players.c
    joined = conn.execute(select(p.signed_up_at, p.cohort).where(p.player_id == player)).one()
    c = db.consents.c
    accepted = conn.execute(
        select(c.at, c.version, c.terms_version).where(c.player_id == player).order_by(c.at)
    ).all()
    withdrawn = conn.execute(
        select(db.withdrawals.c.at, db.withdrawals.c.channel).where(
            db.withdrawals.c.player_id == player
        )
    ).first()
    s, g = db.seats.c, db.games.c
    games = conn.execute(
        select(func.count(), func.min(g.started_at), func.max(g.started_at))
        .select_from(db.seats.join(db.games, s.game_id == g.game_id))
        .where(s.player_id == player)
    ).one()
    n = db.note_answers.c
    notes = conn.execute(
        select(func.count())
        .select_from(db.note_answers.join(db.seats, (n.game_id == s.game_id) & (n.seat == s.seat)))
        .where(s.player_id == player)
    ).scalar_one()
    sessions = conn.execute(
        select(func.count()).select_from(db.sessions).where(db.sessions.c.player_id == player)
    ).scalar_one()
    group = "a group that plays only with each other" if joined.cohort else "the main group"
    lines = [
        f"Email address: {email}",
        f"Random player ID: {player}",
        f"Signed up: {_day(joined.signed_up_at)}, placed in {group}",
    ]
    for row in accepted:
        terms = f", terms {row.terms_version}" if row.terms_version else ""
        lines.append(
            f"Accepted the study information {row.version}{terms} on {_day(row.at)}, "
            "with all three confirmations"
        )
    if not accepted:
        lines.append("Accepted the study information: never")
    if withdrawn is not None:
        lines.append(f"Withdrew on {_day(withdrawn.at)}, {withdrawn.channel}")
    count, first, last = games
    if count:
        lines.append(f"Games played: {count}, from {_day(first)} to {_day(last)}")
    else:
        lines.append("Games played: none")
    lines.append(f"Note-taking answers: {notes}")
    lines.append(f"Sign-ins: {sessions}, each kept only in scrambled form")
    return lines


def correct(conn: Connection, old: str, new: str) -> None:
    """The player with ``old`` now has ``new``, which must be no one's; links to ``old`` are
    deleted."""
    player = player_with(conn, old)
    taken = conn.execute(
        select(db.player_contacts.c.player_id).where(db.player_contacts.c.email == new)
    ).scalar_one_or_none()
    if taken is not None:
        raise ValueError(f"{new} is another player's address; nothing changed.")
    conn.execute(
        update(db.player_contacts).where(db.player_contacts.c.player_id == player).values(email=new)
    )
    _drop_links(conn, old)


def _end_sessions(conn: Connection, player: uuid.UUID | None) -> int:
    """End every sign-in (of ``player``, or everyone's) that has not ended; how many."""
    query = select(db.sessions.c.token_hash).where(
        db.sessions.c.token_hash.not_in(select(db.session_ends.c.token_hash))
    )
    if player is not None:
        query = query.where(db.sessions.c.player_id == player)
    live = conn.execute(query).scalars().all()
    if live:
        conn.execute(
            upsert(db.session_ends)
            .values([{"token_hash": token} for token in live])
            .on_conflict_do_nothing()
        )
    return len(live)


def _drop_links(conn: Connection, email: str | None) -> int:
    """Delete the sign-in links (to ``email``, or all) and their uses; how many links."""
    links = select(db.sign_in_links.c.token_hash)
    if email is not None:
        links = links.where(db.sign_in_links.c.email == email)
    conn.execute(delete(db.sign_in_uses).where(db.sign_in_uses.c.token_hash.in_(links)))
    gone = delete(db.sign_in_links)
    if email is not None:
        gone = gone.where(db.sign_in_links.c.email == email)
    return conn.execute(gone).rowcount


def forget(conn: Connection, email: str) -> tuple[int, int]:
    """Delete ``email`` everywhere it is kept, and end its player's sign-ins. Returns the
    links deleted and the sign-ins ended."""
    player = player_with(conn, email)
    ended = _end_sessions(conn, player)
    links = _drop_links(conn, email)
    conn.execute(delete(db.player_contacts).where(db.player_contacts.c.player_id == player))
    return links, ended


def forget_everyone(conn: Connection) -> dict[str, int]:
    """Delete every address and every sign-in record (31 March 2027); what was deleted."""
    counts = {
        "addresses": conn.execute(delete(db.player_contacts)).rowcount,
        "sign-in links": _drop_links(conn, None),
    }
    conn.execute(delete(db.session_ends))
    counts["sign-ins"] = conn.execute(delete(db.sessions)).rowcount
    return counts


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.contacts",
        description="Answer a request about an email address, or delete the email list.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="what the study holds about an address").add_argument("email")
    fix = commands.add_parser("correct", help="change a player's address")
    fix.add_argument("old")
    fix.add_argument("new")
    commands.add_parser("forget", help="delete an address and end its sign-ins").add_argument(
        "email"
    )
    everyone = commands.add_parser("forget-everyone", help="31 March 2027: delete the list")
    everyone.add_argument("--yes", action="store_true", help="really delete every address")
    args = parser.parse_args(argv)

    addresses: dict[str, str] = {}
    for name in ("email", "old", "new"):
        if hasattr(args, name):
            raw = getattr(args, name)
            try:
                addresses[name] = normalize_email(raw)
            except ValueError:
                parser.error(f"{raw!r} is not an email address")
    if args.command == "forget-everyone" and not args.yes:
        parser.error("forget-everyone deletes every address: add --yes, on 31 March 2027 only")

    engine = engine or create_engine(admin_database_url(), poolclass=pool.NullPool)
    try:
        with engine.begin() as conn:
            match args.command:
                case "show":
                    print("\n".join(held(conn, addresses["email"])))
                case "correct":
                    correct(conn, addresses["old"], addresses["new"])
                    print(f"{addresses['old']} is now {addresses['new']}.")
                    print("In Resend, change the contact's address the same way.")
                case "forget":
                    links, ended = forget(conn, addresses["email"])
                    print(
                        f"Deleted {addresses['email']}, with {links} sign-in links, and ended "
                        f"{ended} sign-ins. Their games and acceptances stay."
                    )
                    print("In Resend, delete the contact too (docs/runbooks/requests.md).")
                case _:
                    counts = forget_everyone(conn)
                    print("Deleted: " + ", ".join(f"{n:,} {what}" for what, n in counts.items()))
                    print("Now delete Resend's contacts (docs/runbooks/email.md §5).")
    except NotFoundError as missing:
        print(f"{missing} Nothing changed.")
        return 1
    except ValueError as refused:
        print(str(refused))
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())

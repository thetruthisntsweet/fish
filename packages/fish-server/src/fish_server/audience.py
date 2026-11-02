"""Copy the study's players into Resend's "Players" segments, for the weekly game-night emails
(T4.1; docs/recruitment.md §4; docs/runbooks/email.md).

    python -m fish_server.audience --dry-run     # what would change, changing nothing
    python -m fish_server.audience

Run it in the production service's **Shell** (the database is reachable only inside Render)
before each Monday's M4. It asks for a full-access Resend key, which is never stored on the
server; FISH_RESEND_AUDIENCE_KEY may hold it for that one command instead.

Every player who has accepted the study information and not withdrawn is put in "Players:
group 1", or "Players: group 2" if in the held-out cohort, and anyone else is taken out of
both. A player who has withdrawn is also taken out of "Invited", so that no
invitation reaches someone who can no longer play. Nothing else is changed: a contact who
unsubscribed stays unsubscribed, and new contacts are only ever added, never resubscribed.
It prints counts, never addresses, and running it twice changes nothing the second time.
"""

import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import quote

from sqlalchemy import Connection, Engine, create_engine, exists, pool, select

from fish_server import db
from fish_server.settings import consent_version, database_url

GROUPS: Final = {False: "Players: group 1", True: "Players: group 2"}
"""The segment for each value of the cohort flag (group 2 is the held-out cohort)."""
INVITED: Final = ("Invited",)
"""The invitation lists, which a withdrawn player leaves too."""
KEY_VAR: Final = "FISH_RESEND_AUDIENCE_KEY"
API: Final = "https://api.resend.com"
PAUSE: Final = 0.2
"""Seconds between calls: five a second, half Resend's limit of ten."""


class AudienceError(Exception):
    """The copy cannot go on; the reason is for the person running it."""


# ---------------------------------------------------------------- the study's side


@dataclass(frozen=True, slots=True)
class Players:
    groups: dict[str, frozenset[str]]
    """The addresses each Players segment should hold."""
    withdrawn: frozenset[str]


def players(conn: Connection) -> Players:
    """Who should hear about game nights: everyone who accepted and has not withdrawn."""
    c, p = db.player_contacts.c, db.players.c
    accepted = exists().where(db.consents.c.player_id == p.player_id)
    left = exists().where(db.withdrawals.c.player_id == p.player_id)
    rows = conn.execute(
        select(c.email, p.cohort, left.label("left")).join(db.players).where(accepted)
    ).all()
    groups = {name: frozenset(r.email for r in rows if r.cohort == held and not r.left)
              for held, name in GROUPS.items()}  # fmt: skip
    return Players(groups, frozenset(r.email for r in rows if r.left))


# ---------------------------------------------------------------- Resend's side


@dataclass(frozen=True, slots=True)
class Member:
    """A contact in a segment: Resend's id for it, and whether it unsubscribed."""

    id: str
    unsubscribed: bool


type Send = Callable[[str, str, object], tuple[int, dict[str, object]]]
"""(method, path, body) -> (status, answer): one call to Resend's API."""


def http(key: str, sleep: Callable[[float], None] = time.sleep) -> Send:
    """Calls to Resend with ``key``, paced, and retried when Resend asks for patience."""

    def send(method: str, path: str, body: object) -> tuple[int, dict[str, object]]:
        for _ in range(5):
            sleep(PAUSE)
            request = urllib.request.Request(
                API + path,
                method=method,
                data=None if body is None else json.dumps(body).encode(),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "fish-audience/1",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return response.status, json.loads(response.read() or b"{}")
            except urllib.error.HTTPError as refused:
                with refused:
                    answer = refused.read()
                    wait = refused.headers.get("retry-after")
                if refused.code != 429:
                    return refused.code, json.loads(answer or b"{}")
                sleep(float(wait or 1))
        raise AudienceError("Resend kept saying to slow down; try again in a minute")

    return send


@dataclass(slots=True)
class Resend:
    send: Send
    calls: int = field(default=0)

    def call(self, method: str, path: str, body: object = None) -> dict[str, object]:
        self.calls += 1
        status, answer = self.send(method, path, body)
        if status >= 300:
            raise AudienceError(f"Resend answered {status} to {method} {path.split('?')[0]}")
        return answer

    def segments(self) -> dict[str, str]:
        """Every segment's id, by name."""
        data = self.call("GET", "/segments").get("data")
        return (
            {str(s["name"]): str(s["id"]) for s in data if isinstance(s, dict)}
            if isinstance(data, list)
            else {}
        )

    def members(self, segment: str) -> dict[str, Member]:
        """A segment's contacts, by address in lower case (as the study stores addresses)."""
        found: dict[str, Member] = {}
        after = ""
        while True:
            page = self.call("GET", f"/segments/{segment}/contacts?limit=100{after}")
            data = page.get("data")
            contacts = [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []
            for contact in contacts:
                member = Member(str(contact["id"]), bool(contact.get("unsubscribed")))
                found[str(contact["email"]).lower()] = member
            if not page.get("has_more") or not contacts:
                return found
            after = f"&after={contacts[-1]['id']}"

    def add(self, email: str, segment: str) -> None:
        """Put ``email`` in ``segment``; a new contact is made if there is none, and an
        existing one keeps its subscription as it is."""
        status, _ = self.send(
            "POST", f"/contacts/{quote(email, safe='@')}/segments/{segment}", None
        )
        self.calls += 1
        if status == 404:
            self.call("POST", "/contacts", {"email": email, "segments": [{"id": segment}]})
        elif status >= 300:
            raise AudienceError(f"Resend answered {status} when adding a contact to a segment")

    def remove(self, contact: str, segment: str) -> None:
        """Take the contact with id ``contact`` out of ``segment``."""
        self.call("DELETE", f"/contacts/{contact}/segments/{segment}")


# ---------------------------------------------------------------- the copy


@dataclass(frozen=True, slots=True)
class Change:
    segment: str
    add: frozenset[str]
    remove: frozenset[str]
    kept: int
    unsubscribed: int
    """Of those it will hold, how many unsubscribed: they are kept, and Resend skips them."""


def changes(wanted: Players, current: dict[str, dict[str, Member]]) -> list[Change]:
    """What to change in each segment: ``current`` is each segment's members by name."""
    out: list[Change] = []
    for name, should in wanted.groups.items():
        have = current[name]
        out.append(
            Change(
                name,
                should - have.keys(),
                frozenset(have.keys() - should),
                len(should & have.keys()),
                sum(1 for e in should & have.keys() if have[e].unsubscribed),
            )
        )
    for name in INVITED:
        if name in current:
            have = current[name]
            gone = frozenset(wanted.withdrawn & have.keys())
            out.append(Change(name, frozenset(), gone, len(have) - len(gone), 0))
    return out


def copy(engine: Engine, resend: Resend, *, dry_run: bool) -> list[Change]:
    with engine.connect() as conn:
        wanted = players(conn)
    ids = resend.segments()
    missing = [name for name in GROUPS.values() if name not in ids]
    if missing:
        raise AudienceError(f"Resend has no segment named {missing[0]!r}: make it first")
    current = {
        name: resend.members(ids[name]) for name in (*GROUPS.values(), *INVITED) if name in ids
    }
    planned = changes(wanted, current)
    if not dry_run:
        for change in planned:
            for email in sorted(change.add):
                resend.add(email, ids[change.segment])
            for email in sorted(change.remove):
                resend.remove(current[change.segment][email].id, ids[change.segment])
    return planned


def key_from(environ: dict[str, str], ask: Callable[[str], str], interactive: bool) -> str:
    key = environ.get(KEY_VAR, "").strip()
    if not key and interactive:
        key = ask("Resend key with full access (not shown, not stored): ").strip()
    if not key:
        raise AudienceError(f"no Resend key: run it in the Shell, or set {KEY_VAR}")
    return key


def main(
    argv: list[str] | None = None, engine: Engine | None = None, send: Send | None = None
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.audience",
        description="Copy the study's players into Resend's Players segments.",
    )
    parser.add_argument("--dry-run", action="store_true", help="show what would change")
    args = parser.parse_args(argv)
    try:
        if consent_version().endswith("-pilot"):
            raise AudienceError("this is the pilot site: its players get no game-night emails")
        if send is None:
            send = http(key_from(dict(os.environ), getpass.getpass, sys.stdin.isatty()))
        engine = engine or create_engine(database_url(), poolclass=pool.NullPool)
        resend = Resend(send)
        try:
            planned = copy(engine, resend, dry_run=args.dry_run)
        finally:
            engine.dispose()
    except AudienceError as reason:
        print(f"Nothing more changed: {reason}.", file=sys.stderr)
        return 1
    verb = ("would add", "would remove") if args.dry_run else ("added", "removed")
    for change in planned:
        unsubscribed = f", {change.unsubscribed} unsubscribed" if change.unsubscribed else ""
        print(
            f"{change.segment}: {verb[0]} {len(change.add)}, {verb[1]} {len(change.remove)}, "
            f"kept {change.kept}{unsubscribed}"
        )
    print(f"({resend.calls} calls to Resend{'; nothing changed' if args.dry_run else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

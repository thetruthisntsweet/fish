"""Signing in with an emailed link (T3.1).

A player asks for a link with their email address. The server keeps only the SHA-256 hash of
the link's random token, with the address and an expiry 15 minutes on, and emails the link.
Opening it shows a page with one button; pressing it uses the link, once, and starts a
session: a second random token, kept as its hash for 30 days, in an HTTP-only cookie. The
button is there because mail scanners open links in emails by themselves; a link that signed
in on being opened would be used up before the player saw it.

The first time an address signs in it becomes a player (docs/corpus.md §2): the next number
from ``signup_numbers``, and the held-out cohort drawn from it at once, before any game
(``fish_rules.cohort``, §2.1). The address goes to ``player_contacts``, which never leaves the
server. Two first sign-ins from one address at the same moment make one player, not two: a
transaction lock on the address puts them one after the other.

The consent screen comes first (Consent Screen §2): a link asked for after pressing Continue
carries the version of the text accepted, and using it records the acceptance
(``fish_server.consent``), for a new player or one returning on a new device alike.

The server's login may only read and insert (D15), so using a link and ending a session are
rows of their own, and a primary key on each makes it happen at most once.

Limits, so the sign-in form cannot be used to send floods of email: 3 links per address in
15 minutes, and at most ``daily_link_limit()`` emails from the whole server in 24 hours
(``fish_server.settings``). ``RateLimiter`` adds a limit per network address, held in memory.
"""

import hashlib
import re
import secrets
import uuid
from collections import deque
from collections.abc import Callable
from datetime import timedelta
from typing import Final

from sqlalchemy import Connection, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as upsert

from fish_rules.cohort import in_cohort
from fish_server import db
from fish_server.consent import accept

LINK_LIFETIME: Final = timedelta(minutes=15)
SESSION_LIFETIME: Final = timedelta(days=30)

LINKS_PER_ADDRESS: Final = 3
ADDRESS_WINDOW: Final = timedelta(minutes=15)
"""At most this many links for one address in this long."""

DAY: Final = timedelta(hours=24)

_EMAIL: Final = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s.]+")
MAX_EMAIL_LENGTH: Final = 254


class TooManyLinksError(Exception):
    """A limit on sign-in emails was reached. ``for_address`` is False when the limit was the
    whole server's."""

    def __init__(self, *, for_address: bool) -> None:
        reason = "for this address" if for_address else "today"
        super().__init__(f"too many sign-in emails {reason}")
        self.for_address = for_address


def normalize_email(raw: str) -> str:
    """``raw`` as the one form the server stores: trimmed and in lower case. Raises ValueError
    if it is not an email address."""
    email = raw.strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or _EMAIL.fullmatch(email) is None:
        raise ValueError("not an email address")
    return email


def token_hash(token: str) -> str:
    """What the server keeps of a token: its SHA-256, as 64 hex digits."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    """A random token of 256 bits, safe in a URL and a cookie."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------- links


def request_link(
    conn: Connection,
    email: str,
    *,
    daily_limit: int,
    consent_version: str | None = None,
    lifetime: timedelta = LINK_LIFETIME,
) -> str:
    """A new link token for ``email`` (already normalized), carrying the acceptance of text
    ``consent_version`` made on the screen before it, if any. Raises TooManyLinksError if the
    address or the server has had its share of links."""
    now = func.now()
    recent = conn.execute(
        select(func.count())
        .select_from(db.sign_in_links)
        .where(db.sign_in_links.c.email == email)
        .where(db.sign_in_links.c.created_at > now - ADDRESS_WINDOW)
    ).scalar_one()
    if recent >= LINKS_PER_ADDRESS:
        raise TooManyLinksError(for_address=True)
    today = conn.execute(
        select(func.count())
        .select_from(db.sign_in_links)
        .where(db.sign_in_links.c.created_at > now - DAY)
    ).scalar_one()
    if today >= daily_limit:
        raise TooManyLinksError(for_address=False)
    token = new_token()
    conn.execute(
        insert(db.sign_in_links).values(
            token_hash=token_hash(token),
            email=email,
            expires_at=now + lifetime,
            consent_version=consent_version,
        )
    )
    return token


def use_link(conn: Connection, token: str, *, cohort_seed: int) -> uuid.UUID | None:
    """Use the link ``token``: the player it signs in, made a player now if the address is
    new, with the acceptance it carries recorded. None if there is no such link, it has
    expired, or it was used before."""
    hashed = token_hash(token)
    link = conn.execute(
        select(db.sign_in_links.c.email, db.sign_in_links.c.consent_version)
        .where(db.sign_in_links.c.token_hash == hashed)
        .where(db.sign_in_links.c.expires_at > func.now())
    ).one_or_none()
    if link is None:
        return None
    used = conn.execute(
        upsert(db.sign_in_uses)
        .values(token_hash=hashed)
        .on_conflict_do_nothing()
        .returning(db.sign_in_uses.c.token_hash)
    ).scalar_one_or_none()
    if used is None:
        return None
    player = player_for(conn, link.email, cohort_seed=cohort_seed)
    if link.consent_version is not None:
        accept(conn, player, link.consent_version)
    return player


def player_for(conn: Connection, email: str, *, cohort_seed: int) -> uuid.UUID:
    """The player with address ``email``, signed up now if there is none (§2, §2.1)."""
    lock = text("SELECT pg_advisory_xact_lock(hashtextextended(:email, 0))")
    conn.execute(lock, {"email": email})
    found = conn.execute(
        select(db.player_contacts.c.player_id).where(db.player_contacts.c.email == email)
    ).scalar_one_or_none()
    if found is not None:
        return found
    number = conn.execute(select(db.signup_numbers.next_value())).scalar_one()
    player = uuid.uuid4()
    conn.execute(
        insert(db.players).values(
            player_id=player, signup_number=number, cohort=in_cohort(cohort_seed, number)
        )
    )
    conn.execute(insert(db.player_contacts).values(player_id=player, email=email))
    return player


# ---------------------------------------------------------------- sessions


def start_session(
    conn: Connection, player: uuid.UUID, *, lifetime: timedelta = SESSION_LIFETIME
) -> str:
    """A new session token for ``player``."""
    token = new_token()
    conn.execute(
        insert(db.sessions).values(
            token_hash=token_hash(token), player_id=player, expires_at=func.now() + lifetime
        )
    )
    return token


def session_player(conn: Connection, token: str) -> uuid.UUID | None:
    """The player session ``token`` belongs to, or None if it is unknown, expired or ended."""
    hashed = token_hash(token)
    ended = select(db.session_ends.c.token_hash).where(db.session_ends.c.token_hash == hashed)
    return conn.execute(
        select(db.sessions.c.player_id)
        .where(db.sessions.c.token_hash == hashed)
        .where(db.sessions.c.expires_at > func.now())
        .where(~ended.exists())
    ).scalar_one_or_none()


def end_session(conn: Connection, token: str) -> None:
    """End session ``token``, if there is one. Ending it twice changes nothing."""
    hashed = token_hash(token)
    known = conn.execute(
        select(db.sessions.c.token_hash).where(db.sessions.c.token_hash == hashed)
    ).scalar_one_or_none()
    if known is not None:
        conn.execute(upsert(db.session_ends).values(token_hash=hashed).on_conflict_do_nothing())


# ---------------------------------------------------------------- per network address


MAX_KEYS: Final = 10_000


class RateLimiter:
    """At most ``limit`` requests per key in any ``window_s`` seconds, kept in memory. A
    server restart forgets it, which is fine for a limit that only slows a flood down."""

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float]) -> None:
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self._seen: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Count a request for ``key``; False if it is over the limit."""
        now = self.clock()
        if len(self._seen) > MAX_KEYS:  # forget addresses with nothing recent
            self._seen = {k: v for k, v in self._seen.items() if v and v[-1] > now - self.window_s}
        seen = self._seen.setdefault(key, deque())
        while seen and seen[0] <= now - self.window_s:
            seen.popleft()
        if len(seen) >= self.limit:
            return False
        seen.append(now)
        return True

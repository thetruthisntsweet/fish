"""Acceptances and withdrawals (T3.2; Consent Screen §2, §3; docs/corpus.md §2.2).

A person accepts the consent screen by ticking its three confirmations and pressing Continue.
A new person does it before they have an address on file, so the acceptance travels with their
sign-in link and is recorded when the link is used (``fish_server.signin``); someone already
signed in accepts a new version with ``POST /consent``. Either way it is one row of
``consents``, and the site shows one version (``FISH_CONSENT_VERSION``): everyone accepts it
before their next game.

The terms of use and privacy policy are agreed to with it, on the same screen (T3.8): the
acceptance names the version of them shown too (``FISH_TERMS_VERSION``), and a person may
play only while both versions they last accepted are the site's. A new version of either
brings the consent screen back.

A withdrawal is a record of its own (``POST /withdraw`` on the website, or
``python -m fish_server.withdraw`` for one that came by email) and is never undone: every game
the person played leaves the corpus at the next export. A person who has withdrawn may not
play again, since their new games would take five other people's games out with them.
"""

from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, insert, select

from fish_server import db

CHANNELS: Final = ("website", "email")


class Acceptance(BaseModel):
    """What the consent screen sends when Continue is pressed: the study information's
    version, the terms' version, and the three confirmations."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: str
    terms_version: str
    us_resident_adult: bool
    agrees: bool
    no_outside_communication: bool


@dataclass(frozen=True, slots=True)
class Shown:
    """What this site asks people to accept: the study information's version and the
    terms' version (``fish_server.settings``)."""

    consent: str
    terms: str


def problem(acceptance: Acceptance, shown: Shown) -> str | None:
    """Why ``acceptance`` cannot be recorded, or None: it must be of the texts this site
    shows, with all three confirmations ticked (Consent Screen §2.3)."""
    if acceptance.version != shown.consent:
        current = shown.consent
        return f"This site shows the study information {current}; reload it and accept that."
    if acceptance.terms_version != shown.terms:
        return f"This site shows the terms {shown.terms}; reload it and accept those."
    ticked = (acceptance.us_resident_adult, acceptance.agrees, acceptance.no_outside_communication)
    if not all(ticked):
        return "All three confirmations are needed to take part."
    return None


def accept(conn: Connection, player: object, version: str, terms: str) -> None:
    """Record that ``player`` accepted text ``version`` with all three confirmations, and
    agreed to the terms ``terms`` with it."""
    conn.execute(
        insert(db.consents).values(
            player_id=player,
            version=version,
            terms_version=terms,
            us_resident_adult=True,
            agrees=True,
            no_outside_communication=True,
        )
    )


def withdraw(conn: Connection, player: object, channel: Literal["website", "email"]) -> None:
    """Record ``player``'s withdrawal, which came through ``channel``."""
    conn.execute(insert(db.withdrawals).values(player_id=player, channel=channel))


@dataclass(frozen=True, slots=True)
class Standing:
    """Where a player stands with the study: the versions of the study information and of
    the terms in their latest acceptance (None if none), whether they have withdrawn, and
    whether they may play under what the site shows."""

    accepted: str | None
    terms_accepted: str | None
    withdrawn: bool
    shown: Shown

    @property
    def current(self) -> str:
        return self.shown.consent

    @property
    def up_to_date(self) -> bool:
        """Whether the latest acceptance is of both texts the site shows now."""
        return self.accepted == self.shown.consent and self.terms_accepted == self.shown.terms

    @property
    def may_play(self) -> bool:
        return self.up_to_date and not self.withdrawn

    def refusal(self) -> str | None:
        """Why the player may not join a game now, or None."""
        if self.withdrawn:
            return "You have withdrawn from the study, so you cannot play."
        if not self.up_to_date:
            return "Accept the study information first."
        return None


def standing(conn: Connection, player: object, shown: Shown) -> Standing:
    """``player``'s standing under what the site shows."""
    c = db.consents.c
    latest = conn.execute(
        select(c.version, c.terms_version)
        .where(c.player_id == player)
        .order_by(c.at.desc(), c.consent_id.desc())
        .limit(1)
    ).one_or_none()
    withdrawn = conn.execute(
        select(db.withdrawals.c.withdrawal_id).where(db.withdrawals.c.player_id == player).limit(1)
    ).scalar_one_or_none()
    accepted, terms = (None, None) if latest is None else (latest.version, latest.terms_version)
    return Standing(accepted, terms, withdrawn is not None, shown)

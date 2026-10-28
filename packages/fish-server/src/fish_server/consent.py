"""Acceptances and withdrawals (T3.2; Consent Screen §2, §3; docs/corpus.md §2.2).

A person accepts the consent screen by ticking its three confirmations and pressing Continue.
A new person does it before they have an address on file, so the acceptance travels with their
sign-in link and is recorded when the link is used (``fish_server.signin``); someone already
signed in accepts a new version with ``POST /consent``. Either way it is one row of
``consents``, and the site shows one version (``FISH_CONSENT_VERSION``): everyone accepts it
before their next game.

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
    """What the consent screen sends when Continue is pressed."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: str
    us_resident_adult: bool
    agrees: bool
    no_outside_communication: bool


def problem(acceptance: Acceptance, current: str) -> str | None:
    """Why ``acceptance`` cannot be recorded, or None: it must be of the text this site shows,
    with all three confirmations ticked (Consent Screen §2.3)."""
    if acceptance.version != current:
        return f"This site shows the study information {current}; reload it and accept that."
    ticked = (acceptance.us_resident_adult, acceptance.agrees, acceptance.no_outside_communication)
    if not all(ticked):
        return "All three confirmations are needed to take part."
    return None


def accept(conn: Connection, player: object, version: str) -> None:
    """Record that ``player`` accepted text ``version`` with all three confirmations."""
    conn.execute(
        insert(db.consents).values(
            player_id=player,
            version=version,
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
    """Where a player stands with the study: the latest version they accepted (None if
    none), whether they have withdrawn, and whether they may play under ``current``."""

    accepted: str | None
    withdrawn: bool
    current: str

    @property
    def may_play(self) -> bool:
        return self.accepted == self.current and not self.withdrawn

    def refusal(self) -> str | None:
        """Why the player may not join a game now, or None."""
        if self.withdrawn:
            return "You have withdrawn from the study, so you cannot play."
        if self.accepted != self.current:
            return "Accept the study information first."
        return None


def standing(conn: Connection, player: object, current: str) -> Standing:
    """``player``'s standing under the text ``current``."""
    c = db.consents.c
    accepted = conn.execute(
        select(c.version)
        .where(c.player_id == player)
        .order_by(c.at.desc(), c.consent_id.desc())
        .limit(1)
    ).scalar_one_or_none()
    withdrawn = conn.execute(
        select(db.withdrawals.c.withdrawal_id).where(db.withdrawals.c.player_id == player).limit(1)
    ).scalar_one_or_none()
    return Standing(accepted, withdrawn is not None, current)

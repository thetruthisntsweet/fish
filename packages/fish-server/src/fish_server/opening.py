"""When a site's tables are open (T4.3; docs/runbooks/launch.md, docs/runbooks/pilot.md).

Anyone signed up may play at any time (docs/recruitment.md §3), so every game on the study's
site is a study game, and every game on the pilot site a pilot game. Each site therefore says
in its settings when it takes new tables, by Eastern day:

- ``FISH_OPENS=2026-12-08`` on the study's site: no new tables before that day, so the site can
  be built and checked before launch without anyone playing on it early;
- ``FISH_PILOT_ENDED=2026-12-06`` on the pilot site: no new tables from that day, and the site
  points people to the study, so no one plays pilot games no one will use;
- ``FISH_TABLES_OPEN=yes``, only with ``FISH_PILOT_ENDED``, takes tables again on the pilot
  site, to test on staging after the pilot. It is never set for long.

Unset, as in development and tests, tables are always open. A closed site still signs people
in, shows the study information and lets people withdraw; only finding a table, making a room
and joining one are refused, with the same words the lobby shows (``/study``'s ``tables``).
A game already being played goes on.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal
from zoneinfo import ZoneInfo

EASTERN: Final = ZoneInfo("America/New_York")
STUDY_SITE: Final = "https://fish.thedefinitivesanjeevexperience.com"
"""Where the pilot site sends people once the pilot is over (docs/recruitment.md §2)."""


@dataclass(frozen=True, slots=True)
class Closed:
    """Why this site takes no new tables, in the words players are shown."""

    reason: Literal["not_open", "pilot_over"]
    message: str
    link: str | None = None
    """An address the message refers people to, shown as a link after it."""

    def sentence(self) -> str:
        """The message with its link, as one sentence for the game socket."""
        return f"{self.message} {self.link}" if self.link else self.message


def _day(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B %Y}"


def closed(
    now: datetime,
    opens: date | None = None,
    pilot_ended: date | None = None,
    override: bool = False,
) -> Closed | None:
    """Why no new tables may be made at ``now``, or None if they may (see above)."""
    today = now.astimezone(EASTERN).date()
    if opens is not None and today < opens:
        return Closed(
            "not_open",
            f"The study opens on {_day(opens)}. Until then, no games can be played here.",
        )
    if pilot_ended is not None and today >= pilot_ended and not override:
        return Closed(
            "pilot_over",
            "The pilot is over: thank you for playing. The study itself is at",
            STUDY_SITE,
        )
    return None


def as_json(why: Closed | None) -> dict[str, str | None] | None:
    """``/study``'s ``tables``: null while tables are open."""
    if why is None:
        return None
    return {"reason": why.reason, "message": why.message, "link": why.link}

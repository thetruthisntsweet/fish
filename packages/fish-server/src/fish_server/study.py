"""The versions of the study information a site can show (Consent Screen §1, §4; T3.3).

Each version is one text, word for word, which the web client holds
(``client/src/study/texts.ts``), and the last day its participants can withdraw through the
website (Consent Screen §2.7). ``client/src/study/versions.json`` lists the same versions and
days, and tests on both sides check that they agree. A site shows one of them
(``FISH_CONSENT_VERSION``). A new text is a new entry here and in the client, never a change
to an old one: everyone who accepted an old text can still reread exactly what they agreed to.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final


@dataclass(frozen=True, slots=True)
class Version:
    """One text: the last day to withdraw on the website, as the text says it, and the moment
    that day ends in US Eastern time, when the button closes."""

    withdraw_until: date
    closes: datetime

    def withdrawal_open(self, now: datetime) -> bool:
        return now < self.closes


VERSIONS: Final[dict[str, Version]] = {
    # "You can withdraw until 14 February 2027." Eastern Standard Time then (UTC-5).
    "v1.0": Version(date(2027, 2, 14), datetime(2027, 2, 15, 5, tzinfo=UTC)),
    # "Until 31 March 2027, you can withdraw..." Eastern Daylight Time then (UTC-4).
    "v1.0-pilot": Version(date(2027, 3, 31), datetime(2027, 4, 1, 4, tzinfo=UTC)),
}
"""Every text this site can show, by version."""


BOT_DELAYS: Final = "stand-in-v1"
"""The bots' delay table on the study's site (R.8.8; ``fish_agents.delays``). Until the pilot
report exists it is a stand-in, which the study must never open with: on 6 or 7 December it
becomes the table built from the pilot (docs/runbooks/pilot.md §4)."""
LAUNCH: Final = date(2026, 12, 8)
"""The day the study opens (docs/recruitment.md §2)."""


TERMS: Final[tuple[str, ...]] = ("v1.0", "v1.0-pilot")
"""Every version of the terms of use and privacy policy this site can show (Terms and
Privacy §1-3; T3.8). The two documents share a version: a change to either is a new version
of both, accepted on the consent screen before the next game. ``-pilot`` versions are the
pilot site's, shown with a pilot consent text. Like the consent texts, the web client holds
each one word for word, and an old one is never changed."""

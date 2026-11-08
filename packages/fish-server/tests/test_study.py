"""Tests for fish_server.study (T3.3): every version the server can show has its text in the
web client, with the same last day to withdraw, and that day ends in US Eastern time."""

import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from fish_agents.delays import load
from fish_server.study import BOT_DELAYS, LAUNCH, TERMS, VERSIONS

CLIENT_VERSIONS: Final = (
    Path(__file__).resolve().parents[3] / "client" / "src" / "study" / "versions.json"
)
"""The versions the client has a text for (client/src/study/texts.ts checks that it does)."""

CLIENT_TERMS: Final = CLIENT_VERSIONS.parents[1] / "legal" / "versions.json"
"""The terms versions the client has (client/src/legal/legal.test.ts checks that it does)."""


def test_the_client_has_a_text_for_exactly_the_versions_the_server_knows() -> None:
    client = json.loads(CLIENT_VERSIONS.read_text(encoding="utf-8"))
    server = {name: {"withdrawUntil": v.withdraw_until.isoformat()} for name, v in VERSIONS.items()}
    assert client == server


def test_the_client_has_terms_for_exactly_the_versions_the_server_knows() -> None:
    """T3.8: the terms of use and privacy policy, one version for both."""
    assert json.loads(CLIENT_TERMS.read_text(encoding="utf-8")) == list(TERMS)


@pytest.mark.parametrize(
    ("version", "last_day"), [("v1.0", "2027-02-14"), ("v1.0-pilot", "2027-03-31")]
)
def test_withdrawing_closes_at_the_end_of_the_texts_last_day_in_eastern_time(
    version: str, last_day: str
) -> None:
    """Consent Screen §1, §4: "You can withdraw until 14 February 2027"; the pilot, until 31
    March 2027."""
    text = VERSIONS[version]
    assert text.withdraw_until.isoformat() == last_day
    midnight = datetime.combine(text.withdraw_until + timedelta(days=1), time())
    assert text.closes == midnight.replace(tzinfo=ZoneInfo("America/New_York"))
    assert text.withdrawal_open(text.closes - timedelta(microseconds=1))
    assert not text.withdrawal_open(text.closes)


def test_the_study_never_opens_with_stand_in_bot_delays() -> None:
    """R.8.8: from the day the study opens, its bots wait as the pilot's people did. Until
    the pilot report exists (6 or 7 December) ``BOT_DELAYS`` names a stand-in; this test
    starts failing on 8 December if it still does (docs/runbooks/pilot.md §4 step 3)."""
    table = load(BOT_DELAYS)
    assert table.percentiles is not None  # a percentile table, never the pilot's uniform wait
    if datetime.now(UTC).date() >= LAUNCH:
        assert not table.stand_in, f"{BOT_DELAYS} is a stand-in: make the pilot's table"

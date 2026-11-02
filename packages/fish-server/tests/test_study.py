"""Tests for fish_server.study (T3.3): every version the server can show has its text in the
web client, with the same last day to withdraw, and that day ends in US Eastern time."""

import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from fish_server.study import VERSIONS

CLIENT_VERSIONS: Final = (
    Path(__file__).resolve().parents[3] / "client" / "src" / "study" / "versions.json"
)
"""The versions the client has a text for (client/src/study/texts.ts checks that it does)."""


def test_the_client_has_a_text_for_exactly_the_versions_the_server_knows() -> None:
    client = json.loads(CLIENT_VERSIONS.read_text(encoding="utf-8"))
    server = {name: {"withdrawUntil": v.withdraw_until.isoformat()} for name, v in VERSIONS.items()}
    assert client == server


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

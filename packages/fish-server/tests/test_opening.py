"""When a site takes new tables (fish_server.opening, settings.tables_closed; T4.3,
docs/runbooks/launch.md and pilot.md): the study's site from its opening day, the pilot site
until its pilot ends, by Eastern day; the hub refusing a table with the lobby's words, and
nothing else."""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from fish_server.hub import Connection, Hub
from fish_server.lobby import Player
from fish_server.opening import STUDY_SITE, Closed, as_json, closed
from fish_server.protocol import CreateRoom, JoinQueue, JoinRoom, Leave
from fish_server.settings import OPENS_VAR, PILOT_ENDED_VAR, TABLES_OPEN_VAR, tables_closed

OPENS = date(2026, 12, 8)
ENDED = date(2026, 12, 6)


def eastern(day: int, hour: int, minute: int = 0) -> datetime:
    """That December 2026 moment in Eastern time (UTC-5 then)."""
    return (
        datetime(2026, 12, day, hour + 5, minute, tzinfo=UTC)
        if hour < 19
        else datetime(2026, 12, day + 1, hour - 19, minute, tzinfo=UTC)
    )


def test_the_study_opens_at_midnight_eastern_on_its_day() -> None:
    before = closed(eastern(7, 23, 59), opens=OPENS)
    assert before is not None
    assert before.reason == "not_open"
    assert before.sentence() == (
        "The study opens on Tuesday 8 December 2026. Until then, no games can be played here."
    )
    assert closed(eastern(8, 0), opens=OPENS) is None
    assert closed(eastern(13, 20), opens=OPENS) is None


def test_the_pilot_ends_at_midnight_eastern_and_points_to_the_study() -> None:
    assert closed(eastern(5, 23, 59), pilot_ended=ENDED) is None  # the last night
    after = closed(eastern(6, 0), pilot_ended=ENDED)
    assert after is not None
    assert (after.reason, after.link) == ("pilot_over", STUDY_SITE)
    assert after.sentence() == (
        "The pilot is over: thank you for playing. The study itself is at "
        "https://fish.thedefinitivesanjeevexperience.com"
    )
    assert closed(eastern(9, 12), pilot_ended=ENDED, override=True) is None  # testing staging


def test_with_neither_day_tables_are_always_open() -> None:
    assert closed(datetime(2020, 1, 1, tzinfo=UTC)) is None
    assert as_json(None) is None
    shut = Closed("not_open", "Not yet.")
    assert as_json(shut) == {"reason": "not_open", "message": "Not yet.", "link": None}


def test_the_settings_are_read_and_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (OPENS_VAR, PILOT_ENDED_VAR, TABLES_OPEN_VAR):
        monkeypatch.delenv(var, raising=False)
    assert tables_closed(eastern(1, 12)) is None
    monkeypatch.setenv(OPENS_VAR, "2026-12-08")
    assert tables_closed(eastern(7, 12)) is not None
    monkeypatch.setenv(TABLES_OPEN_VAR, "yes")
    with pytest.raises(ValueError, match="reopens only a pilot site"):
        tables_closed(eastern(7, 12))  # the study's site can't be opened early
    monkeypatch.delenv(OPENS_VAR)
    monkeypatch.setenv(PILOT_ENDED_VAR, "2026-12-06")
    assert tables_closed(eastern(9, 12)) is None
    monkeypatch.setenv(TABLES_OPEN_VAR, "true")
    with pytest.raises(ValueError, match="FISH_TABLES_OPEN is yes or unset"):
        tables_closed(eastern(9, 12))
    monkeypatch.delenv(TABLES_OPEN_VAR)
    assert tables_closed(eastern(9, 12)) is not None
    monkeypatch.setenv(PILOT_ENDED_VAR, "6 December")
    with pytest.raises(ValueError, match="FISH_PILOT_ENDED is a day like 2026-12-08"):
        tables_closed(eastern(9, 12))


class Recorder:
    """A connection's far end: what was sent to it."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def transmit(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def shut(self) -> None:
        pass


class Asked(Hub):
    """A hub that is never asked about consent while its tables are closed."""

    def refusal(self, player: Player) -> str | None:
        raise AssertionError("asked the database although tables are closed")


def test_a_closed_site_refuses_every_way_to_a_table_and_only_those() -> None:
    shut = Closed("not_open", "The study opens on Tuesday 8 December 2026.")
    hub = Asked(lambda: None, "test", tables=lambda: shut)  # pyright: ignore[reportArgumentType]
    far = Recorder()
    connection = Connection(Player(uuid.uuid4(), False), far.transmit, far.shut)
    hub.connect(connection)

    async def ask() -> None:
        for message in (
            JoinQueue(type="join_queue"),
            CreateRoom(type="create_room"),
            JoinRoom(type="join_room", code="ABCDEF"),
            Leave(type="leave"),
        ):
            await hub._lobby(connection, message)  # pyright: ignore[reportPrivateUsage]
        connection.close()
        await connection.run()

    asyncio.run(ask())
    errors = [(m["code"], m["message"]) for m in far.sent if m["type"] == "error"]
    assert errors == [("not_now", "The study opens on Tuesday 8 December 2026.")] * 3
    assert [m["type"] for m in far.sent][-1] == "lobby"  # leaving still answers
    assert hub.lobby.waiting(connection.player) is None  # never placed anywhere

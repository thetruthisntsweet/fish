"""The recruitment emails (scripts/broadcast.py; docs/recruitment.md; T4.1): every message on
the page can be sent, word for word, only to the lists its heading names; M4 announces every
game night in §3 exactly once to each group it is for; and Resend is asked for exactly the
broadcast intended."""

import importlib.util
import io
import json
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from email.message import Message as Headers
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("broadcast", ROOT / "scripts" / "broadcast.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


broadcast = load()
PAGE: str = (ROOT / "docs" / "recruitment.md").read_text(encoding="utf-8")
MONDAYS = [date(2026, 12, 14) + timedelta(weeks=w) for w in range(9)]  # 14 Dec to 8 Feb


def prepared(key: str, segment: str, week: date | None = None, **values: str) -> Any:
    return broadcast.prepared(PAGE, key, segment, values, week)


# ---------------------------------------------------------------- the page


def test_the_page_has_seven_messages_each_to_its_lists() -> None:
    found = broadcast.messages(PAGE)
    assert list(found) == ["M1", "M2", "M3", "M4", "M5", "M6", "M7"]
    players = ("Players: group 1", "Players: group 2")
    assert {k: m.to for k, m in found.items()} == {
        "M1": ("Gov School",),
        "M2": ("Gov School",),
        "M3": ("Gov School", "Pool"),
        "M4": players,
        "M5": ("Gov School", "Pool"),
        "M6": ("Gov School", "Pool"),
        "M7": players,
    }
    for message in found.values():
        assert message.body[0] == "Hi,"
        assert message.body[-1] == "[unsubscribe]"  # every bulk email can be stopped


def test_the_sender_is_the_one_the_page_names() -> None:
    assert f"`{broadcast.SENDER}`, replies\nto {broadcast.REPLY_TO}" in PAGE


def test_the_schedule_runs_from_opening_night_to_the_last_with_true_weekdays() -> None:
    nights = broadcast.nights(PAGE)  # a date whose weekday is wrong on the page is refused
    days = [n.day for n in nights]
    assert days == sorted(days)
    assert (days[0], days[-1]) == (date(2026, 12, 13), date(2027, 2, 14))
    assert {n.who for n in nights} == {"everyone", "group 1", "group 2"}
    assert not {date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 31), date(2027, 1, 1)} & set(
        days
    )


# ---------------------------------------------------------------- filled in


@pytest.mark.parametrize("key", ["M1", "M2", "M5", "M6"])
def test_messages_with_nothing_to_fill_are_sent_as_written(key: str) -> None:
    message = prepared(key, "Test")
    assert message.body == broadcast.messages(PAGE)[key].body


def test_the_game_length_is_filled_in_and_nothing_is_left_in_braces() -> None:
    with pytest.raises(broadcast.RefusedError, match=r"\{N\} needs a value"):
        prepared("M3", "Pool")
    message = prepared("M3", "Pool", N="25")
    assert any("A game takes about" in line for line in message.body)
    assert "25 minutes" in broadcast.as_text(message)


@pytest.mark.parametrize("group", [1, 2])
def test_each_group_hears_of_each_of_its_nights_exactly_once(group: int) -> None:
    segment = f"Players: group {group}"
    told: list[str] = []
    for monday in MONDAYS:
        message = prepared("M4", segment, monday)
        told += [line[2:] for line in message.body if line.startswith("- ")]
        days = message.subject.removeprefix("Fish this week: ")
        assert days in ("Sunday", "Wednesday and Sunday")
    mine = [n for n in broadcast.nights(PAGE) if n.who in ("everyone", f"group {group}")]
    first = mine[0].day
    expected = [n.shown() for n in mine if n.day > first]  # opening night comes before M4 starts
    expected[-1] += " (the last night)"
    assert told == expected


def test_the_last_week_says_so_in_the_pages_words() -> None:
    assert broadcast.WEEK_OPENING in broadcast.messages(PAGE)["M4"].body
    assert f'the first line reads: "{broadcast.LAST_WEEK_OPENING}"' in PAGE.replace("\n", " ")
    last = prepared("M4", "Players: group 2", MONDAYS[-1])
    assert broadcast.LAST_WEEK_OPENING in last.body
    assert last.body[-1] != broadcast.WEEK_OPENING
    week = prepared("M4", "Players: group 2", MONDAYS[0])
    assert broadcast.WEEK_OPENING in week.body


@pytest.mark.parametrize(
    ("key", "segment", "week", "reason"),
    [
        ("M1", "Pool", None, "M1 goes to Gov School"),
        ("M3", "Players: group 1", None, "goes to Gov School or Pool"),
        ("M7", "Gov School", None, "goes to Players: group 1 or Players: group 2"),
        ("M4", "Players: group 1", None, "M4 needs --week"),
        ("M4", "Players: group 1", date(2026, 12, 15), "a Monday, not a Tuesday"),
        ("M4", "Players: group 1", date(2027, 3, 1), "no game nights"),
        ("M9", "Test", None, "no message M9"),
    ],
)
def test_anything_else_is_refused(key: str, segment: str, week: date | None, reason: str) -> None:
    with pytest.raises(broadcast.RefusedError, match=reason):
        prepared(key, segment, week, N="25")


# ---------------------------------------------------------------- as an email


def test_the_html_links_addresses_keeps_letter_breaks_and_can_unsubscribe() -> None:
    message = prepared("M3", "Pool", N="25")
    body = broadcast.as_html(message)
    url = "https://fish.thedefinitivesanjeevexperience.com"
    assert f'<a href="{url}">{url}</a>, read' in body  # the comma stays outside the link
    assert '<a href="mailto:hkeldeib@fcps.edu">hkeldeib@fcps.edu</a>.' in body
    assert "<p>Thanks,<br>Sanjeev</p>" in body
    assert "<li>Opening night: Sunday 13 December, 8:00 – 10:00 pm</li>" in body  # noqa: RUF001
    assert 'href="{{{RESEND_UNSUBSCRIBE_URL}}}"' in body
    assert "players&#x27; actions" in body  # escaped


def test_the_text_version_is_the_same_words() -> None:
    text = broadcast.as_text(prepared("M2", "Gov School"))
    assert text.startswith("Hi,\n\nA reminder that the Fish pilot starts tomorrow.")
    assert "\n- Tuesday 1 December, 8:00 – 10:00 pm\n" in text  # noqa: RUF001
    assert text.endswith("Thanks,\nSanjeev\n\nUnsubscribe: {{{RESEND_UNSUBSCRIBE_URL}}}\n")


# ---------------------------------------------------------------- Resend


class FakeResend:
    """Answers the two calls the script makes, and keeps what it was sent."""

    def __init__(self, segments: list[dict[str, str]]) -> None:
        self.segments = segments
        self.sent: list[tuple[str, str, dict[str, str], Any]] = []
        self.refuse = False

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        body = None if request.data is None else json.loads(request.data)  # pyright: ignore[reportArgumentType]
        self.sent.append((request.get_method(), request.full_url, dict(request.headers), body))
        if self.refuse:
            raise urllib.error.HTTPError(
                request.full_url, 422, "bad", Headers(), io.BytesIO(b'{"message": "no"}')
            )
        answer = {"data": self.segments} if request.get_method() == "GET" else {"id": "b-1"}
        return io.BytesIO(json.dumps(answer).encode())


@pytest.fixture
def resend(monkeypatch: pytest.MonkeyPatch) -> FakeResend:
    fake = FakeResend([{"id": "s-test", "name": "Test"}, {"id": "s-pool", "name": "Pool"}])
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def test_a_draft_is_made_for_the_named_segment(resend: FakeResend) -> None:
    message = prepared("M3", "Pool", N="25")
    assert broadcast.create(message, "Pool", "re_key", None) == "b-1"
    (_, segments, headers, _), (method, url, _, body) = resend.sent
    assert segments == "https://api.resend.com/segments"
    assert headers["Authorization"] == "Bearer re_key"
    assert (method, url) == ("POST", "https://api.resend.com/broadcasts")
    assert body == {
        "segment_id": "s-pool",
        "from": broadcast.SENDER,
        "reply_to": broadcast.REPLY_TO,
        "subject": "Play Fish for a research study, from Sunday 13 December",
        "html": broadcast.as_html(message),
        "text": broadcast.as_text(message),
        "name": "M3 Launch invitation: Pool",
    }  # a draft: nothing is sent until it is sent from the dashboard


def test_a_scheduled_broadcast_says_when(resend: FakeResend) -> None:
    at = datetime(2026, 11, 16, 14, tzinfo=UTC)
    broadcast.create(prepared("M1", "Test"), "Test", "re_key", at)
    body = resend.sent[-1][3]
    assert (body["send"], body["scheduled_at"]) == (True, "2026-11-16T14:00:00+00:00")


def test_a_segment_resend_does_not_have_is_named(resend: FakeResend) -> None:
    with pytest.raises(
        broadcast.RefusedError, match="no segment named 'Gov School'; it has: Test, Pool"
    ):
        broadcast.create(prepared("M1", "Gov School"), "Gov School", "re_key", None)


def test_resends_refusal_is_shown(resend: FakeResend) -> None:
    resend.refuse = True
    with pytest.raises(broadcast.RefusedError, match=r'422 to GET /segments: \{"message": "no"\}'):
        broadcast.create(prepared("M1", "Test"), "Test", "re_key", None)


# ---------------------------------------------------------------- the command


def test_without_create_it_only_shows_the_message(
    resend: FakeResend, capsys: pytest.CaptureFixture[str]
) -> None:
    assert broadcast.main(["M2", "--segment", "Test"]) == 0
    out = capsys.readouterr().out
    assert "Subject:  Fish pilot: tomorrow at 8 pm, then Thursday and Saturday" in out
    assert "preview only" in out
    assert resend.sent == []


def test_create_needs_the_key_and_a_future_time_with_a_zone(
    resend: FakeResend, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(broadcast.KEY_VAR, raising=False)
    now = datetime(2026, 11, 2, tzinfo=UTC)
    assert broadcast.main(["M1", "--segment", "Test", "--create"], now) == 1
    assert "RESEND_BROADCAST_KEY is not set" in capsys.readouterr().err
    for when, reason in [
        ("2026-11-16T09:00:00", "needs a time zone"),
        ("2026-11-01T09:00:00-05:00", "in the past"),
    ]:
        assert broadcast.main(["M1", "--segment", "Test", "--create", "--send-at", when], now) == 1
        assert reason in capsys.readouterr().err
    assert (
        broadcast.main(["M1", "--segment", "Test", "--send-at", "2026-11-16T09:00:00-05:00"], now)
        == 1
    )
    assert "--send-at needs --create" in capsys.readouterr().err
    monkeypatch.setenv(broadcast.KEY_VAR, "re_key")
    when = "2026-11-16T09:00:00-05:00"
    assert broadcast.main(["M1", "--segment", "Test", "--create", "--send-at", when], now) == 0
    assert "scheduled for 2026-11-16T09:00:00-05:00" in capsys.readouterr().out
    assert broadcast.main(["M1", "--segment", "Test", "--create"], now) == 0
    assert "Draft b-1 made" in capsys.readouterr().out

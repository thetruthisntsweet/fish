"""Copying players into Resend's segments (fish_server.audience; T4.1): each player who
accepted and has not withdrawn is in their group's segment and nowhere else among the Players
segments; a withdrawn player leaves the invitation lists too; an unsubscribed contact is never
resubscribed; and a second run changes nothing. Skipped without FISH_TEST_DATABASE_URL."""

import io
import itertools
import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from email.message import Message as Headers
from typing import Any
from urllib.parse import unquote

import pytest
from sqlalchemy import Engine, create_engine, pool, select

from fish_server import db
from fish_server.audience import (
    GROUPS,
    KEY_VAR,
    AudienceError,
    Resend,
    http,
    key_from,
    main,
)
from fish_server.consent import accept, withdraw
from fish_server.settings import CONSENT_VERSION_VAR, database_url
from fish_server.signin import player_for

ONE, TWO = GROUPS[False], GROUPS[True]
ADDRESSES = itertools.count(1)


class FakeResend:
    """Resend's contacts and segments, kept in memory, answering as its API does; a page of a
    segment holds two contacts, so paging is exercised."""

    def __init__(self, names: tuple[str, ...] = (ONE, TWO, "Gov School", "Pool")) -> None:
        self.ids = {name: f"seg-{i}" for i, name in enumerate(names)}
        self.contacts: dict[str, dict[str, Any]] = {}
        self.created: list[str] = []

    def contact(self, email: str, *segments: str, unsubscribed: bool = False) -> None:
        self.contacts[email] = {
            "id": f"c-{len(self.contacts)}",
            "unsubscribed": unsubscribed,
            "segments": {self.ids[s] for s in segments},
        }

    def members(self, name: str) -> set[str]:
        return {e for e, c in self.contacts.items() if self.ids[name] in c["segments"]}

    def __call__(self, method: str, path: str, body: object) -> tuple[int, dict[str, object]]:
        if (method, path) == ("GET", "/segments"):
            return 200, {"data": [{"id": i, "name": n} for n, i in self.ids.items()]}
        if found := re.fullmatch(r"/segments/([^/]+)/contacts\?limit=100(?:&after=(.+))?", path):
            segment, after = found.groups()
            inside = sorted(
                (c["id"], e, c["unsubscribed"])
                for e, c in self.contacts.items()
                if segment in c["segments"]
            )
            rest = [x for x in inside if after is None or x[0] > after]
            page = [{"id": i, "email": e.upper(), "unsubscribed": u} for i, e, u in rest[:2]]
            return 200, {"data": page, "has_more": len(rest) > 2}
        if found := re.fullmatch(r"/contacts/([^/]+)/segments/([^/]+)", path):
            email, segment = unquote(found.group(1)), found.group(2)
            by_id = {c["id"]: e for e, c in self.contacts.items()}
            email = by_id.get(email, email)  # a contact's id or its address
            if email not in self.contacts:
                return 404, {"message": "Contact not found"}
            members = self.contacts[email]["segments"]
            (members.add if method == "POST" else members.discard)(segment)
            return 200, {"id": self.contacts[email]["id"]}
        if (method, path) == ("POST", "/contacts"):
            assert isinstance(body, dict)
            email = str(body["email"])  # pyright: ignore[reportUnknownArgumentType]
            assert "unsubscribed" not in body  # never touches anyone's subscription
            self.created.append(email)
            self.contact(email)
            self.contacts[email]["segments"] = {s["id"] for s in body["segments"]}  # pyright: ignore[reportUnknownVariableType]
            return 200, {"id": self.contacts[email]["id"]}
        raise AssertionError((method, path))


@pytest.fixture
def engine(server_env: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    monkeypatch.delenv(CONSENT_VERSION_VAR, raising=False)
    made = create_engine(database_url(), poolclass=pool.NullPool)
    yield made
    made.dispose()


def sign_up(engine: Engine, cohort: bool, *, accepted: bool = True, left: bool = False) -> str:
    """A player in (``cohort``) or out of the held-out cohort, by trying addresses until one
    is drawn into it; their address."""
    while True:
        email = (
            f"p{next(ADDRESSES)}-{cohort}-{accepted}-{left}@example.org".lower()
        )  # as the server keeps it
        with engine.begin() as conn:
            player = player_for(conn, email, cohort_seed=5)
            held = conn.execute(
                select(db.players.c.cohort).where(db.players.c.player_id == player)
            ).scalar_one()
            if held != cohort:
                continue
            if accepted:
                accept(conn, player, "v1.0")
            if left:
                withdraw(conn, player, "website")
            return email


def run(engine: Engine, fake: FakeResend, *argv: str) -> int:
    return main(list(argv), create_engine(database_url(), poolclass=pool.NullPool), fake)


def test_each_player_is_put_in_their_groups_segment(
    engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    out = {sign_up(engine, False) for _ in range(3)}
    held = {sign_up(engine, True) for _ in range(2)}
    sign_up(engine, False, accepted=False)  # signed in, never accepted: no emails
    gone = sign_up(engine, True, left=True)
    fake = FakeResend()
    fake.contact("stale@example.org", ONE)  # in a Players segment, but no player
    fake.contact(gone, "Pool", TWO)
    fake.contact("friend@example.org", "Pool")
    quiet = next(iter(out))
    fake.contact(quiet, "Pool", unsubscribed=True)  # unsubscribed from the invitations

    assert run(engine, fake) == 0
    assert (fake.members(ONE), fake.members(TWO)) == (out, held)
    assert fake.members("Pool") == {"friend@example.org", quiet}  # the withdrawn player left
    assert fake.contacts[quiet]["unsubscribed"] is True  # added, never resubscribed
    assert quiet not in fake.created
    printed = capsys.readouterr().out
    assert f"{ONE}: added 3, removed 1, kept 0" in printed
    assert f"{TWO}: added 2, removed 1, kept 0" in printed
    assert "Pool: added 0, removed 1, kept 2" in printed
    assert "@" not in printed  # counts only, never an address

    assert run(engine, fake) == 0  # nothing left to do
    again = capsys.readouterr().out
    assert f"{ONE}: added 0, removed 0, kept 3, 1 unsubscribed" in again
    assert f"{TWO}: added 0, removed 0, kept 2" in again


def test_a_dry_run_changes_nothing(engine: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    sign_up(engine, False)
    fake = FakeResend()
    assert run(engine, fake, "--dry-run") == 0
    assert fake.members(ONE) == set()
    assert f"{ONE}: would add 1, would remove 0, kept 0" in capsys.readouterr().out


def test_the_players_segments_must_exist(
    engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(engine, FakeResend((ONE, "Pool"))) == 1
    assert f"no segment named {TWO!r}" in capsys.readouterr().err


def test_the_pilot_site_has_no_game_night_emails(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(CONSENT_VERSION_VAR, "v1.0-pilot")
    fake = FakeResend()
    assert run(engine, fake) == 1
    assert "pilot site" in capsys.readouterr().err


def test_a_refusal_from_resend_stops_the_copy(
    engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    sign_up(engine, False)
    fake = FakeResend()

    def broken(method: str, path: str, body: object) -> tuple[int, dict[str, object]]:
        return (500, {}) if method == "POST" else fake(method, path, body)

    assert main([], create_engine(database_url(), poolclass=pool.NullPool), broken) == 1
    assert "Resend answered 500 when adding a contact" in capsys.readouterr().err


# ---------------------------------------------------------------- the key and the calls


def test_the_key_is_asked_for_and_never_kept() -> None:
    assert key_from({KEY_VAR: " re_env "}, lambda _: "re_typed", True) == "re_env"
    assert key_from({}, lambda _: " re_typed ", True) == "re_typed"
    with pytest.raises(AudienceError, match="no Resend key"):
        key_from({}, lambda _: "re_typed", False)
    with pytest.raises(AudienceError, match="no Resend key"):
        key_from({}, lambda _: "", True)


def test_calls_are_paced_and_retried_when_resend_says_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers: list[Any] = [429, 200, 200]
    seen: list[urllib.request.Request] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> Any:
        seen.append(request)
        if answers.pop(0) == 429:
            headers = Headers()
            headers["retry-after"] = "3"
            raise urllib.error.HTTPError(request.full_url, 429, "slow", headers, io.BytesIO(b"{}"))
        answer = io.BytesIO(json.dumps({"data": []}).encode())
        answer.status = 200  # type: ignore[attr-defined]
        return answer

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    waits: list[float] = []
    send = http("re_key", waits.append)
    assert send("GET", "/segments", None) == (200, {"data": []})
    assert waits == [0.2, 3.0, 0.2]
    assert seen[-1].get_header("Authorization") == "Bearer re_key"
    assert Resend(send).segments() == {}


def test_a_refusal_other_than_wait_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(request: urllib.request.Request, timeout: float) -> Any:
        raise urllib.error.HTTPError(request.full_url, 404, "no", Headers(), io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert http("re_key", lambda _: None)("POST", "/contacts/x/segments/y", None) == (404, {})


def test_resend_that_never_stops_saying_wait_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(request: urllib.request.Request, timeout: float) -> Any:
        raise urllib.error.HTTPError(request.full_url, 429, "slow", Headers(), io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(AudienceError, match="slow down"):
        http("re_key", lambda _: None)("GET", "/segments", None)


def test_without_a_key_nothing_is_done(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(KEY_VAR, raising=False)  # and no terminal to ask in
    assert main([], create_engine(database_url(), poolclass=pool.NullPool)) == 1
    assert "no Resend key" in capsys.readouterr().err


def test_resends_refusal_is_named(engine: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    def refusing(method: str, path: str, body: object) -> tuple[int, dict[str, object]]:
        return 401, {"message": "API key is invalid"}

    assert main([], create_engine(database_url(), poolclass=pool.NullPool), refusing) == 1
    assert "Resend answered 401 to GET /segments" in capsys.readouterr().err


def test_without_invitation_lists_only_the_players_segments_change(engine: Engine) -> None:
    held = sign_up(engine, True)
    fake = FakeResend((ONE, TWO))
    assert run(engine, fake) == 0
    assert fake.members(TWO) == {held}

"""Consent and withdrawal on the server (T3.2; Consent Screen §2, §3): an acceptance made on the
screen travels with the sign-in link and is recorded when it is used; a signed-in player can
accept a new version; only the current text, with all three confirmations, is accepted; a
withdrawal, from the website or by email, is recorded once and never undone; and only a
player who has accepted the current text and not withdrawn may wait for a game; and
withdrawing on the website closes after the text's last day (T3.3). Each acceptance names the
terms of use and privacy policy agreed to with it, and a new version of them needs a new
acceptance too (T3.8). Skipped without FISH_TEST_DATABASE_URL."""

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, pool, select

from fish_server import db, settings
from fish_server.app import app as server
from fish_server.auth import clock, limiter
from fish_server.consent import Acceptance, Shown, Standing, accept, problem, standing
from fish_server.lobby import Player
from fish_server.mailer import MemoryMailer, mailer
from fish_server.settings import (
    COHORT_SEED_VAR,
    CONSENT_VERSION_VAR,
    TERMS_VERSION_VAR,
    consent_version,
    database_url,
    terms_version,
)
from fish_server.signin import player_for
from fish_server.study import TERMS, VERSIONS
from fish_server.withdraw import main as withdraw_by_email

NOW = datetime(2026, 11, 20, 18, tzinfo=UTC)
"""A day of the study, well before anyone's last day to withdraw."""

STUDY = Shown("v1.0", "v1.0")
PILOT = Shown("v1.0-pilot", "v1.0-pilot")

ACCEPTED: dict[str, object] = {
    "version": "v1.0",
    "terms_version": "v1.0",
    "us_resident_adult": True,
    "agrees": True,
    "no_outside_communication": True,
}


@pytest.fixture
def app(server_env: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    monkeypatch.setenv(COHORT_SEED_VAR, "11")
    monkeypatch.delenv(CONSENT_VERSION_VAR, raising=False)
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def client(app: Engine) -> Iterator[tuple[TestClient, MemoryMailer]]:
    mail = MemoryMailer()
    server.dependency_overrides[mailer] = lambda: mail
    server.dependency_overrides[clock] = lambda: NOW
    limiter._seen.clear()  # pyright: ignore[reportPrivateUsage]
    with TestClient(server) as http:
        yield http, mail
    server.dependency_overrides.clear()


def sign_in(http: TestClient, mail: MemoryMailer, email: str, consent: object = None) -> int:
    """Ask for a link (with the screen's acceptance, if given), use it; the status of the
    request for the link."""
    response = http.post("/auth/link", json={"email": email, "consent": consent})
    if response.status_code != 202:
        return response.status_code
    match = re.search(r"token=([A-Za-z0-9_\-]+)", mail.sent[-1]["text"])
    assert match is not None
    verified = http.post("/auth/verify", data={"token": match.group(1)}, follow_redirects=False)
    assert verified.status_code == 303
    return 202


def consents(app: Engine) -> list[Any]:
    with app.connect() as conn:
        return list(conn.execute(select(db.consents)).mappings())


def withdrawals(app: Engine) -> list[Any]:
    with app.connect() as conn:
        return list(conn.execute(select(db.withdrawals)).mappings())


# ---------------------------------------------------------------- what may be accepted


def test_only_the_current_text_with_every_confirmation_is_accepted() -> None:
    good = Acceptance.model_validate(ACCEPTED)
    assert problem(good, STUDY) is None
    assert "study information v1.0-pilot" in (problem(good, PILOT) or "")
    assert "terms v1.1" in (problem(good, Shown("v1.0", "v1.1")) or "")
    for box in ("us_resident_adult", "agrees", "no_outside_communication"):
        unticked = Acceptance.model_validate(ACCEPTED | {box: False})
        assert problem(unticked, STUDY) == "All three confirmations are needed to take part."
    without_terms = {k: v for k, v in ACCEPTED.items() if k != "terms_version"}
    with pytest.raises(ValueError, match="terms_version"):
        Acceptance.model_validate(without_terms)


def test_the_site_s_version_comes_from_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONSENT_VERSION_VAR, raising=False)
    assert consent_version() == "v1.0"
    monkeypatch.setenv(CONSENT_VERSION_VAR, "v1.0-pilot")
    assert consent_version() == "v1.0-pilot"
    monkeypatch.setenv(CONSENT_VERSION_VAR, "v9.9")  # a text the site does not have
    with pytest.raises(ValueError, match=r"one of v1\.0, v1\.0-pilot, not 'v9\.9'"):
        consent_version()


def test_the_site_s_terms_go_with_its_consent_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONSENT_VERSION_VAR, raising=False)
    monkeypatch.delenv(TERMS_VERSION_VAR, raising=False)
    assert terms_version() == "v1.0"
    assert settings.shown() == STUDY
    monkeypatch.setenv(CONSENT_VERSION_VAR, "v1.0-pilot")
    assert terms_version() == "v1.0-pilot"  # the pilot site's, unless set
    assert settings.shown() == PILOT
    monkeypatch.setenv(TERMS_VERSION_VAR, "v1.0")
    with pytest.raises(ValueError, match="does not go with a pilot consent text"):
        terms_version()
    monkeypatch.setenv(CONSENT_VERSION_VAR, "v1.0")
    monkeypatch.setenv(TERMS_VERSION_VAR, "v1.0-pilot")
    with pytest.raises(ValueError, match="does not go with the study's consent text"):
        terms_version()
    monkeypatch.setenv(TERMS_VERSION_VAR, "v2.0")
    with pytest.raises(ValueError, match=r"one of v1\.0, v1\.0-pilot, not 'v2\.0'"):
        terms_version()


def test_standing_says_who_may_play() -> None:
    assert Standing("v1.0", "v1.0", False, STUDY).may_play
    assert Standing("v1.0", "v1.0", False, STUDY).refusal() is None
    first = "Accept the study information first."
    assert Standing(None, None, False, STUDY).refusal() == first
    assert Standing("v0.9", "v1.0", False, STUDY).refusal() == first
    assert Standing("v1.0", None, False, STUDY).refusal() == first  # accepted before the terms
    assert Standing("v1.0", "v1.0", False, Shown("v1.0", "v1.1")).refusal() == first
    assert "withdrawn" in (Standing("v1.0", "v1.0", True, STUDY).refusal() or "")
    assert not Standing("v1.0", "v1.0", True, STUDY).may_play


# ---------------------------------------------------------------- accepting


def test_the_screen_s_acceptance_is_recorded_when_the_link_is_used(
    client: tuple[TestClient, MemoryMailer], app: Engine
) -> None:
    http, mail = client
    assert http.get("/study").json() == {
        "version": "v1.0",
        "terms_version": "v1.0",
        "withdraw_until": "2027-02-14",
        "withdrawal_open": True,
    }
    assert sign_in(http, mail, "new@example.org", ACCEPTED) == 202
    (row,) = consents(app)
    assert (row["version"], row["terms_version"], row["agrees"]) == ("v1.0", "v1.0", True)
    me = http.get("/auth/me").json()
    assert me == {
        "signed_in": True,
        "study": {
            "current": "v1.0",
            "accepted": "v1.0",
            "terms_current": "v1.0",
            "terms_accepted": "v1.0",
            "withdrawn": False,
            "may_play": True,
        },
    }


def test_nothing_is_recorded_for_an_acceptance_that_is_not_one(
    client: tuple[TestClient, MemoryMailer], app: Engine
) -> None:
    http, mail = client
    unticked = ACCEPTED | {"no_outside_communication": False}
    assert sign_in(http, mail, "a@example.org", unticked) == 422
    assert sign_in(http, mail, "b@example.org", ACCEPTED | {"version": "v0.9"}) == 422
    assert sign_in(http, mail, "c@example.org", {"version": "v1.0"}) == 422
    assert sign_in(http, mail, "f@example.org", ACCEPTED | {"terms_version": "v0.9"}) == 422
    assert mail.sent == []
    with app.connect() as conn:
        assert conn.execute(select(func.count()).select_from(db.sign_in_links)).scalar() == 0
    assert consents(app) == []


def test_signing_in_again_needs_no_acceptance_and_a_new_version_needs_one(
    client: tuple[TestClient, MemoryMailer], app: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    http, mail = client
    sign_in(http, mail, "d@example.org", ACCEPTED)
    sign_in(http, mail, "d@example.org")  # on another device, no screen
    assert len(consents(app)) == 1
    monkeypatch.setitem(VERSIONS, "v1.1", VERSIONS["v1.0"])  # a new text (Consent Screen §2.8)
    monkeypatch.setenv(CONSENT_VERSION_VAR, "v1.1")
    assert http.get("/auth/me").json()["study"]["may_play"] is False
    assert http.post("/consent", json=ACCEPTED).status_code == 422  # not the text shown now
    assert http.post("/consent", json=ACCEPTED | {"version": "v1.1"}).status_code == 204
    assert [row["version"] for row in consents(app)] == ["v1.0", "v1.1"]
    assert http.get("/auth/me").json()["study"]["may_play"] is True


def test_new_terms_alone_need_a_new_acceptance(
    client: tuple[TestClient, MemoryMailer], app: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new version of the terms of use and privacy policy brings the consent screen back,
    with the same study information (T3.8)."""
    http, mail = client
    sign_in(http, mail, "t@example.org", ACCEPTED)
    monkeypatch.setattr(settings, "TERMS", (*TERMS, "v1.1"))
    monkeypatch.setenv(TERMS_VERSION_VAR, "v1.1")
    study = http.get("/auth/me").json()["study"]
    assert (study["accepted"], study["terms_accepted"], study["terms_current"]) == (
        "v1.0", "v1.0", "v1.1"
    )  # fmt: skip
    assert study["may_play"] is False
    assert http.post("/consent", json=ACCEPTED).status_code == 422  # not the terms shown now
    assert http.post("/consent", json=ACCEPTED | {"terms_version": "v1.1"}).status_code == 204
    assert [(r["version"], r["terms_version"]) for r in consents(app)] == [
        ("v1.0", "v1.0"), ("v1.0", "v1.1")
    ]  # fmt: skip
    assert http.get("/auth/me").json()["study"]["may_play"] is True


def test_an_acceptance_from_before_the_terms_must_be_made_again(
    client: tuple[TestClient, MemoryMailer], app: Engine
) -> None:
    """Rows written before migration 0007 have no terms version: those people accept the
    consent screen again, terms and all, before their next game."""
    http, mail = client
    sign_in(http, mail, "old@example.org")  # signed in, nothing accepted
    with app.begin() as conn:
        (player,) = conn.execute(select(db.players.c.player_id)).scalars()
        conn.execute(
            db.consents.insert().values(
                player_id=player, version="v1.0", us_resident_adult=True, agrees=True,
                no_outside_communication=True,
            )
        )  # fmt: skip
    study = http.get("/auth/me").json()["study"]
    assert (study["accepted"], study["terms_accepted"], study["may_play"]) == ("v1.0", None, False)
    assert http.post("/consent", json=ACCEPTED).status_code == 204
    assert http.get("/auth/me").json()["study"]["may_play"] is True


def test_accepting_and_withdrawing_need_a_session(
    client: tuple[TestClient, MemoryMailer],
) -> None:
    http, _ = client
    assert http.post("/consent", json=ACCEPTED).status_code == 401
    assert http.post("/withdraw", json={"confirm": True}).status_code == 401
    assert http.get("/auth/me").json() == {"signed_in": False}


# ---------------------------------------------------------------- withdrawing


def test_withdrawing_on_the_website_is_recorded_once_and_ends_playing(
    client: tuple[TestClient, MemoryMailer], app: Engine
) -> None:
    http, mail = client
    sign_in(http, mail, "e@example.org", ACCEPTED)
    assert http.post("/withdraw", json={"confirm": False}).status_code == 422  # confirm it
    assert http.post("/withdraw", json={}).status_code == 422
    assert http.post("/withdraw", json={"confirm": True}).status_code == 204
    assert http.post("/withdraw", json={"confirm": True}).status_code == 204
    assert [row["channel"] for row in withdrawals(app)] == ["website"]
    study = http.get("/auth/me").json()["study"]
    assert (study["withdrawn"], study["may_play"]) == (True, False)
    assert http.post("/consent", json=ACCEPTED).status_code == 409  # never undone


def test_the_pilot_site_says_its_own_last_day(
    client: tuple[TestClient, MemoryMailer], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, _ = client
    monkeypatch.setenv(CONSENT_VERSION_VAR, "v1.0-pilot")
    assert http.get("/study").json() == {
        "version": "v1.0-pilot",
        "terms_version": "v1.0-pilot",
        "withdraw_until": "2027-03-31",
        "withdrawal_open": True,
    }


def test_withdrawing_on_the_website_closes_after_the_last_day(
    client: tuple[TestClient, MemoryMailer], app: Engine
) -> None:
    http, mail = client
    sign_in(http, mail, "late@example.org", ACCEPTED)
    sign_in(http, mail, "early@example.org", ACCEPTED)
    closes = VERSIONS["v1.0"].closes
    server.dependency_overrides[clock] = lambda: closes - timedelta(seconds=1)
    assert http.get("/study").json()["withdrawal_open"] is True
    assert http.post("/withdraw", json={"confirm": True}).status_code == 204  # just in time
    server.dependency_overrides[clock] = lambda: closes
    assert http.get("/study").json()["withdrawal_open"] is False
    assert http.post("/withdraw", json={"confirm": True}).status_code == 204  # already done
    sign_in(http, mail, "late@example.org")
    late = http.post("/withdraw", json={"confirm": True})
    assert (late.status_code, late.json()) == (
        409,
        {"detail": "Withdrawing closed at the end of 14 February 2027."},
    )
    assert len(withdrawals(app)) == 1
    assert http.get("/auth/me").json()["study"]["withdrawn"] is False


def test_a_withdrawal_by_email_is_recorded_from_the_command_line(
    app: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    with app.begin() as conn:
        player = player_for(conn, "f@example.org", cohort_seed=1)
    assert withdraw_by_email([" F@Example.org "], app) == 0
    assert "Recorded the withdrawal of f@example.org" in capsys.readouterr().out
    assert withdraw_by_email(["f@example.org"], create_engine(database_url())) == 0
    assert "already withdrawn" in capsys.readouterr().out
    assert [(row["player_id"], row["channel"]) for row in withdrawals(app)] == [(player, "email")]
    assert withdraw_by_email(["nobody@example.org"], create_engine(database_url())) == 1
    assert "No player has the address" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        withdraw_by_email(["not an address"])


# ---------------------------------------------------------------- who may wait for a game


def test_the_lobby_lets_in_only_those_who_may_play(app: Engine) -> None:
    from fish_server.hub import Hub

    hub = Hub(lambda: app, "test", STUDY)
    with app.begin() as conn:
        ready, unready, gone = (player_for(conn, f"{n}@example.org", cohort_seed=1) for n in "xyz")
        accept(conn, ready, "v1.0", "v1.0")
        accept(conn, gone, "v1.0", "v1.0")
        conn.execute(db.withdrawals.insert().values(player_id=gone, channel="website"))
    assert hub.refusal(Player(ready, False)) is None
    assert hub.refusal(Player(unready, False)) == "Accept the study information first."
    assert "withdrawn" in (hub.refusal(Player(gone, False)) or "")
    with app.connect() as conn:
        assert standing(conn, uuid.uuid4(), STUDY) == Standing(None, None, False, STUDY)

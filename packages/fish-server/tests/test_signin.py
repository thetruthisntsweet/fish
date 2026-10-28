"""Signing in with an emailed link (T3.1): links work once and expire, the first sign-in of an
address makes a player with the cohort drawn from their sign-up number, sessions last until
they expire or end, and the limits on sign-in emails hold. Database tests are skipped without
FISH_TEST_DATABASE_URL."""

import re
import threading
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Final

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, pool, select
from sqlalchemy.exc import ProgrammingError

from fish_rules.cohort import in_cohort
from fish_server import db
from fish_server.app import app as server
from fish_server.auth import COOKIE, limiter
from fish_server.mailer import (
    RESEND_URL,
    ConsoleMailer,
    MailError,
    MemoryMailer,
    ResendMailer,
    mailer,
)
from fish_server.settings import (
    COHORT_SEED_VAR,
    DAILY_LINKS_VAR,
    EMAIL_FROM_VAR,
    EMAIL_VAR,
    PUBLIC_URL_VAR,
    RENDER_URL_VAR,
    RESEND_KEY_VAR,
    cohort_seed,
    daily_link_limit,
    database_url,
    email_from,
    email_mode,
    public_url,
)
from fish_server.signin import (
    LINKS_PER_ADDRESS,
    RateLimiter,
    TooManyLinksError,
    end_session,
    normalize_email,
    player_for,
    request_link,
    session_player,
    start_session,
    token_hash,
    use_link,
)

SEED: Final = 20261027


@pytest.fixture
def app(server_env: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """The server's own login, which only reads and inserts, with a cohort seed set."""
    monkeypatch.setenv(COHORT_SEED_VAR, str(SEED))
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------- addresses and tokens


@pytest.mark.parametrize(
    ("raw", "email"),
    [(" Ada@Example.ORG ", "ada@example.org"), ("a.b+c@x.co.uk", "a.b+c@x.co.uk")],
)
def test_addresses_are_kept_in_one_form(raw: str, email: str) -> None:
    assert normalize_email(raw) == email


@pytest.mark.parametrize(
    "raw", ["", "ada", "ada@", "@x.org", "ada@x", "a b@x.org", "a@x.", "a" * 250 + "@x.org"]
)
def test_what_is_not_an_address_is_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="not an email address"):
        normalize_email(raw)


def test_the_server_keeps_only_a_hash_of_each_token() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", token_hash("x"))
    assert token_hash("x") != token_hash("y")


# ---------------------------------------------------------------- links and players


def test_a_link_signs_in_once_and_makes_a_player(app: Engine) -> None:
    with app.begin() as conn:
        token = request_link(conn, "ada@example.org", daily_limit=90)
    with app.begin() as conn:
        player = use_link(conn, token, cohort_seed=SEED)
        assert player is not None
        row = conn.execute(select(db.players).where(db.players.c.player_id == player)).one()
        assert row.cohort == in_cohort(SEED, row.signup_number)  # drawn at sign-up (§2.1)
        contact = select(db.player_contacts.c.email).where(db.player_contacts.c.player_id == player)
        assert conn.execute(contact).scalar_one() == "ada@example.org"
        assert conn.execute(select(db.sign_in_links.c.token_hash)).scalar_one() == token_hash(token)
    with app.begin() as conn:
        assert use_link(conn, token, cohort_seed=SEED) is None  # used


def test_the_same_address_is_the_same_player(app: Engine) -> None:
    players: list[uuid.UUID | None] = []
    for _ in range(2):
        with app.begin() as conn:
            token = request_link(conn, "bo@example.org", daily_limit=90)
            players.append(use_link(conn, token, cohort_seed=SEED))
    assert players[0] is not None
    assert players[0] == players[1]
    with app.connect() as conn:
        assert conn.execute(select(func.count()).select_from(db.players)).scalar() == 1


def test_sign_up_numbers_count_up_and_the_cohort_follows_them(app: Engine) -> None:
    with app.begin() as conn:
        for n in range(25):
            player_for(conn, f"p{n}@example.org", cohort_seed=SEED)
        rows = conn.execute(select(db.players.c.signup_number, db.players.c.cohort)).all()
    assert sorted(number for number, _ in rows) == list(range(25))
    assert all(cohort == in_cohort(SEED, number) for number, cohort in rows)
    assert sum(cohort for number, cohort in rows if number < 20) == 3  # 3 in every 20


def test_an_expired_or_unknown_link_signs_nobody_in(app: Engine) -> None:
    with app.begin() as conn:
        token = request_link(conn, "cy@example.org", daily_limit=90, lifetime=timedelta(0))
    with app.begin() as conn:
        assert use_link(conn, token, cohort_seed=SEED) is None
        assert use_link(conn, "not-a-token", cohort_seed=SEED) is None


def test_two_first_sign_ins_at_once_make_one_player(app: Engine) -> None:
    with app.begin() as conn:
        tokens = [request_link(conn, "di@example.org", daily_limit=90) for _ in range(2)]
    results: list[uuid.UUID | None] = []
    barrier = threading.Barrier(2)

    def sign_in(token: str) -> None:
        with app.begin() as conn:
            barrier.wait()
            results.append(use_link(conn, token, cohort_seed=SEED))

    threads = [threading.Thread(target=sign_in, args=(t,)) for t in tokens]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(results)) == 1
    assert None not in results


def test_an_address_gets_three_links_in_15_minutes(app: Engine) -> None:
    with app.begin() as conn:
        for _ in range(LINKS_PER_ADDRESS):
            request_link(conn, "ed@example.org", daily_limit=90)
        with pytest.raises(TooManyLinksError, match="for this address") as caught:
            request_link(conn, "ed@example.org", daily_limit=90)
        assert caught.value.for_address
        request_link(conn, "fay@example.org", daily_limit=90)  # another address is fine


def test_the_server_sends_at_most_its_daily_limit(app: Engine) -> None:
    with app.begin() as conn:
        for n in range(4):
            request_link(conn, f"g{n}@example.org", daily_limit=4)
        with pytest.raises(TooManyLinksError, match="today") as caught:
            request_link(conn, "h@example.org", daily_limit=4)
        assert not caught.value.for_address


# ---------------------------------------------------------------- sessions


def a_player(app: Engine) -> uuid.UUID:
    with app.begin() as conn:
        return player_for(conn, "ivy@example.org", cohort_seed=SEED)


def test_a_session_signs_in_until_it_ends(app: Engine) -> None:
    player = a_player(app)
    with app.begin() as conn:
        token = start_session(conn, player)
        assert session_player(conn, token) == player
        assert session_player(conn, token + "x") is None
        end_session(conn, token)
        end_session(conn, token)  # twice changes nothing
        end_session(conn, "unknown")
        assert session_player(conn, token) is None


def test_a_session_expires(app: Engine) -> None:
    player = a_player(app)
    with app.begin() as conn:
        token = start_session(conn, player, lifetime=timedelta(0))
        assert session_player(conn, token) is None


def test_the_server_login_cannot_undo_a_use_or_an_end(app: Engine) -> None:
    """Using a link and ending a session are rows of their own; the login may not delete."""
    player = a_player(app)
    with app.begin() as conn:
        token = start_session(conn, player)
        end_session(conn, token)
    with pytest.raises(ProgrammingError, match="permission denied"), app.begin() as conn:
        conn.execute(db.session_ends.delete())


# ---------------------------------------------------------------- the network address limit


def test_one_network_address_is_limited_in_any_window() -> None:
    now = [0.0]
    limits = RateLimiter(2, 60, lambda: now[0])
    assert limits.allow("a")
    assert limits.allow("a")
    assert not limits.allow("a")
    assert limits.allow("b")
    now[0] = 60.0
    assert limits.allow("a")


def test_the_limiter_forgets_quiet_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fish_server.signin.MAX_KEYS", 2)
    now = [0.0]
    limits = RateLimiter(1, 10, lambda: now[0])
    for key in "abc":
        limits.allow(key)
    now[0] = 100.0
    limits.allow("d")
    assert set(limits._seen) == {"d"}  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------- the endpoints


@pytest.fixture
def client(app: Engine) -> Iterator[tuple[TestClient, MemoryMailer]]:
    mail = MemoryMailer()
    server.dependency_overrides[mailer] = lambda: mail
    limiter._seen.clear()  # pyright: ignore[reportPrivateUsage]
    yield TestClient(server), mail
    server.dependency_overrides.clear()


def link_in(mail: MemoryMailer) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", mail.sent[-1]["text"])
    assert match is not None
    return match.group(1)


def test_signing_in_from_start_to_finish(client: tuple[TestClient, MemoryMailer]) -> None:
    http, mail = client
    assert http.get("/auth/me").status_code == 401
    response = http.post("/auth/link", json={"email": "Jo@Example.org"})
    assert (response.status_code, response.json()) == (202, {"status": "sent"})
    assert mail.sent[-1]["to"] == "jo@example.org"
    assert "http://127.0.0.1:8000/sign-in?token=" in mail.sent[-1]["text"]
    assert "15 minutes" in mail.sent[-1]["html"]
    token = link_in(mail)
    page = http.get(f"/sign-in?token={token}")
    assert page.status_code == 200
    assert f"value='{token}'" in page.text  # opening the link only shows a button
    assert http.get("/auth/me").status_code == 401
    response = http.post("/auth/verify", data={"token": token}, follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie  # not https locally
    assert http.get("/auth/me").json()["signed_in"] is True
    again = http.post("/auth/verify", data={"token": token}, follow_redirects=False)
    assert again.status_code == 400  # used
    assert http.post("/auth/sign-out").status_code == 204
    assert http.get("/auth/me").status_code == 401
    assert http.post("/auth/sign-out").status_code == 204  # signed out already: still fine


def test_the_cookie_is_secure_over_https(
    client: tuple[TestClient, MemoryMailer], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PUBLIC_URL_VAR, "https://fish.example.org")
    http, mail = client
    http.post("/auth/link", json={"email": "kai@example.org"})
    assert "https://fish.example.org/sign-in?token=" in mail.sent[-1]["text"]
    response = http.post("/auth/verify", data={"token": link_in(mail)}, follow_redirects=False)
    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.parametrize("body", [{"email": "nope"}, {"email": 3}, {"mail": "a@b.org"}])
def test_the_form_needs_an_address(client: tuple[TestClient, MemoryMailer], body: object) -> None:
    http, mail = client
    assert http.post("/auth/link", json=body).status_code == 422
    assert mail.sent == []


def test_a_link_that_is_not_one_shows_why(client: tuple[TestClient, MemoryMailer]) -> None:
    http, _ = client
    assert http.post("/auth/verify", data={"token": "nope"}).status_code == 400
    assert http.post("/auth/verify", data={}).status_code == 400


def test_limits_answer_429_or_503(
    client: tuple[TestClient, MemoryMailer], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, _ = client
    for _ in range(LINKS_PER_ADDRESS):
        http.post("/auth/link", json={"email": "lu@example.org"})
    assert http.post("/auth/link", json={"email": "lu@example.org"}).status_code == 429
    monkeypatch.setenv(DAILY_LINKS_VAR, "3")
    assert http.post("/auth/link", json={"email": "mo@example.org"}).status_code == 503
    for _ in range(10):
        http.post("/auth/link", json={"email": "no@example.org"})
    assert http.post("/auth/link", json={"email": "pa@example.org"}).status_code == 429  # address


def test_a_failed_email_leaves_no_link(
    client: tuple[TestClient, MemoryMailer], app: Engine
) -> None:
    http, _ = client

    class Broken:
        def send(self, to: str, subject: str, text: str, html: str) -> None:
            raise MailError("down")

    server.dependency_overrides[mailer] = Broken
    assert http.post("/auth/link", json={"email": "qi@example.org"}).status_code == 503
    with app.connect() as conn:
        assert conn.execute(select(func.count()).select_from(db.sign_in_links)).scalar() == 0


# ---------------------------------------------------------------- mailers and settings


def test_resend_is_sent_the_email_with_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[urllib.request.Request] = []

    def opener(request: urllib.request.Request, timeout: float) -> object:
        sent.append(request)
        return 200

    ResendMailer("re_key", "Fish <s@x.org>", opener).send("a@b.org", "Hi", "text", "<p>h</p>")
    (request,) = sent
    assert request.full_url == RESEND_URL
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer re_key"
    assert request.data is not None
    assert b'"to": ["a@b.org"]' in request.data  # pyright: ignore[reportOperatorIssue]


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(RESEND_URL, 401, "no", {}, None),  # pyright: ignore[reportArgumentType]
        urllib.error.URLError("unreachable"),
        TimeoutError(),
    ],
)
def test_resend_failures_are_mail_errors_without_the_key(error: Exception) -> None:
    def opener(request: urllib.request.Request, timeout: float) -> object:
        raise error

    with pytest.raises(MailError) as caught:
        ResendMailer("re_secret", "Fish <s@x.org>", opener).send("a@b.org", "s", "t", "h")
    assert "re_secret" not in str(caught.value)


def test_the_console_mailer_prints(capsys: pytest.CaptureFixture[str]) -> None:
    ConsoleMailer().send("a@b.org", "Subject", "the link", "<p>")
    assert "the link" in capsys.readouterr().err


def test_the_settings_choose_the_mailer(monkeypatch: pytest.MonkeyPatch) -> None:
    mailer.cache_clear()
    monkeypatch.delenv(EMAIL_VAR, raising=False)
    assert isinstance(mailer(), ConsoleMailer)
    mailer.cache_clear()
    monkeypatch.setenv(EMAIL_VAR, "resend")
    monkeypatch.setenv(RESEND_KEY_VAR, "re_x")
    monkeypatch.setenv(EMAIL_FROM_VAR, "Fish <a@b.org>")
    chosen = mailer()
    assert isinstance(chosen, ResendMailer)
    assert (chosen.api_key, chosen.sender) == ("re_x", "Fish <a@b.org>")
    mailer.cache_clear()
    monkeypatch.setenv(EMAIL_VAR, "carrier-pigeon")
    with pytest.raises(ValueError, match="console or resend"):
        email_mode()


def test_sign_in_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (PUBLIC_URL_VAR, RENDER_URL_VAR, EMAIL_FROM_VAR, DAILY_LINKS_VAR):
        monkeypatch.delenv(var, raising=False)
    assert public_url() == "http://127.0.0.1:8000"
    monkeypatch.setenv(RENDER_URL_VAR, "https://fish-staging.onrender.com/")
    assert public_url() == "https://fish-staging.onrender.com"
    monkeypatch.setenv(PUBLIC_URL_VAR, "https://play.example.org")
    assert public_url() == "https://play.example.org"
    monkeypatch.setenv(PUBLIC_URL_VAR, "play.example.org")
    with pytest.raises(ValueError, match="https://"):
        public_url()
    assert email_from().startswith("Fish <signin@mail.")
    assert daily_link_limit() == 90
    monkeypatch.setenv(DAILY_LINKS_VAR, "ten")
    with pytest.raises(ValueError, match="whole number"):
        daily_link_limit()


@pytest.mark.parametrize("raw", ["-1", "1.5", "x", str(2**64)])
def test_the_cohort_seed_is_a_64_bit_number(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(COHORT_SEED_VAR, str(2**64 - 1))
    assert cohort_seed() == 2**64 - 1
    monkeypatch.setenv(COHORT_SEED_VAR, raw)
    with pytest.raises(ValueError, match="whole number"):
        cohort_seed()


def test_sign_in_tables_never_leave_the_server() -> None:
    assert set(db.PRIVATE) >= {"sign_in_links", "sign_in_uses", "sessions", "session_ends"}
    assert not set(db.PRIVATE) & set(db.APPEND_ONLY)

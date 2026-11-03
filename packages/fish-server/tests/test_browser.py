"""The website in a real browser (T3.3; Consent Screen §2): the built client, served by the real
server on a real port with a real database, driven in Chromium at phone width.

The key points fit on the first screen at phone width, in both texts and both colour
schemes, with nothing wider than the screen. Then one person goes all the way: the consent
screen with nothing stored before Continue, the email field, the emailed link and its
button, signed in with the acceptance recorded, a room made and left in the lobby, the text
they accepted reread, the account page, a confirmed withdrawal recorded once, and signing
out. And six people sign up, sit together through a room (its link or its code), and play a
whole game (T3.4): an ask, Calls pressed and assigned, choices and votes, the result, and
the note-taking question answered and written.

Marked ``browser``: the ordinary test run leaves these out, because they need the client
built first. ``scripts/check.sh`` and CI run them after the build with ``pytest -m browser``.
Chromium comes from ``uv run playwright install chromium`` (once). Skipped without
FISH_TEST_DATABASE_URL."""

import re
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final, Literal

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, ViewportSize, expect, sync_playwright
from sqlalchemy import Engine, Table, create_engine, func, pool, select

from fish_server import db
from fish_server.app import app as server
from fish_server.auth import limiter
from fish_server.mailer import MemoryMailer, mailer
from fish_server.settings import (
    CLIENT_DIR_VAR,
    COHORT_SEED_VAR,
    CONSENT_VERSION_VAR,
    database_url,
)

pytestmark = pytest.mark.browser

CLIENT: Final = Path(__file__).resolve().parents[3] / "client" / "dist"
PHONE: Final[ViewportSize] = {"width": 390, "height": 664}
"""An iPhone's width, and the height its browser leaves for the page with its bars showing."""

type Site = tuple[str, MemoryMailer, Engine]


@pytest.fixture
def site(
    request: pytest.FixtureRequest, server_env: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Site]:
    """The server with the built client, running on a free local port: its address, the
    emails it sends, and its database. The text shown is ``v1.0`` unless parametrized."""
    if not (CLIENT / "index.html").is_file():
        pytest.fail("Build the client first: npm --prefix client run build")
    monkeypatch.setenv(CLIENT_DIR_VAR, str(CLIENT))
    monkeypatch.setenv(COHORT_SEED_VAR, "7")
    monkeypatch.setenv(CONSENT_VERSION_VAR, getattr(request, "param", "v1.0"))
    mail = MemoryMailer()
    server.dependency_overrides[mailer] = lambda: mail
    limiter._seen.clear()  # pyright: ignore[reportPrivateUsage]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    running = uvicorn.Server(uvicorn.Config(server, port=port, log_level="warning"))
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not running.started:
        assert time.monotonic() < deadline, "the server did not start"
        time.sleep(0.05)
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield f"http://127.0.0.1:{port}", mail, engine
    engine.dispose()
    running.should_exit = True
    thread.join(20)
    server.dependency_overrides.clear()


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            chromium = playwright.chromium.launch()
        except Exception as missing:
            pytest.fail(f"Install Chromium first: uv run playwright install chromium ({missing})")
        yield chromium
        chromium.close()


def rows(engine: Engine, *tables: Table) -> list[int]:
    with engine.connect() as conn:
        return [conn.execute(select(func.count()).select_from(t)).scalar_one() for t in tables]


@pytest.mark.parametrize("site", ["v1.0", "v1.0-pilot"], indirect=True)
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_key_points_fit_on_the_first_screen_of_a_phone(
    site: Site, browser: Browser, scheme: Literal["light", "dark"]
) -> None:
    """Consent Screen §2.2: the key points fit on the first screen at phone width."""
    base, _, _ = site
    page = browser.new_page(viewport=PHONE, color_scheme=scheme)
    page.goto(base + "/")
    key_points = page.locator(".study > section").first
    expect(key_points.get_by_role("heading", name="Key points")).to_be_visible()
    box = key_points.bounding_box()
    assert box is not None
    assert box["y"] + box["height"] <= PHONE["height"]
    assert page.evaluate("document.documentElement.scrollWidth") <= PHONE["width"]
    page.close()


def test_a_person_joins_rereads_withdraws_and_signs_out(site: Site, browser: Browser) -> None:
    base, mail, engine = site
    page: Page = browser.new_page(viewport=PHONE)
    page.goto(base + "/")

    # The consent screen first, Continue disabled until all three are ticked (§2.1, §2.3).
    expect(page.get_by_role("heading", level=1)).to_have_text(
        "Fish research study: before you play"
    )
    boxes = page.get_by_role("checkbox")
    expect(boxes).to_have_count(3)
    proceed = page.get_by_role("button", name="Continue")
    for box in boxes.all():
        expect(proceed).to_be_disabled()
        box.check()
    expect(proceed).to_be_enabled()
    assert rows(engine, db.players, db.sign_in_links, db.consents) == [0, 0, 0]  # nothing yet

    # Continue, the email field, the emailed link and its one button (§2.5).
    proceed.click()
    page.get_by_label("Email address").fill("browser@example.org")
    page.get_by_role("button", name="Send sign-in link").click()
    expect(page.get_by_role("heading", name="Check your email")).to_be_visible()
    assert rows(engine, db.players, db.consents) == [0, 0]  # the acceptance rides the link
    token = re.search(r"token=([A-Za-z0-9_\-]+)", mail.sent[-1]["text"])
    assert token is not None
    page.goto(f"{base}/sign-in?token={token.group(1)}")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Play Fish")).to_be_visible()
    with engine.connect() as conn:
        (accepted,) = conn.execute(select(db.consents)).mappings()
    confirmed = ("us_resident_adult", "agrees", "no_outside_communication")
    assert (accepted["version"], *(accepted[name] for name in confirmed)) == ("v1.0", *[True] * 3)

    # The lobby, over the game socket (T3.4): a room made, its code shown, and left.
    page.get_by_role("button", name="Make a room for friends").click()
    expect(page.get_by_role("status")).to_have_text(
        "1 of 6 players are here. The game starts when six are here."
    )
    expect(page.get_by_label("Room code")).to_have_text(re.compile(r"^[A-HJ-NP-Z2-9]{6}$"))
    page.get_by_role("button", name="Leave").click()
    expect(page.get_by_role("button", name="Find a table")).to_be_enabled()

    # The text they accepted, from the footer (§2.6).
    page.get_by_role("contentinfo").get_by_role("link", name="Study information").click()
    expect(page.get_by_text("Version v1.0, the version you accepted.")).to_be_visible()
    expect(page.get_by_role("heading", name="Before you continue, please confirm:")).to_be_visible()

    # The account page: withdrawing asks first, then is recorded once (§2.7).
    page.get_by_role("contentinfo").get_by_role("link", name="Your account").click()
    expect(page.get_by_text("You accepted version v1.0.")).to_be_visible()
    page.get_by_role("button", name="Withdraw from the study").click()
    page.get_by_role("button", name="Cancel").click()
    assert rows(engine, db.withdrawals) == [0]
    page.get_by_role("button", name="Withdraw from the study").click()
    page.get_by_role("button", name="Yes, withdraw").click()
    expect(
        page.get_by_text("You have withdrawn from the study. You cannot play again.")
    ).to_be_visible()
    with engine.connect() as conn:
        assert conn.execute(select(db.withdrawals.c.channel)).scalars().all() == ["website"]
    page.goto(base + "/")  # a fresh visit
    expect(page.get_by_role("heading", name="You have withdrawn from the study")).to_be_visible()

    # Signing out: back to the consent screen, with no account link.
    page.goto(base + "/account")
    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("checkbox")).to_have_count(3)
    expect(page.get_by_role("contentinfo").get_by_role("link", name="Your account")).to_have_count(
        0
    )
    assert page.context.cookies() == []
    page.close()


# ---------------------------------------------------------------- a whole game (T3.4)

GAME_S: Final = 180
"""The longest a game may take here: a few seconds a call, and 15 for a vote nobody finishes."""


def sign_up(browser: Browser, base: str, mail: MemoryMailer, email: str) -> Page:
    """A new person, in a browser of their own, through the consent screen and the emailed
    link, at the lobby."""
    page = browser.new_context(viewport=PHONE).new_page()
    page.goto(base + "/")
    expect(page.get_by_role("checkbox")).to_have_count(3)
    for box in page.get_by_role("checkbox").all():
        box.check()
    page.get_by_role("button", name="Continue").click()
    page.get_by_label("Email address").fill(email)
    page.get_by_role("button", name="Send sign-in link").click()
    expect(page.get_by_role("heading", name="Check your email")).to_be_visible()
    token = re.search(r"token=([A-Za-z0-9_\-]+)", mail.sent[-1]["text"])
    assert token is not None
    page.goto(f"{base}/sign-in?token={token.group(1)}")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("button", name="Find a table")).to_be_enabled()
    return page


def shown(page: Page, role: Literal["region", "heading", "button"], name: str) -> bool:
    """Whether ``page`` shows it now, without waiting."""
    return page.get_by_role(role, name=name, exact=True).count() > 0


def play_a_move(pages: list[Page], pressed: list[int]) -> None:
    """One step of play, by whoever the screens show can act: a choice or a vote, a call's
    assignment (every card put with the caller, so most calls are wrong and end the game
    fast), run-out's next set, or else Call pressed on the first set offered."""
    for page in pages:
        for name in ("Choose", "Vote"):
            choosing = page.get_by_role("region", name=name, exact=True)
            if choosing.count() > 0 and "You voted for" not in choosing.inner_text():
                choosing.get_by_role("button").first.click()
                return
        if shown(page, "region", "Assign your call"):
            call = page.get_by_role("region", name="Assign your call")
            for row in call.get_by_role("group").all():
                row.get_by_role("button", name="You").click()
            call.get_by_role("button", name="Make the call").click()
            return
        if shown(page, "region", "Name the set to call"):
            sets = page.get_by_role("region", name="Name the set to call")
            sets.get_by_role("button").first.click()
            sets.get_by_role("button", name=re.compile("^Call ")).click()
            return
    for i, page in enumerate(pages):
        if (
            shown(page, "button", "Call a set")
            and page.get_by_role("button", name="Call a set").is_enabled()
        ):
            page.get_by_role("button", name="Call a set").click()
            sets = page.get_by_role("region", name="Call a set")
            sets.get_by_role("button").first.click()
            sets.get_by_role("button", name=re.compile("^Call ")).click()
            pressed.append(i)
            return


def test_six_people_play_a_whole_game(site: Site, browser: Browser) -> None:
    """Six people sign up, sit together through a room, and play a game to its end at phone
    width: an ask, Call pressed and every call assigned, choices and votes, until a team has
    five sets; then each sees the result and answers the note-taking question."""
    base, mail, engine = site
    pages = [sign_up(browser, base, mail, f"player{i}@example.org") for i in range(6)]

    # A room: two open its shared link, three type its code; the game starts with the sixth.
    pages[0].get_by_role("button", name="Make a room for friends").click()
    code = pages[0].get_by_label("Room code").inner_text()
    link = pages[0].get_by_label("Room link").inner_text()
    assert link == f"{base}/?room={code}"
    for i, page in enumerate(pages[1:]):
        if i < 2:
            page.goto(link)
            expect(page.get_by_placeholder("Room code")).to_have_value(code)
        else:
            page.get_by_placeholder("Room code").fill(code.lower())
        page.get_by_role("button", name="Join").click()
    for page in pages:
        expect(page.get_by_role("region", name="Your hand")).to_be_visible()
        expect(page.locator(".seat")).to_have_count(6)
        expect(page.get_by_text("bot", exact=True)).to_have_count(0)  # six people
        expect(page.locator(".seat.you")).to_have_count(1)
        assert page.evaluate("document.documentElement.scrollWidth") <= PHONE["width"]

    # The player whose turn it is asks; everyone sees the ask and its answer.
    asker = next(p for p in pages if p.get_by_role("status").inner_text().startswith("Your turn"))
    asking = asker.get_by_role("region", name="Ask for a card")
    asking.get_by_role("button").first.click()
    asking.get_by_role("group").first.get_by_role("button").first.click()
    asking.get_by_role("button", name=re.compile("^Ask ")).click()
    for page in pages:
        expect(page.get_by_text(re.compile(r" asked .* for the "))).to_be_visible()

    # Calls until the game ends: each pressed, assigned, scored, and the turn chosen.
    pressed: list[int] = []
    deadline = time.monotonic() + GAME_S
    while not shown(pages[0], "region", "Your last game"):
        assert time.monotonic() < deadline, "the game did not end"
        play_a_move(pages, pressed)
        pages[0].wait_for_timeout(150)
    assert pressed, "no Call was pressed"

    # The result, the question, and the lobby, for all six.
    for page in pages:
        ending = page.get_by_role("region", name="Your last game")
        expect(ending).to_contain_text(re.compile(r"team won, 5 sets to [0-4]\."))
        expect(
            page.get_by_role("heading", name="Did you take notes during this game?")
        ).to_be_visible()
        page.get_by_role("button", name="No", exact=True).click()
        expect(page.get_by_role("button", name="Find a table")).to_be_enabled()
    deadline = time.monotonic() + 10
    while rows(engine, db.note_answers) != [6]:
        assert time.monotonic() < deadline, "the answers were not written"
        time.sleep(0.1)
    with engine.connect() as conn:
        assert conn.execute(select(db.game_endings.c.completion)).scalars().all() == ["finished"]
        assert set(conn.execute(select(db.note_answers.c.answer)).scalars()) == {"no"}
    for page in pages:
        page.context.close()

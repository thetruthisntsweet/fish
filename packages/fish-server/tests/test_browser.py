"""The website in a real browser (T3.3; Consent Screen §2): the built client, served by the real
server on a real port with a real database, driven in Chromium at phone width.

The key points fit on the first screen at phone width, in both texts and both colour
schemes, with nothing wider than the screen. Then one person goes all the way: the consent
screen with nothing stored before Continue, the email field, the emailed link and its
button, signed in with the acceptance recorded, the text they accepted reread, the account
page, a confirmed withdrawal recorded once, and signing out.

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
    expect(page.get_by_role("heading", name="You are signed in")).to_be_visible()
    with engine.connect() as conn:
        (accepted,) = conn.execute(select(db.consents)).mappings()
    confirmed = ("us_resident_adult", "agrees", "no_outside_communication")
    assert (accepted["version"], *(accepted[name] for name in confirmed)) == ("v1.0", *[True] * 3)

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

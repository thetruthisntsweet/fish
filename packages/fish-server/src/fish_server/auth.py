"""The sign-in and study endpoints (T3.1; consent and withdrawal, T3.2). How sign-in works is
in ``fish_server.signin``; acceptances and withdrawals in ``fish_server.consent``.

- ``GET /study``: the version of the study information this site shows.
- ``POST /auth/link`` with ``{"email": ..., "consent": {...}}``: email a sign-in link,
  carrying the acceptance made on the consent screen (``fish_server.consent``); 422 if the
  acceptance is not of the current text with all three confirmations. 202 whether or not the
  address has played before, so the form does not tell anyone who has; 422 for something
  that is not an address; 429 once a limit is reached; 503 if the email could not be sent.
- ``GET /sign-in?token=...``: the page the link opens, with one button. Opening it uses
  nothing.
- ``POST /auth/verify`` with the form's ``token``: use the link, start a session, set the
  ``fish_session`` cookie and go to ``/``. 400 if the link has expired or was used.
- ``GET /auth/me``: 200 ``{"signed_in": true, "study": {...}}`` with a session (the version
  last accepted, whether withdrawn, whether they may play), 401 without.
- ``POST /consent``: accept the current text; ``POST /withdraw`` with ``{"confirm": true}``:
  withdraw from the study.
- ``POST /auth/sign-out``: end the session and clear the cookie.

The pages are plain HTML until the web client (T3.4) takes them over.
"""

import html
import time
import uuid
from typing import Annotated, Final, Literal
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from fish_server.consent import Acceptance, accept, problem, standing, withdraw
from fish_server.database import get_engine
from fish_server.mailer import Mailer, MailError, mailer
from fish_server.settings import cohort_seed, consent_version, daily_link_limit, public_url
from fish_server.signin import (
    LINK_LIFETIME,
    SESSION_LIFETIME,
    RateLimiter,
    TooManyLinksError,
    end_session,
    normalize_email,
    request_link,
    session_player,
    start_session,
    use_link,
)

COOKIE: Final = "fish_session"
PER_NETWORK_ADDRESS: Final = 10
"""Sign-in emails one network address may ask for in an hour."""

router = APIRouter()
limiter = RateLimiter(PER_NETWORK_ADDRESS, 3600, time.monotonic)


class LinkRequest(BaseModel):
    """The sign-in form: an email address, and the acceptance made on the consent screen just
    before it (null for someone signing in again, who accepted before)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    email: str
    consent: Acceptance | None = None


class WithdrawRequest(BaseModel):
    """Withdrawing, confirmed (Consent Screen §2.7)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    confirm: Literal[True]


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title></head><body><main>{body}</main></body></html>",
        status_code=status,
    )


def _email(link: str) -> tuple[str, str, str]:
    minutes = int(LINK_LIFETIME.total_seconds() // 60)
    subject = "Your Fish sign-in link"
    text = (
        f"Sign in to Fish:\n\n{link}\n\nThe link works once, within {minutes} minutes. "
        "If you did not ask for it, you can ignore this email."
    )
    safe = html.escape(link, quote=True)
    body = (
        f"<p><a href='{safe}'>Sign in to Fish</a></p><p>The link works once, within "
        f"{minutes} minutes. If you did not ask for it, you can ignore this email.</p>"
    )
    return subject, text, body


@router.post("/auth/link", status_code=202)
def send_link(
    form: LinkRequest, request: Request, mail: Annotated[Mailer, Depends(mailer)]
) -> Response:
    try:
        email = normalize_email(form.email)
    except ValueError:
        return JSONResponse({"detail": "That is not an email address."}, status_code=422)
    accepted = None
    if form.consent is not None:
        refused = problem(form.consent, consent_version())
        if refused is not None:
            return JSONResponse({"detail": refused}, status_code=422)
        accepted = form.consent.version
    if not limiter.allow(request.client.host if request.client else "unknown"):
        return JSONResponse({"detail": "Too many sign-in emails. Try later."}, status_code=429)
    try:
        with get_engine().begin() as conn:
            token = request_link(
                conn, email, daily_limit=daily_link_limit(), consent_version=accepted
            )
            link = f"{public_url()}/sign-in?token={quote(token)}"
            mail.send(email, *_email(link))  # a failed send rolls the link back
    except TooManyLinksError as limit:
        status = 429 if limit.for_address else 503
        return JSONResponse({"detail": f"{str(limit).capitalize()}. Try later."}, status)
    except MailError:
        return JSONResponse({"detail": "The email could not be sent. Try later."}, 503)
    return JSONResponse({"status": "sent"}, status_code=202)


@router.get("/sign-in")
def sign_in_page(token: str = "") -> HTMLResponse:
    """The page a link opens: one button, so that opening the link uses nothing."""
    safe = html.escape(token, quote=True)
    return _page(
        "Sign in to Fish",
        "<h1>Sign in to Fish</h1><form method='post' action='/auth/verify'>"
        f"<input type='hidden' name='token' value='{safe}'>"
        "<button type='submit'>Sign in</button></form>",
    )


def _verify(token: str) -> str | None:
    seed = cohort_seed()
    with get_engine().begin() as conn:
        player = use_link(conn, token, cohort_seed=seed)
        return None if player is None else start_session(conn, player)


@router.post("/auth/verify")
async def verify(request: Request) -> Response:
    fields = parse_qs((await request.body()).decode(errors="replace"))
    token = (fields.get("token") or [""])[0]
    session = await run_in_threadpool(_verify, token) if token else None
    if session is None:
        return _page(
            "Sign-in link not valid",
            "<h1>This link has expired or was already used</h1>"
            "<p>Ask for a new one on the sign-in page.</p>",
            status=400,
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE,
        session,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=public_url().startswith("https://"),
        samesite="lax",
    )
    return response


def signed_in(token: str | None) -> uuid.UUID | None:
    """The player a ``fish_session`` cookie signs in, if any."""
    if not token:
        return None
    with get_engine().connect() as conn:
        return session_player(conn, token)


@router.get("/study")
def study() -> JSONResponse:
    """The version of the study information this site shows (Consent Screen §1, §4)."""
    return JSONResponse({"version": consent_version()})


def _standing(player: uuid.UUID) -> dict[str, object]:
    with get_engine().connect() as conn:
        where = standing(conn, player, consent_version())
    return {
        "current": where.current,
        "accepted": where.accepted,
        "withdrawn": where.withdrawn,
        "may_play": where.may_play,
    }


@router.get("/auth/me")
def me(fish_session: Annotated[str | None, Cookie()] = None) -> JSONResponse:
    """Whether the cookie signs in, and if so where the player stands with the study: the
    version they last accepted, whether they have withdrawn, and whether they may play."""
    player = signed_in(fish_session)
    if player is None:
        return JSONResponse({"signed_in": False}, 401)
    return JSONResponse({"signed_in": True, "study": _standing(player)})


@router.post("/consent", status_code=204)
def give_consent(
    form: Acceptance, fish_session: Annotated[str | None, Cookie()] = None
) -> Response:
    """A signed-in player accepts the study information shown now (a new version, or after
    signing in without an acceptance). 409 once they have withdrawn."""
    player = signed_in(fish_session)
    if player is None:
        return JSONResponse({"detail": "Sign in first."}, 401)
    current = consent_version()
    refused = problem(form, current)
    if refused is not None:
        return JSONResponse({"detail": refused}, 422)
    with get_engine().begin() as conn:
        if standing(conn, player, current).withdrawn:
            return JSONResponse({"detail": "You have withdrawn from the study."}, 409)
        accept(conn, player, current)
    return Response(status_code=204)


@router.post("/withdraw", status_code=204)
def withdraw_here(
    form: WithdrawRequest, fish_session: Annotated[str | None, Cookie()] = None
) -> Response:
    """The account page's "Withdraw from the study" button, confirmed (Consent Screen §2.7).
    Withdrawing twice records it once."""
    player = signed_in(fish_session)
    if player is None:
        return JSONResponse({"detail": "Sign in first."}, 401)
    with get_engine().begin() as conn:
        if not standing(conn, player, consent_version()).withdrawn:
            withdraw(conn, player, "website")
    return Response(status_code=204)


@router.post("/auth/sign-out", status_code=204)
def sign_out(fish_session: Annotated[str | None, Cookie()] = None) -> Response:
    if fish_session:
        with get_engine().begin() as conn:
            end_session(conn, fish_session)
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, httponly=True, samesite="lax")
    return response

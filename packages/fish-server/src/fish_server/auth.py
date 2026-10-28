"""The sign-in endpoints (T3.1). How sign-in works is in ``fish_server.signin``.

- ``POST /auth/link`` with ``{"email": ...}``: email a sign-in link. 202 whether or not the
  address has played before, so the form does not tell anyone who has; 422 for something
  that is not an address; 429 once a limit is reached; 503 if the email could not be sent.
- ``GET /sign-in?token=...``: the page the link opens, with one button. Opening it uses
  nothing.
- ``POST /auth/verify`` with the form's ``token``: use the link, start a session, set the
  ``fish_session`` cookie and go to ``/``. 400 if the link has expired or was used.
- ``GET /auth/me``: 200 ``{"signed_in": true}`` with a session, 401 without.
- ``POST /auth/sign-out``: end the session and clear the cookie.

The pages are plain HTML until the web client (T3.4) takes them over.
"""

import html
import time
import uuid
from typing import Annotated, Final
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from fish_server.database import get_engine
from fish_server.mailer import Mailer, MailError, mailer
from fish_server.settings import cohort_seed, daily_link_limit, public_url
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
    """The sign-in form: an email address."""

    model_config = ConfigDict(extra="forbid", strict=True)
    email: str


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
    if not limiter.allow(request.client.host if request.client else "unknown"):
        return JSONResponse({"detail": "Too many sign-in emails. Try later."}, status_code=429)
    try:
        with get_engine().begin() as conn:
            token = request_link(conn, email, daily_limit=daily_link_limit())
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


@router.get("/auth/me")
def me(fish_session: Annotated[str | None, Cookie()] = None) -> JSONResponse:
    player = signed_in(fish_session)
    return JSONResponse({"signed_in": player is not None}, 200 if player else 401)


@router.post("/auth/sign-out", status_code=204)
def sign_out(fish_session: Annotated[str | None, Cookie()] = None) -> Response:
    if fish_session:
        with get_engine().begin() as conn:
            end_session(conn, fish_session)
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, httponly=True, samesite="lax")
    return response

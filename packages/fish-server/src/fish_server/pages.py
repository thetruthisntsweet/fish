"""The web client, served by the game server itself (T3.3).

``npm --prefix client run build`` writes the client to ``client/dist`` (the image builds it
too, and ``FISH_CLIENT_DIR`` can point elsewhere). The server answers the client's pages with
its ``index.html`` and serves its files, so the pages, the endpoints and ``/ws`` share one
address and the session cookie works with nothing more to set up.

- ``/``, ``/account``, ``/information``: ``index.html``, never cached, so a deploy reaches
  everyone at their next visit. The client shows the right screen for the path.
- ``/assets/<name>``: the client's scripts and styles. Their names carry a hash of their
  contents, so they are cached for good.
- ``/favicon.svg``.

Any other path is not a page: 404, so a mistyped endpoint is never answered with a page.
"""

import re
from typing import Final

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, Response

from fish_server.settings import client_dir

PAGES: Final = ("/", "/account", "/information")
"""Every path the client shows a screen for."""

ASSET_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
"""A file directly in ``assets``: no folders, nothing hidden."""

NEVER_CACHED: Final = {"Cache-Control": "no-cache"}
CACHED_FOR_GOOD: Final = {"Cache-Control": "public, max-age=31536000, immutable"}
CACHED_A_DAY: Final = {"Cache-Control": "public, max-age=86400"}

NOT_BUILT: Final = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Fish</title></head>"
    "<body><main><h1>The web client is not built</h1><p>Run <code>npm --prefix client run "
    "build</code>, then reload.</p></main></body></html>"
)

router = APIRouter(include_in_schema=False)


def page() -> Response:
    """The client's ``index.html``; 503 if the client has not been built."""
    index = client_dir() / "index.html"
    if not index.is_file():
        return HTMLResponse(NOT_BUILT, status_code=503)
    return FileResponse(index, media_type="text/html; charset=utf-8", headers=NEVER_CACHED)


for path in PAGES:
    router.add_api_route(path, page, methods=["GET"])


@router.get("/assets/{name}")
def asset(name: str) -> Response:
    """One of the client's built files, by name."""
    path = client_dir() / "assets" / name
    if not ASSET_NAME.fullmatch(name) or not path.is_file():
        return Response(status_code=404)
    return FileResponse(path, headers=CACHED_FOR_GOOD)


@router.get("/favicon.svg")
def favicon() -> Response:
    path = client_dir() / "favicon.svg"
    if not path.is_file():
        return Response(status_code=404)
    return FileResponse(path, media_type="image/svg+xml", headers=CACHED_A_DAY)

"""Tests for fish_server.pages (T3.3): the server serves the built web client."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fish_server.app import app
from fish_server.pages import PAGES
from fish_server.settings import CLIENT_DIR_VAR, client_dir

INDEX = "<!doctype html><title>Fish</title><div id='root'></div>"
SCRIPT = "index-AbC123_x.js"
STYLE = "index-AbC123_x.css"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)  # no lifespan: nothing here touches the games or the database


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A built client, as ``npm run build`` lays it out."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "assets" / SCRIPT).write_text("console.log(1);", encoding="utf-8")
    (tmp_path / "assets" / STYLE).write_text("main{}", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (tmp_path / "secret.txt").write_text("not a client file")
    monkeypatch.setenv(CLIENT_DIR_VAR, str(tmp_path))
    return tmp_path


def test_the_client_is_found_under_the_directory_the_server_runs_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CLIENT_DIR_VAR, raising=False)
    assert client_dir() == Path("client/dist")  # the repository locally, /app in the image
    monkeypatch.setenv(CLIENT_DIR_VAR, " /srv/client ")
    assert client_dir() == Path("/srv/client")


@pytest.mark.usefixtures("built")
@pytest.mark.parametrize("path", PAGES)
def test_every_page_is_the_client_never_cached(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.usefixtures("built")
@pytest.mark.parametrize(("name", "kind"), [(SCRIPT, "text/javascript"), (STYLE, "text/css")])
def test_the_clients_files_are_cached_for_good(client: TestClient, name: str, kind: str) -> None:
    response = client.get(f"/assets/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(kind)
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.usefixtures("built")
def test_the_icon_is_served(client: TestClient) -> None:
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"


@pytest.mark.usefixtures("built")
@pytest.mark.parametrize(
    "path",
    [
        "/assets/missing.js",
        "/assets/.hidden",
        "/assets/..%2Fsecret.txt",
        "/assets/%2E%2E%2Fsecret.txt",
        "/assets/sub/index.js",
        "/secret.txt",
        "/index.html",
        "/accounts",  # not a page: a typo is never answered with the client
        "/sign-up",
    ],
)
def test_nothing_else_is_served(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_a_server_without_a_built_client_says_how_to_build_it(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CLIENT_DIR_VAR, str(tmp_path / "nothing"))
    response = client.get("/")
    assert response.status_code == 503
    assert "npm --prefix client run build" in response.text
    assert client.get(f"/assets/{SCRIPT}").status_code == 404
    assert client.get("/favicon.svg").status_code == 404


@pytest.mark.usefixtures("built")
def test_the_endpoints_are_still_the_servers(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/sign-in", params={"token": "x"}).text.count("<form") == 1


def test_the_client_has_a_screen_for_exactly_the_pages_served() -> None:
    """client/src/navigation.ts lists the paths the client shows a screen for."""
    source = Path(__file__).resolve().parents[3] / "client" / "src" / "navigation.ts"
    found = re.search(r"export const PAGES = \[([^\]]*)\]", source.read_text(encoding="utf-8"))
    assert found is not None
    assert tuple(re.findall(r'"([^"]+)"', found.group(1))) == PAGES

"""What the server writes to its logs (T3.8): requests by method, path, status and time, never
an IP address, an email address or a sign-in link (Terms and Privacy §2, §4). The last test
runs the server exactly as the Dockerfile does and reads everything it writes."""

import logging
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fish_server.app import app
from fish_server.logs import Scrubbed, install, scrub

DOCKERFILE = Path(__file__).parents[3] / "Dockerfile"


@pytest.mark.parametrize(
    ("line", "shown"),
    [
        ("sign-in for player@example.com failed", "sign-in for [email] failed"),
        ("Key (email)=(a.b+c@mail.example.org) already exists", "Key (email)=([email]) already"),
        ("from 203.0.113.9:51234", "from [address]:51234"),
        ('connection to server at "127.0.0.1", port 5432 failed', 'at "[address]", port 5432'),
        ("client 2001:db8::1 connected", "client [address] connected"),
        ("client ::1 and fe80::1%eth0", "client [address] and [address]"),
        ("GET /sign-in?token=abc-DEF_123 200", "GET /sign-in?token=[hidden] 200"),
        ("cookie session=0123abcd; Path=/", "cookie session=[hidden]; Path=/"),
    ],
)
def test_scrub_replaces_addresses_and_tokens(line: str, shown: str) -> None:
    assert shown in scrub(line)


@pytest.mark.parametrize(
    "line",
    [
        "game 3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90: stopped without an ending; now abandoned",
        "INFO: started at 20:06:31, ruleset 1.2, server 0.1.0",
        "GET /assets/index-B3x9.js 200 2 ms",
    ],
)
def test_scrub_leaves_the_rest_alone(line: str) -> None:
    assert scrub(line) == line


def test_a_traceback_is_scrubbed_too() -> None:
    formatter = Scrubbed()
    try:
        raise ValueError("no row for someone@example.com from 198.51.100.7")
    except ValueError:
        record = logging.LogRecord("fish_server", logging.ERROR, __file__, 1, "failed", None,
                                   sys.exc_info())  # fmt: skip
    out = formatter.format(record)
    assert "Traceback" in out
    assert "ValueError: no row for [email] from [address]" in out
    assert "example.com" not in out


def test_install_scrubs_every_handler_and_can_run_twice() -> None:
    handler = logging.StreamHandler()
    uvicorn = logging.getLogger("uvicorn.error")
    uvicorn.addHandler(handler)
    try:
        install()
        install()
        assert isinstance(handler.formatter, Scrubbed)
        assert not isinstance(handler.formatter.inner, Scrubbed)  # wrapped once
        assert logging.getLogger("fish_server").getEffectiveLevel() == logging.INFO
    finally:
        uvicorn.removeHandler(handler)


def test_each_request_is_logged_without_its_query_or_address(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="fish_server.access")
    client = TestClient(app)
    assert client.get("/sign-in?token=a-secret-token").status_code == 200
    assert client.get("/no-such-page").status_code == 404
    with client.websocket_connect("/ws/echo") as ws:
        assert "server_hello" in ws.receive_text()
    lines = [r.getMessage() for r in caplog.records if r.name == "fish_server.access"]
    assert re.fullmatch(r"GET /sign-in 200 \d+ ms", lines[0])
    assert re.fullmatch(r"GET /no-such-page 404 \d+ ms", lines[1])
    assert re.fullmatch(r"WebSocket /ws/echo 101 \d+ ms", lines[2])
    assert "secret" not in caplog.text
    assert "testclient" not in caplog.text  # the client's address, as the test client gives it


def _command(port: int) -> list[str]:
    """The Dockerfile's command, with ``port``."""
    match = re.search(r'exec (uvicorn [^"]+)"', DOCKERFILE.read_text(encoding="utf-8"))
    assert match is not None
    return shlex.split(match.group(1).replace("${PORT:-8000}", str(port)))


def test_the_dockerfile_turns_uvicorns_access_log_off() -> None:
    command = _command(8000)
    assert "--no-access-log" in command
    assert "--proxy-headers" in command  # the sign-in limit still needs each real address


@pytest.mark.usefixtures("server_env")
def test_the_server_as_deployed_logs_no_address_or_token(tmp_path: Path) -> None:
    """Run uvicorn with the Dockerfile's own flags, send requests through a "proxy" that names
    a client's address, and read every line the server writes."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    out = tmp_path / "server.log"
    env = {**os.environ, "FISH_EMAIL": "console"}
    with out.open("w", encoding="utf-8") as log:
        server = subprocess.Popen(_command(port), stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while True:
            try:
                urllib.request.urlopen(f"{base}/health", timeout=2)
                break
            except OSError:
                if time.monotonic() > deadline or server.poll() is not None:
                    raise
                time.sleep(0.2)
        for path in ("/sign-in?token=a-secret-token", "/health", "/health/db"):
            request = urllib.request.Request(
                base + path, headers={"X-Forwarded-For": "203.0.113.9"}
            )
            urllib.request.urlopen(request, timeout=5).read()
        time.sleep(0.5)  # let the last lines reach the file
    finally:
        server.terminate()
        server.wait(timeout=15)
    written = out.read_text(encoding="utf-8")
    assert re.search(r"GET /sign-in 200 \d+ ms", written), written
    assert re.search(r"GET /health/db 200 \d+ ms", written), written
    for secret in ("203.0.113.9", "127.0.0.1", "a-secret-token", "token="):
        assert secret not in written, f"{secret!r} in the server's output:\n{written}"

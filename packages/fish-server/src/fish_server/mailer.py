"""Sending sign-in emails (T3.1).

``Mailer`` is anything with ``send(to, subject, text, html)``. The server picks one from its
settings (``mailer()``): ``ConsoleMailer`` prints the message in the server's log, for
development; ``ResendMailer`` sends it through Resend's HTTP API, on Render. Tests use
``MemoryMailer``. Nothing else in the server knows which is in use.

Resend is called with the standard library, so the server takes no new dependency; the call
is a blocking HTTPS request, which the sign-in endpoints make from FastAPI's thread pool.
"""

import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import Final, Protocol

from fish_server.settings import email_from, email_mode, resend_api_key

RESEND_URL: Final = "https://api.resend.com/emails"
TIMEOUT_S: Final = 10


class MailError(RuntimeError):
    """The email could not be sent. The message never includes the API key."""


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str, html: str) -> None:
        """Send one email to ``to``, or raise MailError."""
        ...


@dataclass
class MemoryMailer:
    """Keeps every email instead of sending it (tests)."""

    sent: list[dict[str, str]] = field(default_factory=list[dict[str, str]])

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})


class ConsoleMailer:
    """Prints every email to standard error (local development). Never used on Render."""

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        print(f"[email to {to}] {subject}\n{text}", file=sys.stderr, flush=True)


type Opener = Callable[[urllib.request.Request, float], object]


def _open(request: urllib.request.Request, timeout: float) -> object:  # pragma: no cover
    """The real HTTPS request; tests never reach the network."""
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status


@dataclass
class ResendMailer:
    """Sends through Resend. ``opener`` makes the HTTP request; tests replace it."""

    api_key: str
    sender: str
    opener: Opener = _open

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        body = {"from": self.sender, "to": [to], "subject": subject, "text": text, "html": html}
        request = urllib.request.Request(
            RESEND_URL,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "fish-server",
            },
        )
        try:
            self.opener(request, TIMEOUT_S)
        except urllib.error.HTTPError as error:
            raise MailError(f"Resend refused the email: HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError) as error:
            raise MailError(f"Resend could not be reached: {error}") from None


@cache
def mailer() -> Mailer:
    """The mailer the settings name (FISH_EMAIL): ``console`` or ``resend``."""
    if email_mode() == "resend":
        return ResendMailer(resend_api_key(), email_from())
    return ConsoleMailer()

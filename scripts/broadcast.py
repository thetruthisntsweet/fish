"""Send one of the recruitment messages through Resend Broadcasts (T4.1).

The words come from docs/recruitment.md and nowhere else. The script reads the message there,
fills in what the page leaves in braces, and stops if anything is left unfilled; M4 (this
week's game nights) is built from the schedule in §3 of the same page. A message only ever
goes to a list its heading names.

    uv run python scripts/broadcast.py M1 --segment Invited                  # preview only
    uv run python scripts/broadcast.py M1 --segment Invited --create         # a draft
    uv run python scripts/broadcast.py M3 --segment Invited --fill N=25 --create
    uv run python scripts/broadcast.py M4 --segment "Players: group 2" --week 2026-12-14 \\
        --create --send-at 2026-12-14T09:00:00-05:00

Without --create it only prints the message. With --create it makes a draft in Resend: open it
in the dashboard (Broadcasts), send yourself a copy with "Send test email", then send it from
there; --send-at schedules it instead.
The key, RESEND_BROADCAST_KEY, is a full-access Resend key: it lives on your computer only,
never in render.yaml or the repository (docs/runbooks/email.md).
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final

RECRUITMENT: Final = Path(__file__).resolve().parents[1] / "docs" / "recruitment.md"
SENDER: Final = "Sanjeev Kumar (Fish study) <fish@news.thedefinitivesanjeevexperience.com>"
REPLY_TO: Final = "821sanjeevkumar@gmail.com"
API: Final = "https://api.resend.com"
KEY_VAR: Final = "RESEND_BROADCAST_KEY"
PLAYERS: Final = ("Players: group 1", "Players: group 2")
UNSUBSCRIBE: Final = "{{{RESEND_UNSUBSCRIBE_URL}}}"

LAST_WEEK_OPENING: Final = "This is the study's last week. Your group's game nights, Eastern time:"
WEEK_OPENING: Final = "Your group's game nights this week, Eastern time:"
LAST_NIGHT_NOTE: Final = " (the last night)"

MONTHS: Final = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
DAYS: Final = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class RefusedError(Exception):
    """The message cannot be sent as asked; the reason is for the person running this."""


# ---------------------------------------------------------------- the page


@dataclass(frozen=True, slots=True)
class Message:
    key: str
    title: str
    to: tuple[str, ...]
    """The segments its heading names."""
    subject: str
    body: tuple[str, ...]
    """The quoted lines, without "> "; an empty string between paragraphs."""


def messages(page: str) -> dict[str, Message]:
    """Every message on the page, by key (M1, M2, ...)."""
    found: dict[str, Message] = {}
    lines = page.splitlines()
    for i, line in enumerate(lines):
        heading = re.fullmatch(r"### (M\d+) · (.+?) · (.+?) · (.+)", line)
        if heading is None:
            continue
        key, title, _, to = heading.groups()
        rest = lines[i + 1 :]
        subject = next(m.group(1) for s in rest if (m := re.fullmatch(r"\*\*Subject:\*\* (.+)", s)))
        start = next(j for j, s in enumerate(rest) if s.startswith(">"))
        body: list[str] = []
        for s in rest[start:]:
            if not s.startswith(">"):
                break
            body.append(s[2:] if s.startswith("> ") else "")
        lists = PLAYERS if to == "each Players segment" else tuple(to.split(", "))
        found[key] = Message(key, title, lists, subject, tuple(body))
    return found


@dataclass(frozen=True, slots=True)
class Night:
    day: date
    time: str
    who: str
    """ "everyone", "group 1" or "group 2"."""

    def shown(self) -> str:
        return (
            f"{DAYS[self.day.weekday()]} {self.day.day} {MONTHS[self.day.month - 1]}, {self.time}"
        )


def nights(page: str) -> list[Night]:
    """The study's game nights (§3), checked: each date's weekday must be the one written."""
    study = page[page.index("**Study:**") :]
    found: list[Night] = []
    year = 0
    for row in re.findall(
        r"^\| ((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) .+?) \| (.+?) \| (.+?) \|$", study, re.M
    ):
        when, time, who = row
        parts = re.fullmatch(r"(\w{3}) (\d{1,2}) (\w{3})(?: (\d{4}))?(?: \(.+\))?", when)
        if parts is None:
            raise RefusedError(f"§3: cannot read the date {when!r}")
        weekday, day, month, written_year = parts.groups()
        year = int(written_year) if written_year else year
        month_number = [m[:3] for m in MONTHS].index(month) + 1
        night = Night(date(year, month_number, int(day)), time, who)
        if DAYS[night.day.weekday()][:3] != weekday:
            raise RefusedError(f"§3: {when} is a {DAYS[night.day.weekday()]}")
        found.append(night)
    return found


# ---------------------------------------------------------------- filling in


def fill(text: str, values: dict[str, str]) -> str:
    def value(found: re.Match[str]) -> str:
        name = found.group(1)
        if name not in values:
            raise RefusedError(f"{{{name}}} needs a value: --fill {name}=...")
        return values[name]

    return re.sub(r"\{([A-Za-z]\w*)\}", value, text)


def this_week(message: Message, segment: str, week: date, page: str) -> Message:
    """M4 for one group and one week: its nights from §3 in place of the examples."""
    if week.weekday() != 0:
        raise RefusedError(f"--week is a Monday, not a {DAYS[week.weekday()]}")
    group = "group " + segment.removeprefix("Players: group ")
    every = nights(page)
    mine = [
        n
        for n in every
        if week <= n.day < week + timedelta(days=7) and n.who in ("everyone", group)
    ]
    if not mine:
        raise RefusedError(f"no game nights for {group} in the week of {week}")
    last = every[-1] in mine
    listed = [f"- {n.shown()}{LAST_NIGHT_NOTE if n == every[-1] else ''}" for n in mine]
    body: list[str] = []
    examples_done = False
    for line in message.body:
        if line.startswith("- {"):
            if not examples_done:
                body.extend(listed)
                examples_done = True
            continue
        body.append(LAST_WEEK_OPENING if last and line == WEEK_OPENING else line)
    days = " and ".join(DAYS[n.day.weekday()] for n in mine)
    return Message(
        message.key, message.title, message.to, fill(message.subject, {"days": days}), tuple(body)
    )


def prepared(
    page: str, key: str, segment: str, values: dict[str, str], week: date | None
) -> Message:
    """The message ``key`` for ``segment``, filled in and checked."""
    found = messages(page)
    if key not in found:
        raise RefusedError(f"no message {key} in docs/recruitment.md; there are {', '.join(found)}")
    message = found[key]
    if segment not in message.to:
        raise RefusedError(f"{key} goes to {' or '.join(message.to)}, not {segment!r}")
    if key == "M4":
        if week is None:
            raise RefusedError("M4 needs --week, the Monday it is sent")
        message = this_week(message, segment, week, page)
    body = tuple(fill(line, values) for line in message.body)
    subject = fill(message.subject, values)
    left = [s for s in (subject, *body) if "{" in s or "}" in s]
    if left:
        raise RefusedError(f"still in braces: {left[0]!r}")
    return Message(message.key, message.title, message.to, subject, body)


# ---------------------------------------------------------------- as an email

URL: Final = re.compile(r"https://[^\s<>()\"]+[^\s<>()\".,;:!?]|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def blocks(body: tuple[str, ...]) -> list[list[str]]:
    """The body's paragraphs, each its lines."""
    found: list[list[str]] = [[]]
    for line in body:
        if line:
            found[-1].append(line)
        elif found[-1]:
            found.append([])
    return [b for b in found if b]


def joined(lines: list[str]) -> list[str]:
    """A paragraph's lines as its sentences run on, with a line break kept only after a
    greeting or a sign-off ("Hi,", "Thanks,"), as a letter has them."""
    out: list[str] = []
    for line in lines:
        if out and not (out[-1].endswith(",") and len(out[-1].split()) <= 2):
            out[-1] += " " + line
        else:
            out.append(line)
    return out


def linked(text: str) -> str:
    """``text`` as HTML, with every address and email a link."""
    out: list[str] = []
    at = 0
    for found in URL.finditer(text):
        target = found.group(0)
        href = target if target.startswith("https://") else f"mailto:{target}"
        out += [
            html.escape(text[at : found.start()]),
            f'<a href="{html.escape(href)}">{html.escape(target)}</a>',
        ]
        at = found.end()
    return "".join([*out, html.escape(text[at:])])


def as_html(message: Message) -> str:
    parts: list[str] = []
    for block in blocks(message.body):
        if block == ["[unsubscribe]"]:
            parts.append(
                '<p style="font-size:13px;color:#5a6470;margin-top:28px">'
                f'<a href="{UNSUBSCRIBE}" style="color:#5a6470">Unsubscribe</a></p>'
            )
        elif all(line.startswith("- ") for line in block):
            items = "".join(f"<li>{linked(line[2:])}</li>" for line in block)
            parts.append(f'<ul style="padding-left:20px">{items}</ul>')
        else:
            parts.append("<p>" + "<br>".join(linked(line) for line in joined(block)) + "</p>")
    style = "font-family:-apple-system,'Segoe UI',Roboto,sans-serif;font-size:16px;line-height:1.5"
    return f'<div style="{style};color:#1d232b;max-width:36rem">{"".join(parts)}</div>'


def as_text(message: Message) -> str:
    parts: list[str] = []
    for block in blocks(message.body):
        if block == ["[unsubscribe]"]:
            parts.append(f"Unsubscribe: {UNSUBSCRIBE}")
        elif all(line.startswith("- ") for line in block):
            parts.append("\n".join(block))
        else:
            parts.append("\n".join(joined(block)))
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------- Resend


def call(method: str, path: str, key: str, body: object = None) -> dict[str, object]:
    request = urllib.request.Request(
        API + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "fish-broadcast/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as refused:
        with refused:
            detail = refused.read().decode(errors="replace")
        raise RefusedError(f"Resend answered {refused.code} to {method} {path}: {detail}") from None


def segment_id(name: str, key: str) -> str:
    listed = call("GET", "/segments", key)
    data = listed.get("data")
    segments = data if isinstance(data, list) else []
    for segment in segments:
        if isinstance(segment, dict) and segment.get("name") == name:
            return str(segment["id"])
    names = ", ".join(str(s.get("name")) for s in segments if isinstance(s, dict))
    raise RefusedError(f"Resend has no segment named {name!r}; it has: {names or 'none'}")


def create(message: Message, segment: str, key: str, send_at: datetime | None) -> str:
    body: dict[str, object] = {
        "segment_id": segment_id(segment, key),
        "from": SENDER,
        "reply_to": REPLY_TO,
        "subject": message.subject,
        "html": as_html(message),
        "text": as_text(message),
        "name": f"{message.key} {message.title}: {segment}",
    }
    if send_at is not None:
        body |= {"send": True, "scheduled_at": send_at.isoformat()}
    return str(call("POST", "/broadcasts", key, body)["id"])


# ---------------------------------------------------------------- command line


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send a recruitment message (docs/recruitment.md)."
    )
    parser.add_argument("message", help="M1 to M7")
    parser.add_argument("--segment", required=True, help="the list the message goes to")
    parser.add_argument("--fill", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--week", type=date.fromisoformat, help="M4: the Monday it is sent")
    parser.add_argument("--create", action="store_true", help="make it in Resend (a draft)")
    parser.add_argument(
        "--send-at", type=datetime.fromisoformat, help="schedule it, e.g. 2026-11-16T09:00:00-05:00"
    )
    args = parser.parse_args(argv)
    values = {name: value for name, _, value in (pair.partition("=") for pair in args.fill)}
    try:
        if args.send_at is not None:
            if not args.create:
                raise RefusedError("--send-at needs --create")
            if args.send_at.tzinfo is None:
                raise RefusedError("--send-at needs a time zone, e.g. 2026-11-16T09:00:00-05:00")
            if args.send_at <= (now or datetime.now(args.send_at.tzinfo)):
                raise RefusedError("--send-at is in the past")
        message = prepared(
            RECRUITMENT.read_text(encoding="utf-8"), args.message, args.segment, values, args.week
        )
        print(f"From:     {SENDER}\nReply-To: {REPLY_TO}\nTo:       {args.segment}")
        print(f"Subject:  {message.subject}\n\n{as_text(message)}")
        if not args.create:
            print("(preview only: add --create to make it in Resend)")
            return 0
        key = os.environ.get(KEY_VAR, "").strip()
        if not key:
            raise RefusedError(f"{KEY_VAR} is not set (docs/runbooks/email.md)")
        made = create(message, args.segment, key, args.send_at)
    except RefusedError as reason:
        print(f"Not sent: {reason}", file=sys.stderr)
        return 1
    if args.send_at is None:
        print(
            f"Draft {made} made. In Resend (Broadcasts), send yourself a copy with "
            '"Send test email", read it, then send it from there.'
        )
    else:
        print(f"Broadcast {made} scheduled for {args.send_at.isoformat()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

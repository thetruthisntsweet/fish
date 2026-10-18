"""Actions as plain data, for storing a game as its seed plus its actions (docs/determinism.md §8).

``action_to_data`` gives a dict of strings, ints and lists of ints, ready for JSON;
``action_from_data`` reverses it exactly and rejects anything malformed. Whether the values
are legal is the engine's business, not the codec's. The corpus schema (T1.6) may wrap these
dicts, but should not change their contents without a new encoding name.
"""

from collections.abc import Mapping
from dataclasses import fields
from typing import Final

from fish_rules.events import (
    Action,
    Ask,
    Assign,
    AssignTimeout,
    Call,
    ChoiceTimeout,
    Choose,
    CloseWindow,
    Declare,
    OpenWindow,
    Pass,
    Vote,
)

ACTION_ENCODING: Final = "fish-actions-v1"
"""Names this encoding. Recorded next to stored actions."""

_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "Ask": ("seat", "target", "card"),
    "Call": ("seat", "set_id"),
    "Declare": ("seat", "set_id"),
    "Pass": ("seat",),
    "Assign": ("seat", "holders"),
    "Choose": ("seat", "chosen"),
    "Vote": ("seat", "chosen"),
    "OpenWindow": (),
    "CloseWindow": (),
    "AssignTimeout": (),
    "ChoiceTimeout": (),
}


def action_to_data(action: Action) -> dict[str, object]:
    """``action`` as ``{"type": <class name>, <field>: <int or list of ints>, ...}``."""
    data: dict[str, object] = {"type": type(action).__name__}
    for field in fields(action):
        value: object = getattr(action, field.name)
        data[field.name] = list(value) if isinstance(value, tuple) else value  # pyright: ignore[reportUnknownArgumentType]
    return data


def _int(data: Mapping[str, object], key: str) -> int:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an int, got {value!r}")
    return value


def _ints(data: Mapping[str, object], key: str) -> tuple[int, ...]:
    value = data[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of ints, got {value!r}")
    items: list[object] = list(value)  # pyright: ignore[reportUnknownArgumentType]
    out: list[int] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{key} must be a list of ints, got {value!r}")
        out.append(item)
    return tuple(out)


def action_from_data(data: Mapping[str, object]) -> Action:
    """The action ``data`` encodes. Raises ValueError if it is not exactly one action's fields."""
    kind = data.get("type")
    if not isinstance(kind, str) or kind not in _FIELDS:
        raise ValueError(f"unknown action type {kind!r}")
    expected = {"type", *_FIELDS[kind]}
    if set(data) != expected:
        raise ValueError(f"{kind} needs exactly the keys {sorted(expected)}, got {sorted(data)}")
    match kind:
        case "Ask":
            return Ask(_int(data, "seat"), _int(data, "target"), _int(data, "card"))
        case "Call":
            return Call(_int(data, "seat"), _int(data, "set_id"))
        case "Declare":
            return Declare(_int(data, "seat"), _int(data, "set_id"))
        case "Pass":
            return Pass(_int(data, "seat"))
        case "Assign":
            return Assign(_int(data, "seat"), _ints(data, "holders"))
        case "Choose":
            return Choose(_int(data, "seat"), _int(data, "chosen"))
        case "Vote":
            return Vote(_int(data, "seat"), _int(data, "chosen"))
        case "OpenWindow":
            return OpenWindow()
        case "CloseWindow":
            return CloseWindow()
        case "AssignTimeout":
            return AssignTimeout()
        case _:
            return ChoiceTimeout()

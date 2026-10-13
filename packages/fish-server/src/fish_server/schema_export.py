"""Write the JSON Schema for every protocol message (T2.1 subtask 8).

Run through ``scripts/gen_types.sh``, which then converts the schemas to TypeScript.
Usage: ``python -m fish_server.schema_export OUT_DIR``. Writes one ``<Message>.json``
per message and deletes any other ``.json`` file in OUT_DIR, so a removed message
cannot leave a stale schema behind.
"""

import json
import sys
from pathlib import Path
from typing import Any

from fish_server.protocol import CLIENT_MESSAGES, SERVER_MESSAGES


def _drop_field_titles(node: Any) -> None:
    """Remove the ``title`` Pydantic puts on every field, at any depth.

    With field titles, the TypeScript generator emits a separate exported type per field
    (``Type``, ``ProtocolVersion``, ...), and those names collide across files. Model
    titles are kept: they become the interface names.
    """
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            for field in props.values():
                if isinstance(field, dict):
                    field.pop("title", None)
        for value in node.values():
            _drop_field_titles(value)
    elif isinstance(node, list):
        for item in node:
            _drop_field_titles(item)


def schemas() -> dict[str, dict[str, Any]]:
    """Return {file name: schema} for every message, in a stable order.

    Client messages use the schema of what the server accepts ("validation");
    server messages use the schema of what the server sends ("serialization").
    """
    out: dict[str, dict[str, Any]] = {}
    for model in CLIENT_MESSAGES:
        out[f"{model.__name__}.json"] = model.model_json_schema(mode="validation")
    for model in SERVER_MESSAGES:
        out[f"{model.__name__}.json"] = model.model_json_schema(mode="serialization")
    for schema in out.values():
        _drop_field_titles(schema)
    return dict(sorted(out.items()))


def write(out_dir: Path) -> list[Path]:
    """Write every schema to ``out_dir``; remove stale ones. Returns the files written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = schemas()
    for old in sorted(out_dir.glob("*.json")):
        if old.name not in wanted:
            old.unlink()
    written: list[Path] = []
    for name, schema in wanted.items():
        path = out_dir / name
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m fish_server.schema_export OUT_DIR", file=sys.stderr)
        return 2
    for path in write(Path(args[0])):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

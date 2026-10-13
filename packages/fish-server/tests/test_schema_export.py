"""Tests for fish_server.schema_export (T2.1 subtask 8)."""

import json
from pathlib import Path

import pytest

from fish_server.schema_export import main, schemas, write

REPO_SCHEMAS = Path(__file__).resolve().parents[3] / "schemas"


def test_one_schema_per_message() -> None:
    assert list(schemas()) == ["ClientHello.json", "ServerHello.json"]


def test_schemas_forbid_unknown_fields_and_require_every_field() -> None:
    for schema in schemas().values():
        assert schema["additionalProperties"] is False
        assert sorted(schema["required"]) == sorted(schema["properties"])


def test_fields_have_no_titles() -> None:
    """Field titles would make the TypeScript generator emit colliding type names."""
    for schema in schemas().values():
        assert all("title" not in field for field in schema["properties"].values())


def test_write_creates_files_and_removes_stale_ones(tmp_path: Path) -> None:
    (tmp_path / "Removed.json").write_text("{}", encoding="utf-8")
    written = write(tmp_path)
    assert sorted(p.name for p in tmp_path.glob("*.json")) == [p.name for p in written]
    assert json.loads((tmp_path / "ServerHello.json").read_text())["title"] == "ServerHello"


def test_write_is_deterministic(tmp_path: Path) -> None:
    write(tmp_path / "a")
    write(tmp_path / "b")
    for name in schemas():
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_committed_schemas_are_current(tmp_path: Path) -> None:
    """Same check as scripts/gen_types.sh --check, for the Python half."""
    write(tmp_path)
    for name in schemas():
        assert (REPO_SCHEMAS / name).read_bytes() == (tmp_path / name).read_bytes(), name


def test_main_writes_to_the_given_folder(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 0
    assert (tmp_path / "ClientHello.json").exists()


def test_main_without_a_folder_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err

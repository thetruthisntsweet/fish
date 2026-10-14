"""Tests for fish_server.deploy, the pre-deploy command (T2.1 subtask 14)."""

from pathlib import Path

import pytest
from sqlalchemy.exc import DBAPIError

from fish_server import deploy
from fish_server.settings import ADMIN_DATABASE_URL_VAR, APP_PASSWORD_VAR

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def test_first_and_second_deploy_on_a_fresh_database(
    fresh_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(ADMIN_DATABASE_URL_VAR, fresh_database_url)
    monkeypatch.setenv(APP_PASSWORD_VAR, "deploy-test-password-0123456789")
    assert deploy.main(["--alembic-ini", str(ALEMBIC_INI)]) == 0
    assert "Pre-deploy checks passed." in capsys.readouterr().out
    assert deploy.main(["--alembic-ini", str(ALEMBIC_INI)]) == 0  # nothing to migrate
    assert "Login role: updated." in capsys.readouterr().out


def test_failed_checks_cancel_the_deploy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(deploy, "run", lambda _ini: ["can create tables"])
    assert deploy.main([]) == 1
    assert "FAIL: can create tables" in capsys.readouterr().out


def test_database_refusals_are_one_readable_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    refusal = Exception(
        "permission denied to create role\nDETAIL: Only roles with the CREATEROLE attribute"
    )

    def refuse(_ini: Path) -> list[str]:
        raise DBAPIError("CREATE ROLE fish_app NOLOGIN", None, refusal)

    monkeypatch.setattr(deploy, "run", refuse)
    assert deploy.main([]) == 1
    out = capsys.readouterr().out
    assert "FAIL: database refused a step: permission denied to create role" in out
    assert "needs the CREATEROLE attribute" in out

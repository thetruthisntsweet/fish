"""Deploying the study's site (T4.3; .github/workflows/deploy.yml, scripts/check_deploy.py):
only a site tag on main, whose commit passed CI, moves the production
branch that Render deploys; run by hand, the workflow checks a tag and moves nothing."""

import importlib.util
import subprocess
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
import yaml

ROOT: Final = Path(__file__).resolve().parents[3]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_deploy", ROOT / "scripts/check_deploy.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = _script()


@pytest.mark.parametrize(
    ("tag", "day"),
    [
        ("site-2026.12.07", date(2026, 12, 7)),
        ("site-2026.12.07.2", date(2026, 12, 7)),
        ("site-2027.02.14.10", date(2027, 2, 14)),
    ],
)
def test_a_site_tag_names_its_day(tag: str, day: date) -> None:
    assert SCRIPT.check_tag(tag) == day


@pytest.mark.parametrize(
    ("tag", "message"),
    [
        ("v0.3.0", "not a site tag"),
        ("site-2026-12-07", "not a site tag"),
        ("site-2026.12.07.1", "not a site tag"),  # the first of a day has no number
        ("site-2026.12.07.02", "not a site tag"),
        ("site-2026.12.07; rm -rf /", "not a site tag"),
        ("site-2026.02.30", "names no real day"),
    ],
)
def test_anything_else_is_refused(tag: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SCRIPT.check_tag(tag)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def test_only_a_commit_on_main_may_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    for name in ("a", "b"):
        (tmp_path / name).write_text(name)
        _git(tmp_path, "add", name)
        _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)
    merged = _git(tmp_path, "rev-parse", "HEAD~1")
    _git(tmp_path, "switch", "-qc", "unmerged")
    (tmp_path / "c").write_text("c")
    _git(tmp_path, "add", "c")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
    monkeypatch.chdir(tmp_path)
    assert SCRIPT.main(["site-2026.12.07", "--commit", merged, "--main", "main"]) == 0
    assert "OK: site-2026.12.07 (Mon 7 Dec 2026) is on main" in capsys.readouterr().out
    assert SCRIPT.main(["site-2026.12.07", "--commit", "HEAD", "--main", "main"]) == 1
    assert "not on main: merge it first" in capsys.readouterr().out
    assert SCRIPT.main(["site-2026.12.07", "--commit", "nonsense", "--main", "main"]) == 1
    assert "git cannot compare" in capsys.readouterr().out


def workflow() -> dict[Any, Any]:
    return yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))


def test_only_site_tags_and_rehearsals_run_it() -> None:
    triggers = workflow()[True]  # YAML reads the key `on` as true
    assert triggers["push"] == {"tags": ["site-*"]}
    assert "tag" in triggers["workflow_dispatch"]["inputs"]
    assert workflow()["concurrency"] == {"group": "deploy", "cancel-in-progress": False}


def test_production_moves_only_after_both_checks_and_only_on_a_tag() -> None:
    assert workflow()["permissions"] == {"contents": "read"}
    (job,) = workflow()["jobs"].values()
    assert job["permissions"] == {"contents": "write", "actions": "read"}
    steps = {step.get("name", ""): step for step in job["steps"]}
    names = list(steps)
    assert names.index("The tag is a site tag, on main") < names.index("Move production")
    assert names.index("CI passed on its commit") < names.index("Move production")
    assert "scripts/check_deploy.py" in steps["The tag is a site tag, on main"]["run"]
    assert "--workflow ci.yml" in steps["CI passed on its commit"]["run"]
    move = steps["Move production"]
    assert move["if"] == "github.event_name == 'push'"
    assert 'refs/heads/production"' in move["run"]
    pushes = [s for s in job["steps"] if "git push" in s.get("run", "")]
    assert pushes == [move]
    assert "${{" not in move["run"]  # the tag reaches the shell only through the environment

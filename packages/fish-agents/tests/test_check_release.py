"""The release check (scripts/check_release.py) lets a tag through only when the packages, the
changelog and the citation all name its version, and gives the changelog entry as notes."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "check_release.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_release", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_release = load()
VERSION = check_release.version_of("fish-rules", ROOT)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of the files the check reads."""
    for package in check_release.PUBLISHED:
        (tmp_path / "packages" / package).mkdir(parents=True)
        shutil.copy(ROOT / "packages" / package / "pyproject.toml", tmp_path / "packages" / package)
    for name in ("CHANGELOG.md", "CITATION.cff"):
        shutil.copy(ROOT / name, tmp_path)
    return tmp_path


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def set_citation_date(repo: Path, date: str) -> None:
    citation = (repo / "CITATION.cff").read_text(encoding="utf-8")
    line = next(line for line in citation.splitlines() if line.startswith("date-released: "))
    edit(repo / "CITATION.cff", line, f'date-released: "{date}"')


def test_this_version_can_be_released() -> None:
    notes = check_release.release_notes(f"v{VERSION}")
    assert notes.strip()
    assert notes.strip() in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "\n## " not in notes


def test_the_notes_stop_at_the_previous_entry(repo: Path) -> None:
    edit(
        repo / "CHANGELOG.md",
        f"## {VERSION} (",
        f"## 9.9.9 (2027-01-01)\n\nLater.\n\n## {VERSION} (",
    )
    for package in check_release.PUBLISHED:
        edit(
            repo / "packages" / package / "pyproject.toml",
            f'version = "{VERSION}"',
            'version = "9.9.9"',
        )
    edit(repo / "CITATION.cff", f"version: {VERSION}", "version: 9.9.9")
    set_citation_date(repo, "2027-01-01")
    assert check_release.release_notes("v9.9.9", repo) == "Later.\n"


@pytest.mark.parametrize("tag", ["0.1.0", "v0.1", "v0.1.0rc1", "release-0.1.0"])
def test_only_version_tags_are_releases(tag: str) -> None:
    with pytest.raises(check_release.ReleaseError, match="not a release tag"):
        check_release.release_notes(tag)


def test_every_package_must_be_at_the_tagged_version(repo: Path) -> None:
    edit(
        repo / "packages" / "fish-env" / "pyproject.toml",
        f'version = "{VERSION}"',
        'version = "0.0.9"',
    )
    with pytest.raises(check_release.ReleaseError, match=r"fish-env is at 0\.0\.9"):
        check_release.release_notes(f"v{VERSION}", repo)
    with pytest.raises(check_release.ReleaseError, match="fish-rules is at"):
        check_release.release_notes("v0.0.9", repo)


def test_the_changelog_must_have_an_entry(repo: Path) -> None:
    edit(repo / "CHANGELOG.md", f"## {VERSION} (", f"## {VERSION}-draft (")
    with pytest.raises(check_release.ReleaseError, match="no '## "):
        check_release.release_notes(f"v{VERSION}", repo)


def test_the_entry_must_not_be_empty(repo: Path) -> None:
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = text.index(f"## {VERSION} (")
    end = text.index("\n", heading) + 1
    (repo / "CHANGELOG.md").write_text(text[:end] + "\n", encoding="utf-8")
    with pytest.raises(check_release.ReleaseError, match="is empty"):
        check_release.release_notes(f"v{VERSION}", repo)


def test_the_citation_must_name_the_version_and_date(repo: Path) -> None:
    set_citation_date(repo, "1999-01-01")
    with pytest.raises(check_release.ReleaseError, match="date-released"):
        check_release.release_notes(f"v{VERSION}", repo)
    edit(repo / "CITATION.cff", f"version: {VERSION}", "version: 0.0.9")
    with pytest.raises(check_release.ReleaseError, match="does not name version"):
        check_release.release_notes(f"v{VERSION}", repo)


def test_the_command_writes_the_notes(tmp_path: Path) -> None:
    notes = tmp_path / "notes.md"
    done = subprocess.run(
        [sys.executable, str(SCRIPT), f"v{VERSION}", "--notes", str(notes)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert "agree" in done.stdout
    assert notes.read_text(encoding="utf-8") == check_release.release_notes(f"v{VERSION}")


def test_the_command_fails_on_a_wrong_tag() -> None:
    done = subprocess.run([sys.executable, str(SCRIPT), "v99.0.0"], capture_output=True, text=True)
    assert done.returncode == 1
    assert done.stderr.startswith("FAIL fish-rules is at")

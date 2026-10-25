"""Release metadata (T2.6): fish-rules, fish-env and fish-agents are published together, at one
version, with the licence, readme and links PyPI shows; the other packages can never be
uploaded. Building and installing the packages is checked separately, outside the workspace.
"""

import filecmp
import re
import tomllib
from importlib import import_module, metadata
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[3]
PUBLISHED = ("fish-rules", "fish-env", "fish-agents")
PRIVATE = ("fish-server", "fish-research")
URLS = {"Homepage", "Documentation", "Changelog", "Issues"}


def project(name: str) -> dict[str, Any]:
    data = tomllib.loads((ROOT / "packages" / name / "pyproject.toml").read_text("utf-8"))
    return data["project"]


def requirements(name: str) -> list[str]:
    spec = project(name)
    optional: dict[str, list[str]] = spec.get("optional-dependencies", {})
    return [*spec["dependencies"], *(r for group in optional.values() for r in group)]


def test_the_published_packages_share_one_version() -> None:
    versions = {project(name)["version"] for name in PUBLISHED}
    assert len(versions) == 1
    (version,) = versions
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), "semantic versioning (T2.1)"


@pytest.mark.parametrize("name", PUBLISHED)
def test_the_installed_version_is_the_declared_one(name: str) -> None:
    declared = project(name)["version"]
    assert metadata.version(name) == declared
    assert import_module(name.replace("-", "_")).__version__ == declared


@pytest.mark.parametrize("name", PUBLISHED)
def test_metadata_for_pypi(name: str) -> None:
    spec = project(name)
    folder = ROOT / "packages" / name
    assert spec["license"] == "Apache-2.0"
    assert spec["license-files"] == ["LICENSE"]
    assert filecmp.cmp(folder / "LICENSE", ROOT / "LICENSE", shallow=False)
    assert spec["readme"] == "README.md"
    assert (folder / "README.md").read_text("utf-8").startswith(f"# {name}\n")
    assert 0 < len(spec["description"]) <= 90
    assert spec["requires-python"] == ">=3.14"
    assert "Programming Language :: Python :: 3.14" in spec["classifiers"]
    assert "Private :: Do Not Upload" not in spec["classifiers"]
    assert set(spec["urls"]) == URLS


@pytest.mark.parametrize("name", PUBLISHED)
def test_dependencies_are_bounded(name: str) -> None:
    """Sibling packages must match this minor version: fish-env 0.1 is built for fish-rules
    0.1. Other dependencies name the oldest version that is tested."""
    major, minor, _ = project(name)["version"].split(".")
    for requirement in requirements(name):
        sibling = re.fullmatch(r"(fish-[a-z]+)(.*)", requirement)
        if sibling is not None:
            assert sibling[1] in PUBLISHED
            assert sibling[2] == f">={major}.{minor},<{major}.{int(minor) + 1}", requirement
        elif requirement != "torch":
            assert ">=" in requirement, f"{requirement} needs a lower bound"


@pytest.mark.parametrize("name", PRIVATE)
def test_the_other_packages_can_never_be_uploaded(name: str) -> None:
    assert "Private :: Do Not Upload" in project(name)["classifiers"]


def test_the_changelog_and_citation_name_this_version() -> None:
    """A release names its version in CHANGELOG.md and CITATION.cff, with the same date."""
    version = project("fish-rules")["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text("utf-8")
    entry = re.search(rf"^## {re.escape(version)} \((\d{{4}}-\d{{2}}-\d{{2}})\)$", changelog, re.M)
    assert entry is not None, f"CHANGELOG.md has no entry for {version}"
    citation = (ROOT / "CITATION.cff").read_text("utf-8")
    assert re.search(rf"^version: {re.escape(version)}$", citation, re.M)
    assert re.search(rf'^date-released: "{entry[1]}"$', citation, re.M)

"""docs/rules.md is the ruleset the code implements: it is the version in fish_rules.version,
and it numbers exactly the rules the traceability check lists (scripts/check_rule_citations.py),
so a rule cannot be added, removed or renumbered in one place only."""

import importlib.util
import re
from pathlib import Path

from fish_rules.version import RULESET_VERSION

ROOT = Path(__file__).parents[3]
RULES_DOC = (ROOT / "docs" / "rules.md").read_text(encoding="utf-8")


def check_rule_citations_rules() -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location(
        "check_rule_citations", ROOT / "scripts" / "check_rule_citations.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RULES


def test_r10_1_the_document_is_this_ruleset_version() -> None:
    """R.10.1: the document's version is the one the engine records."""
    assert RULES_DOC.startswith(f"# Canonical Ruleset v{RULESET_VERSION}\n")
    assert f"This is ruleset v{RULESET_VERSION}." in RULES_DOC


def test_the_document_numbers_exactly_the_rules_that_are_traced() -> None:
    numbered = re.findall(r"^- \*\*(R\.\d+(?:\.\d+)?)\*\* ", RULES_DOC, flags=re.MULTILINE)
    assert tuple(numbered) == check_rule_citations_rules()

from fish_rules.version import RULESET_VERSION


def test_ruleset_version_is_v1_1() -> None:
    """R.10.1: this code implements Canonical Ruleset v1.1."""
    assert RULESET_VERSION == "1.1"

from fish_rules.version import RULESET_VERSION


def test_ruleset_version_is_v1_0() -> None:
    """R.10.1: this code implements Canonical Ruleset v1.0."""
    assert RULESET_VERSION == "1.0"

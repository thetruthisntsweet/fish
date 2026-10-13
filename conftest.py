"""Shared pytest setup: Hypothesis profiles (Implementation Environment §8).

Pick a profile with the HYPOTHESIS_PROFILE environment variable; default is "dev".
"""

import os

from hypothesis import HealthCheck, settings

settings.register_profile("dev", max_examples=100)
settings.register_profile(
    "ci",
    max_examples=1_000,
    derandomize=True,  # same examples every CI run, so a failure is reproducible
    deadline=None,  # CI machines are slow and unpredictable
    print_blob=True,  # prints a code to replay any failure exactly
)
settings.register_profile(
    "nightly",
    max_examples=50_000,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

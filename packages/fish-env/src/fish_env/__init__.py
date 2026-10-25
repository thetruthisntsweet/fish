"""fish-env: the Fish benchmark environment, a PettingZoo AEC environment (T2.3)."""

from importlib import metadata

from fish_env.env import AGENTS, FishEnv, env

__all__ = ["AGENTS", "FishEnv", "env"]

__version__ = metadata.version("fish-env")
"""The installed package's version, from its metadata (pyproject.toml)."""

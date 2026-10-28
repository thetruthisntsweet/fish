"""fish-env: the Fish benchmark environment, a PettingZoo AEC environment (T2.3)."""

from importlib import metadata

from fish_env.env import AGENTS, FishEnv, env
from fish_env.memory import MemoryWrapper, memory_env

__all__ = ["AGENTS", "FishEnv", "MemoryWrapper", "env", "memory_env"]

__version__ = metadata.version("fish-env")
"""The installed package's version, from its metadata (pyproject.toml)."""

"""fish-agents: the baseline agents (T5.1-T5.5) and the interface they share.

``fish_agents.base`` (the ``Agent`` interface and ``PolicyStreams``) needs only fish-rules, so
the server can run agents as bots. ``fish_agents.play`` runs agents in the environment.
"""

from fish_agents.base import Agent, PolicyStreams

__all__ = ["Agent", "PolicyStreams"]

__version__ = "0.0.0"

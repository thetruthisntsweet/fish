"""Deterministic random numbers for the rules (Implementation Environment §6).

A corpus game is a seed plus an event log, so replaying a seed must give the same
deal, first player and priority orders forever, on any machine and any Python
version. Python's ``random`` and NumPy's ``Generator`` do not promise that, so the
rules use this small generator instead.

FROZEN: the arithmetic in this module is part of every recorded game. Changing it
breaks replay of existing games and requires a new ruleset version (R.10).
"""

from typing import Final

_MASK64: Final = (1 << 64) - 1  # 64 one-bits: keeps a number inside 64 bits
_GOLDEN_GAMMA: Final = 0x9E3779B97F4A7C15  # added to the state on every call
_MIX1: Final = 0xBF58476D1CE4E5B9
_MIX2: Final = 0x94D049BB133111EB


class SplitMix64:
    """SplitMix64 (Steele, Lea and Flood, 2014), as in Vigna's reference ``splitmix64.c``.

    Holds a 64-bit state and returns 64-bit unsigned integers. Not cryptographic;
    seeds are chosen by the server, never derived from this generator.
    """

    __slots__ = ("_state",)

    def __init__(self, state: int) -> None:
        self._state = state & _MASK64

    def next_u64(self) -> int:
        """Return the next 64-bit unsigned integer and advance the state."""
        self._state = (self._state + _GOLDEN_GAMMA) & _MASK64  # step the state
        z = self._state
        z = ((z ^ (z >> 30)) * _MIX1) & _MASK64  # mix round 1
        z = ((z ^ (z >> 27)) * _MIX2) & _MASK64  # mix round 2
        return z ^ (z >> 31)  # final mix

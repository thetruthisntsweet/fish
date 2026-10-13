"""Deterministic random numbers for the rules (Implementation Environment §6).

A corpus game is a seed plus an event log, so replaying a seed must give the same
deal, first player and priority orders forever, on any machine and any Python
version. Python's ``random`` and NumPy's ``Generator`` do not promise that, so the
rules use this small generator instead.

FROZEN: the arithmetic in this module is part of every recorded game. Changing it
breaks replay of existing games and requires a new ruleset version (R.10).
"""

import hashlib
from collections.abc import Iterable, Sequence
from typing import Final, Literal, get_args

RNG_ALGORITHM: Final = "splitmix64-sha256-v1"
"""Names this exact algorithm. Recorded in every game next to RULESET_VERSION; changes only
together with a new ruleset version (R.10)."""

_MASK64: Final = (1 << 64) - 1
_GOLDEN_GAMMA: Final = 0x9E3779B97F4A7C15
_MIX1: Final = 0xBF58476D1CE4E5B9
_MIX2: Final = 0x94D049BB133111EB


def _check_int(value: object, what: str) -> int:
    """Return ``value`` if it is an int; raise TypeError otherwise. Rejects bools, which
    Python counts as ints (``True == 1``)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{what} must be an int, got {type(value).__name__}")
    return value


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
        self._state = (self._state + _GOLDEN_GAMMA) & _MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * _MIX1) & _MASK64
        z = ((z ^ (z >> 27)) * _MIX2) & _MASK64
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        """Return a uniform integer in [0, n), for 1 <= n <= 2**64, with no modulo bias.

        Draws ``x`` and rejects it while ``x < (2**64 - n) % n``; the values left are an
        exact multiple of ``n``, so ``x % n`` is uniform. Always draws at least once,
        including for ``n == 1``. FROZEN: the draw order is part of every recorded game.
        """
        n = _check_int(n, "n")
        if not 1 <= n <= _MASK64 + 1:
            raise ValueError(f"n must be in [1, 2**64], got {n}")
        threshold = (_MASK64 + 1 - n) % n
        while True:
            x = self.next_u64()
            if x >= threshold:
                return x % n

    def between(self, lo: int, hi: int) -> int:
        """Return a uniform integer in [lo, hi], both ends included. Uses one ``below`` call."""
        lo, hi = _check_int(lo, "lo"), _check_int(hi, "hi")
        if lo > hi:
            raise ValueError(f"lo must not exceed hi, got lo={lo}, hi={hi}")
        return lo + self.below(hi - lo + 1)

    def choice[T](self, items: Sequence[T]) -> T:
        """Return one element of ``items``, chosen uniformly: ``items[below(len(items))]``."""
        if len(items) == 0:
            raise ValueError("cannot choose from an empty sequence")
        return items[self.below(len(items))]

    def shuffled[T](self, items: Iterable[T]) -> list[T]:
        """Return a new list holding ``items`` in random order. The input is not changed.

        Fisher-Yates, FROZEN order: for i from n-1 down to 1, j = below(i + 1), then swap
        positions i and j. Uses exactly n-1 ``below`` calls. Changing the loop direction or
        the draw order changes every recorded deal.
        """
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.below(i + 1)
            out[i], out[j] = out[j], out[i]
        return out


# ---------------------------------------------------------------- streams (§6)

StreamName = Literal["deal", "first_player", "priority", "tiebreak", "bot_delay", "bot_policy"]
"""The named streams of a game. Each use of randomness draws from its own stream (§6)."""

STREAM_NAMES: Final[tuple[StreamName, ...]] = get_args(StreamName)

_DOMAIN: Final = b"fish-rng-v1\x00"


def _check_u64(value: object, what: str) -> int:
    """Return ``value`` if it is an int in [0, 2**64); raise otherwise. Rejects bools."""
    value = _check_int(value, what)
    if not 0 <= value <= _MASK64:
        raise ValueError(f"{what} must be in [0, 2**64), got {value}")
    return value


def stream(game_seed: int, name: StreamName, index: int = 0) -> SplitMix64:
    """Return the generator for one named stream of one game.

    The starting state is the first 8 bytes (big-endian) of SHA-256 over::

        b"fish-rng-v1\\x00"
        + game_seed      (8 bytes, big-endian)
        + len(name)      (1 byte)
        + name           (UTF-8)
        + index          (8 bytes, big-endian)
    """
    seed = _check_u64(game_seed, "game_seed")
    idx = _check_u64(index, "index")
    if name not in STREAM_NAMES:
        raise ValueError(f"unknown stream name {name!r}; expected one of {STREAM_NAMES}")
    name_bytes = name.encode("utf-8")
    data = (
        _DOMAIN
        + seed.to_bytes(8, "big")
        + len(name_bytes).to_bytes(1, "big")
        + name_bytes
        + idx.to_bytes(8, "big")
    )
    digest = hashlib.sha256(data).digest()
    return SplitMix64(int.from_bytes(digest[:8], "big"))

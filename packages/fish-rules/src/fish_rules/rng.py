"""Deterministic randomness (T2.1 tab, section 6).

Project-owned SplitMix64 generator, named sub-streams seeded from
SHA-256(game seed, stream name, index), and a Fisher-Yates shuffle.
No dependency on Python's or NumPy's random modules, so a seed replays
identically on every version.
"""

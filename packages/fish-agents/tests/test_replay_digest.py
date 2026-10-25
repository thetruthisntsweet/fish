"""The replay digest (scripts/replay_digest.py): it writes a result, accepts its own result and
rejects any other. The full check against the frozen digest runs in CI's determinism job,
under two hash seeds."""

import json
import subprocess
import sys
from pathlib import Path

from fish_agents.b0 import B0_VERSION
from fish_rules.codec import ACTION_ENCODING
from fish_rules.state import STATE_ENCODING
from fish_rules.version import RULESET_VERSION

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "replay_digest.py"
FROZEN = Path(__file__).parent / "vectors" / "replay_digest_v1.json"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_the_frozen_digest_is_for_this_ruleset_and_these_encodings() -> None:
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    assert frozen["encoding"] == "fish-replay-digest-v1"
    assert frozen["ruleset"] == RULESET_VERSION
    assert frozen["action_encoding"] == ACTION_ENCODING
    assert frozen["state_encoding"] == STATE_ENCODING
    assert frozen["agent"] == B0_VERSION
    assert frozen["games_per_kind"] == 100
    assert list(frozen["kinds"]) == ["playout", "b0", "website"]
    assert all(kind["ended"] == 100 for kind in frozen["kinds"].values())


def test_the_digest_accepts_itself_and_rejects_any_change(tmp_path: Path) -> None:
    out = tmp_path / "digest.json"
    first = run("--games", "2", "--out", str(out))
    assert first.returncode == 0, first.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["games_per_kind"] == 2
    assert "| website |" in first.stdout

    again = run("--games", "2", "--check", str(out))
    assert again.returncode == 0, again.stderr
    assert "Matches digest.json." in again.stdout

    result["kinds"]["b0"]["digest"] = "0" * 64
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(result), encoding="utf-8")
    failed = run("--games", "2", "--check", str(tampered))
    assert failed.returncode == 1
    assert "FAIL the replays differ" in failed.stderr
    assert "b0 games: frozen" in failed.stderr
    assert "website games" not in failed.stderr


def test_the_digest_refuses_to_overwrite_or_play_no_games(tmp_path: Path) -> None:
    existing = tmp_path / "digest.json"
    existing.write_text("{}", encoding="utf-8")
    refused = run("--games", "1", "--out", str(existing))
    assert refused.returncode == 2
    assert "refusing to overwrite" in refused.stderr
    zero = run("--games", "0")
    assert zero.returncode == 2
    assert "at least 1" in zero.stderr

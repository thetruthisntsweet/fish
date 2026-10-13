#!/usr/bin/env bash
# Runs every local check in the same order as CI. Stops at the first failure.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Ruff: format"
uv run ruff format --check .
echo "== Ruff: lint"
uv run ruff check .
echo "== Pyright"
uv run pyright
echo "== Tests + coverage"
uv run pytest --cov --cov-report=term-missing
echo "== Coverage: fish-rules must be 100%"
uv run coverage report --include="*/fish_rules/*" --fail-under=100
echo "All checks passed."
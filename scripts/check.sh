#!/usr/bin/env bash
# Runs every local check in the same order as CI. Stops at the first failure.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env if present, so the database tests run locally (they skip without it).
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

echo "== Ruff: format"
uv run ruff format --check .
echo "== Ruff: lint"
uv run ruff check .
echo "== Pyright"
uv run pyright
echo "== Package boundaries"
uv run lint-imports
echo "== Rule traceability: every rule cited by a test or owed"
uv run python scripts/check_rule_citations.py
echo "== Tests + coverage"
uv run pytest --cov --cov-report=term-missing
echo "== Coverage: fish-rules must be 100%"
uv run coverage report --include="*/fish_rules/*" --fail-under=100
echo "== Coverage: fish-env must be 100%"
uv run coverage report --include="*/fish_env/*" --fail-under=100
echo "== Coverage: fish-agents must be 100%"
uv run coverage report --include="*/fish_agents/*" --fail-under=100
echo "== RNG vectors: independent JavaScript check"
node scripts/verify_rng_vectors.mjs

echo "== Client: install"
npm --prefix client ci --no-audit --no-fund
echo "== Generated types: up to date"
scripts/gen_types.sh --check
echo "== Client: format"
npm --prefix client run format:check
echo "== Client: lint"
npm --prefix client run lint
echo "== Client: types"
npm --prefix client run typecheck
echo "== Client: tests"
npm --prefix client test
echo "== Client: build"
npm --prefix client run build

echo "All checks passed."

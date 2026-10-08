#!/usr/bin/env bash
# Every offline check for the Python side of Toad: tests, lint, format and strict types.
# No network and no paid API calls. Run from anywhere; exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
PY=.venv/bin/python
[[ -x $PY ]] || { echo "No .venv yet: run python3 scripts/setup.py" >&2; exit 1; }

step() { printf '\n== %s\n' "$1"; }
step "server tests"; $PY -m pytest server/tests -q
step "agent CLI tests"; $PY -m pytest agent/tests -q -p no:cacheprovider
step "ruff lint"; $PY -m ruff check server agent scripts
step "ruff format"; $PY -m ruff format --check server agent scripts
step "mypy: server"; $PY -m mypy --strict server/src
step "mypy: agent CLI"; $PY -m mypy --strict agent/toad_agent.py
step "mypy: server scripts"; (cd server/scripts && ../../$PY -m mypy --strict --explicit-package-bases .)
step "agent definition matches the server's tools"; $PY .claude/skills/toad-agent/scripts/check_agent.py
printf '\nAll Toad engine checks passed.\n'

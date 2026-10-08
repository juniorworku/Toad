#!/usr/bin/env bash
# One command for the demo: keeps the Toad engine running on this laptop (restarts it if it
# ever exits) and keeps the USB link to the desk phone alive (re-adds `adb reverse` every few
# seconds, so replugging the cable just works).
# Usage: scripts/start-toad.sh        Stop: Ctrl-C (or kill this script)
# The engine runs from the repo root and reads ./.env (see scripts/setup.py).
set -u
cd "$(dirname "$0")/.." || exit 1
# Android platform tools: adb on PATH, else the repo-local SDK (scripts/android-env.sh),
# else the default macOS SDK location.
if ! command -v adb >/dev/null 2>&1; then
  for dir in "${TOAD_ANDROID_HOME:-$PWD/.tools/android-sdk}/platform-tools" "$HOME/Library/Android/sdk/platform-tools"; do
    if [[ -x $dir/adb ]]; then PATH="$PATH:$dir"; break; fi
  done
fi
export PATH
LOG="${TOAD_LOG:-/tmp/toad-engine.log}"
PYTHON="${TOAD_PYTHON:-.venv/bin/python}"

engine_up() { pgrep -f "uvicorn toad_server.main:app" >/dev/null; }

if [[ ! -x $PYTHON ]]; then
  echo "No Python environment at $PYTHON. Run: python3 scripts/setup.py" >&2
  exit 1
fi
command -v adb >/dev/null 2>&1 || echo "adb not found: the engine will run, but the phone can't be linked over USB." >&2

echo "Toad keeper started. Engine log: $LOG"
while true; do
  if ! engine_up; then
    echo "$(date +%H:%M:%S) starting engine"
    (nohup "$PYTHON" -m uvicorn toad_server.main:app --host 0.0.0.0 --port 8787 --no-access-log >>"$LOG" 2>&1 &)
    sleep 8
  fi
  if adb get-state >/dev/null 2>&1 && ! adb reverse --list 2>/dev/null | grep -q "tcp:8787"; then
    adb reverse tcp:8787 tcp:8787 >/dev/null && echo "$(date +%H:%M:%S) phone linked"
    adb shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
    adb shell am start -n com.toad.companion/.MainActivity >/dev/null 2>&1
  fi
  sleep 3
done

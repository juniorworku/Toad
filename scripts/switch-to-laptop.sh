#!/usr/bin/env bash
# Fallback: run Toad on this laptop again (phone on USB), and stop the cloud engine so only
# one engine runs. Copies the cloud's data back first so nothing added there is lost.
# Needs: adb, fly (or flyctl, logged in), tar. Optional: caffeinate (macOS) or systemd-inhibit
# (Linux) to keep the laptop awake while the engine runs.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v adb >/dev/null 2>&1; then
  for dir in "${TOAD_ANDROID_HOME:-$PWD/.tools/android-sdk}/platform-tools" "$HOME/Library/Android/sdk/platform-tools"; do
    if [[ -x $dir/adb ]]; then PATH="$PATH:$dir"; break; fi
  done
fi
export PATH
FLY="${FLY:-fly}"
command -v "$FLY" >/dev/null 2>&1 || FLY=flyctl
fly() { command "$FLY" "$@"; }
APP=toad-engine

env_value() { grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- | sed -E "s/^[\"']//; s/[\"']$//" || true; }
DATA="${DATA_DIR:-$(env_value DATA_DIR)}"
DATA="${DATA:-data}"
[[ $DATA == /* ]] || DATA="$PWD/$DATA"

LOCK=/tmp/toad-switch.lock
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Another Toad switch is running (or crashed: remove $LOCK). Not starting." >&2
  exit 1
fi
trap 'rmdir "$LOCK"' EXIT

if ! adb get-state >/dev/null 2>&1; then
  echo "The laptop can't see the phone. Plug it in over USB first; nothing was changed." >&2
  exit 1
fi

# Stop any laptop engine first so it can't overwrite the data we're about to bring back.
pkill -f "start-toad.sh" 2>/dev/null || true
pkill -f "uvicorn toad_server.main:app" 2>/dev/null || true
mkdir -p backups && [ -f "$DATA/toad.json" ] && cp "$DATA/toad.json" "backups/toad-$(date +%Y%m%d-%H%M%S).json"

echo "Copying the cloud's data back…"
tgz="/tmp/toad-cloud-$(date +%s).tgz"
if fly ssh console -a "$APP" -C "sh -c 'tar czf $tgz -C /data .'" >/dev/null 2>&1 && fly ssh sftp get "$tgz" "$tgz" -a "$APP" >/dev/null 2>&1; then
  mkdir -p "$DATA" && tar xzf "$tgz" -C "$DATA" && rm -f "$tgz" && rm -f "$DATA"/._* "$DATA"/pages/._*
else
  echo "(couldn't fetch cloud data; keeping the laptop's copy)"
fi

echo "Stopping the cloud engine…"
for id in $(fly machines list -a "$APP" -q 2>/dev/null); do fly machine stop "$id" -a "$APP" >/dev/null || true; done

echo "Pointing the phone at the laptop…"
adb shell "run-as com.toad.companion sed -i 's#<string name=\"serverUrl\">[^<]*</string>#<string name=\"serverUrl\">ws://localhost:8787</string>#' shared_prefs/settings.xml"
# Restart the app so it reads the new address. "am force-stop" is refused while the app is the
# locked kiosk (lock task mode), so kill its process as the app's own user; Android relaunches it.
adb shell "run-as com.toad.companion sh -c 'kill \$(pidof com.toad.companion)'" 2>/dev/null || adb shell am force-stop com.toad.companion
sleep 3

echo "Starting the laptop engine and USB link (keeps running in the background)…"
# Keep the laptop from sleeping while the keeper runs: caffeinate on macOS, systemd-inhibit on
# Linux (only if this session may take the lock), otherwise run it plain.
awake=()
if command -v caffeinate >/dev/null 2>&1; then
  awake=(caffeinate -is)
elif command -v systemd-inhibit >/dev/null 2>&1 &&
  systemd-inhibit --what=sleep:idle --who=Toad --why=check true >/dev/null 2>&1; then
  awake=(systemd-inhibit --what=sleep:idle --who=Toad --why="Toad engine is running")
fi
# setsid-style detach: survives the terminal that ran this script closing.
nohup ${awake[@]+"${awake[@]}"} scripts/start-toad.sh >/tmp/toad-keeper.log 2>&1 </dev/null &
disown
sleep 2
adb shell am start -n com.toad.companion/.MainActivity >/dev/null 2>&1 || true
echo "Done. Keep the phone on USB."

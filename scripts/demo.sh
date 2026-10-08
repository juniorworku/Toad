#!/usr/bin/env bash
# Runs the afternoon-planning demo on a connected phone or emulator through the debug hooks,
# typing the user's lines instead of speaking them, and the handwritten list instead of the
# camera. Needs a debug build of the app (installed already; Gradle isn't used here) connected
# to a running engine (scripts/start-toad.sh, or the cloud).
#   scripts/demo.sh            # uses the first adb device
#   ANDROID_SERIAL=xyz scripts/demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -z ${ADB:-} ]] && ! command -v adb >/dev/null 2>&1; then
  for dir in "${TOAD_ANDROID_HOME:-$PWD/.tools/android-sdk}/platform-tools" "$HOME/Library/Android/sdk/platform-tools"; do
    if [[ -x $dir/adb ]]; then ADB="$dir/adb"; break; fi
  done
fi
ADB="${ADB:-adb}"
PKG=com.toad.companion
OUT=demo/run-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"

# Debug builds log each turn under the "Toad" tag: REPLY <speech> | ERROR <message>, then SPOKE.
spoke_count() { "$ADB" logcat -d -s Toad:I | grep -c "SPOKE" || true; }
cast() { "$ADB" shell "am broadcast -p $PKG -a $PKG.debug.$1 $2" >/dev/null; }

say() {
  local before; before=$(spoke_count)
  echo "YOU:   $1"
  cast SAY "--es text \"$1\""
  for _ in $(seq 1 120); do
    sleep 1
    [[ $(spoke_count) -gt $before ]] && break
  done
  # logcat pads short tags ("Toad    : "), so allow spaces before the colon.
  "$ADB" logcat -d -s Toad:I | grep -E "REPLY|ERROR" | tail -1 | sed -E 's/.*Toad *: (REPLY|ERROR) /TOAD:  /'
  "$ADB" exec-out screencap -p > "$OUT/$2.png"
}

"$ADB" shell am start -n $PKG/.MainActivity >/dev/null
"$ADB" logcat -c
sleep 3
"$ADB" shell mkdir -p /sdcard/Android/data/$PKG/files
"$ADB" push demo/handwritten-todo.jpg /sdcard/Android/data/$PKG/files/todo.jpg >/dev/null
cast PHOTO "--es name todo.jpg"   # the next "look" uses this photo instead of the camera

say "Help me plan my afternoon. Here's my list." 1-plan
say "Okay, let's go with the grant intro." 2-choose
say "Remember that I'm working on this." 3-remember
cast NEW_CONVERSATION ""          # "later": a fresh conversation, only saved memories carry over
say "What was I supposed to focus on?" 4-recall
echo "Screenshots in $OUT"

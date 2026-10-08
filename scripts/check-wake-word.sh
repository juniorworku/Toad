#!/usr/bin/env bash
# Offline sanity check for the "Hey Toad" wake phrase: synthesizes phrases with a local voice,
# runs them through the same Vosk model and grammar the app uses, and prints which ones would
# wake it. Synthetic voices are a smoke test, not a substitute for a real phone mic in a real room.
#
# Needs python3 with venv (vosk is installed into a throwaway venv; on Ubuntu: python3-venv) and
#   macOS: say + afconvert (built in)
#   Linux: espeak-ng (or espeak), plus ffmpeg or sox
set -euo pipefail
cd "$(dirname "$0")/.."
MODEL=android/app/src/main/assets/model-en-us
[[ -d $MODEL ]] || { echo "Run android/scripts/fetch-wake-model.sh first"; exit 1; }

if [[ $(uname -s) == Darwin ]]; then
  TTS=say
  VOICES=(Samantha Daniel Karen Moira Rishi Tessa)
else
  if command -v espeak-ng >/dev/null 2>&1; then TTS=espeak-ng
  elif command -v espeak >/dev/null 2>&1; then TTS=espeak
  else
    echo "No speech synthesizer found. Install one: sudo apt install espeak-ng ffmpeg" >&2
    exit 1
  fi
  if command -v ffmpeg >/dev/null 2>&1; then CONVERT=ffmpeg
  elif command -v sox >/dev/null 2>&1; then CONVERT=sox
  else
    echo "Need ffmpeg or sox to resample to 16 kHz WAV: sudo apt install ffmpeg" >&2
    exit 1
  fi
  VOICES=(en-us en-us+m3 en-us+f3 en-gb en-gb-scotland en-gb-x-rp+f2)
fi

# Writes the phrase as 16 kHz mono 16-bit WAV; fails (and the clip is skipped) if the voice is missing.
synth() { # voice phrase out.wav
  local raw="${3%.wav}.raw"
  if [[ $TTS == say ]]; then
    say -v "$1" -o "$raw.aiff" "$2" 2>/dev/null || return 1
    afconvert -f WAVE -d LEI16@16000 -c 1 "$raw.aiff" "$3"
  else
    "$TTS" -v "$1" -w "$raw.wav" "$2" >/dev/null 2>&1 || return 1
    if [[ $CONVERT == ffmpeg ]]; then
      ffmpeg -v error -y -i "$raw.wav" -ar 16000 -ac 1 -c:a pcm_s16le "$3"
    else
      sox "$raw.wav" -r 16000 -c 1 -b 16 "$3"
    fi
  fi
}

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
{ python3 -m venv "$WORK/venv" && "$WORK/venv/bin/pip" install -q vosk 2>/dev/null; } ||
  { echo "Couldn't create a venv with vosk (needs python3-venv and network access)." >&2; exit 1; }
i=0
for voice in "${VOICES[@]}"; do
  for phrase in "Hey Toad" "Hey, Toad!" "Hey book" "Hey look" "Today" "Thank you" "Hey, do you" "Hey Buddy" "Help me plan my afternoon" "The desk is clean" "Hey dude" "Hey road"; do
    i=$((i+1))
    synth "$voice" "$phrase" "$WORK/s$i.wav" || continue
    echo "$WORK/s$i.wav|$voice|$phrase"
  done
done > "$WORK/list.txt"
[[ -s $WORK/list.txt ]] || { echo "No clips were synthesized (no matching voices for $TTS)." >&2; exit 1; }
"$WORK/venv/bin/python" - "$MODEL" "$WORK/list.txt" 2>/dev/null <<'PY'
import json, sys, wave
from vosk import Model, KaldiRecognizer, SetLogLevel
SetLogLevel(-1)
model = Model(sys.argv[1])
# Keep in sync with WakeWord.kt (VARIANTS + DECOYS + "[unk]").
VARIANTS = ["hey toad"]
DECOYS = ["hey", "desk", "hey book", "hey look", "hey just", "hey this", "school", "cool", "discuss", "hey there",
          "you", "hey do you", "thank you", "hey buddy", "the desk", "desktop", "hey dude"]
grammar = json.dumps(VARIANTS + DECOYS + ["[unk]"])
def heard(js, field):
    s = json.loads(js).get(field, "").strip()
    return any(s == v or s.startswith(v + " ") or s.endswith(" " + v) or (" " + v + " ") in s for v in VARIANTS)
should = wrong = 0
for line in open(sys.argv[2]):
    path, voice, text = line.rstrip("\n").split("|")
    wf = wave.open(path, "rb"); rec = KaldiRecognizer(model, 16000, grammar); hit = False
    while (data := wf.readframes(1600)):
        hit |= heard(rec.Result(), "text") if rec.AcceptWaveform(data) else heard(rec.PartialResult(), "partial")
    hit |= heard(rec.FinalResult(), "text")
    want = "toad" in text.lower()
    should += want; wrong += hit != want
    print(f"{'WAKE ' if hit else 'quiet'}  {voice:15} {text}{'   <-- WRONG' if hit != want else ''}")
print(f"\n{wrong} wrong out of {sum(1 for _ in open(sys.argv[2]))} clips ({should} should wake)")
PY

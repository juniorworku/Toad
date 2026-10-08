# Operating scripts

Run everything from the repository root. Shell scripts work on Linux and macOS. Each one finds `adb` on `PATH`, then in the repo-local SDK (`.tools/android-sdk/platform-tools`, see `android-env.sh`), then in `~/Library/Android/sdk/platform-tools` on macOS. The engine reads `./.env` from the repo root (`DEVICE_TOKEN`, `LIVE_VOICE`, `DATA_DIR`, …).

Python provider smoke tools (fake device, live provider checks) live in [`server/scripts/`](../server/scripts/). Any tool there that makes a real call or writes to an external account says so.

## Setup and checks

| Script | What it does | Needs |
| --- | --- | --- |
| `python3 scripts/setup.py` | Creates `.venv`, installs `server/requirements.lock` and the server (editable), and creates a private `.env` with a random `DEVICE_TOKEN`. Keeps an existing `.env`. `--check` reports prerequisites without changing anything. | Python 3.12+ |
| `.venv/bin/python scripts/smoke_local.py` | Starts a temporary engine in fake mode on a free port and checks `/healthz`, the authenticated device WebSocket, the transcript and the 24 kHz PCM reply. No AI API calls. | `.venv` |
| `source scripts/android-env.sh` | Points `JAVA_HOME`, `ANDROID_HOME`, `GRADLE_USER_HOME` and `PATH` at the repo-local toolchain in `.tools/`. Source it; don't run it. | `.tools/` |
| `scripts/validate-android.sh` | Runs unit tests, the debug build and lint in `android/`, then lists adb devices. | `.tools/` JDK 17 and SDK |
| `scripts/check-wake-word.sh` | Offline check of the "Hey Toad" wake phrase. It synthesizes "Hey Toad" and near-misses in several voices, runs them through the Vosk model and the same grammar as `WakeWord.kt`, and prints which clips would wake the app. Synthetic voices are only a smoke test, not a real room mic. Keep its `VARIANTS`/`DECOYS` in sync with `WakeWord.kt`. | Model from `android/scripts/fetch-wake-model.sh`; `python3` with venv (vosk goes in a throwaway venv, so this needs network); Linux: `espeak-ng` (or `espeak`) plus `ffmpeg` or `sox`; macOS: `say`, `afconvert` |

## Running the desk

| Script | What it does | Needs |
| --- | --- | --- |
| `scripts/start-toad.sh` | Keeps the engine running on this laptop (`uvicorn toad_server.main:app` on port 8787, restarted if it exits, log in `/tmp/toad-engine.log` or `$TOAD_LOG`). Also keeps the USB link to the phone alive by re-adding `adb reverse tcp:8787` every few seconds and bringing the app to the front. Stop it with Ctrl-C. | `.venv`, `adb` |
| `scripts/switch-to-cloud.sh` | Moves Toad to Fly (`toad-engine`). In order: checks the phone has internet; stops the laptop engine; deploys; copies the data directory up, with the state going in as `toad.incoming.json` so it's swapped in on restart; points the phone at `wss://toad-engine.fly.dev`. A local backup goes to `backups/` first. | `adb`, `fly`/`flyctl` (logged in), `curl`, `tar` |
| `scripts/switch-to-laptop.sh` | Fallback. Stops the laptop engine, backs up the local state, copies the cloud data back, stops the Fly machine, points the phone at `ws://localhost:8787` and starts `start-toad.sh` in the background (log `/tmp/toad-keeper.log`). While it runs, the laptop is kept awake with `caffeinate` on macOS or `systemd-inhibit` on Linux, when either is available. | `adb`, `fly`/`flyctl`, `tar` |
| `scripts/demo.sh` | Runs the afternoon-planning demo on a phone or emulator through the debug broadcast hooks (`com.toad.companion.debug.*`). It types the lines instead of speaking them and pushes `demo/handwritten-todo.jpg` in place of the camera. Prints each reply (logcat tag `Toad`) and saves screenshots in `demo/run-*/`. Use `ANDROID_SERIAL=…` to pick a device. | Debug build installed and connected to an engine; `adb` |

Only one engine may run at a time. Both switch scripts take the lock `/tmp/toad-switch.lock`, so two switches can't run at once. If a switch crashed, remove the lock by hand. To restart the app, the switch scripts kill its process as the app's own user (`run-as`), because `am force-stop` is refused while the app is the locked kiosk. That needs a debuggable build.

## Deployment

`Dockerfile`, `.dockerignore` and `fly.toml` are at the repo root, because the image also needs `agent/toad-agent.json`. Deploy with `fly deploy --ha=false`. Keep it to one Machine with the `toad_data` volume at `/data`. Keys are Fly secrets and never go into the image.

## Avatar

| Script | What it does | Needs |
| --- | --- | --- |
| `LP_DIR=~/LivePortrait scripts/make-avatar.sh photo.jpg [crop]` | Renders one photo into looping idle, listening, talking and thinking clips plus `poster.jpg`, all in `android/app/src/main/assets/avatar/`. Rendering is local with LivePortrait. `crop` is ffmpeg `w:h:x:y` on the 1024² output (default `720:720:250:70`). | A LivePortrait checkout with `.venv` and weights; `ffmpeg` with libx264. InsightFace (used by LivePortrait) is licensed for non-commercial use only. |

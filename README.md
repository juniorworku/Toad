# Toad

A Python-server and Kotlin Android rebuild of the Desku AI desk companion, with a new animated moss-green toad.

## Implemented

- Kotlin/Compose application migrated and rebranded as `com.toad.companion`, retaining local Claude mode, hardware, screens, kiosk behavior and JVM tests.
- Native toad drawing and launcher icon; six expressions, blinking, eye-follow and voice-driven mouth animation.
- Python FastAPI engine: authenticated device WebSocket, ordered state/JSON/binary transport, microphone mute, stop/restart, replacement/reconnect cleanup, camera response correlation, memory deletion and presence tracking.
- Atomic JSON store for memories, focus/history, todos, check-ins, hosted-agent references and Today page ID; server-side memory consent policy.
- GPT-Live adapter, saved-agent SDK integration, persisted pages and desk tools; explicit diagnostic fake and local smoke script.

Python now includes opt-in GPT-Live speech transport and a saved-agent reasoning adapter with tool execution, session recovery, camera input, memory consent, tasks, and Today/generated pages. Fake mode remains the default: microphone audio is consumed without recognition; typed input produces a diagnostic transcript and tone. Live account access and Android device behavior remain unverified. Scheduled check-ins, voice reconnection and idle-close policies are implemented. Dashboard, presence welcomes, apps and phone calls remain pending.

## Run the Python engine

From the repository root, run `python3 scripts/setup.py` to install the locked Python environment and create a private `.env` with a random device token. Existing `.env` files are preserved. Use `python3 scripts/setup.py --check` to inspect prerequisites.

Manual setup:

```bash
.venv/bin/python -m pip install -r server/requirements.lock
.venv/bin/python -m pip install --no-deps -e './server[dev]'
export DEVICE_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PROVIDER_MODE=fake
.venv/bin/python -m uvicorn toad_server.main:app --host 127.0.0.1 --port 8787 --no-access-log
```

For setup from scratch, first run `python3 -m venv .venv`. Reuse the same newly generated device token in Android settings; generating a new value every start requires updating the phone. `.env` can supply configuration instead; keep it out of Git. Disable access logs because the compatibility WebSocket URL carries its token in the query string. No original secrets/account identifiers were imported.

```bash
.venv/bin/python -m pytest server/tests -q
.venv/bin/python -m ruff check server/src server/tests scripts/smoke_local.py
.venv/bin/python -m mypy --strict server/src
.venv/bin/python scripts/smoke_local.py
```

For live mode, set `PROVIDER_MODE=openai`, `OPENAI_API_KEY`, and optionally `OPENAI_PROJECT` in your private `.env`. The server creates or updates the saved agent and persists its session reference. This mode makes paid API requests when enabled. See `server/.env.example` for the documented endpoint/model defaults.

## Android

See [Android setup](android/README.md). Build from `android/` with JDK 17 and Android SDK 36. Connect a USB phone with `adb reverse tcp:8787 tcp:8787`, then set the engine address to `ws://127.0.0.1:8787` and enter the token. Leave the engine address blank for the original phone-only Claude behavior.

Android validation passes: debug APK built, 13 JVM tests passed, and lint has zero errors with 33 remaining warnings. Java and adb are available through `source scripts/android-env.sh`; rerun with `scripts/validate-android.sh`. Physical-device testing is deferred. See [validation report](docs/ANDROID_VALIDATION.md).

## Rebuild references

- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Current status](docs/STATUS.md)
- [Device protocol](docs/DEVICE_PROTOCOL.md)
- [Provider feasibility](docs/PROVIDER_COMPATIBILITY.md)
- [Baseline review](docs/BASELINE_REVIEW.md)
- [Avatar](design/avatar/README.md)

Baseline: Desku commit `2aea122`. MIT attribution is preserved in [LICENSE](LICENSE). GitHub target: `juniorworku/Toad`. No provider provisioning or deployment has been performed.

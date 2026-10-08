# Nook

A Python-server and Kotlin Android rebuild of the Desku AI desk companion, with a new animated amber owl.

## Implemented

- Kotlin/Compose application migrated and rebranded as `com.nook.companion`, retaining local Claude mode, hardware, screens, kiosk behavior and JVM tests.
- Native owl drawing and launcher icon; six expressions, blinking, eye-follow and voice-driven beak animation.
- Python FastAPI engine: authenticated device WebSocket, ordered state/JSON/binary transport, microphone mute, stop/restart, replacement/reconnect cleanup, camera response correlation, memory deletion and presence tracking.
- Atomic JSON store for memories, focus/history, todos, check-ins, hosted-agent references and Today page ID; server-side memory consent policy.
- Explicit diagnostic fake voice adapter, regression tests and a real local HTTP/WebSocket smoke script.

The Python engine **does not yet provide AI speech**. Fake mode consumes microphone audio without transcribing it; typed `say` returns a labeled transcript and quiet diagnostic tone. The Android source has not been compiled or tested on a device yet. Model tools, live-provider adapters, scheduler, pages, dashboard, apps and calls remain pending.

## Run the Python engine

From the repository root:

```bash
.venv/bin/python -m pip install -r server/requirements.lock
.venv/bin/python -m pip install --no-deps -e './server[dev]'
export DEVICE_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PROVIDER_MODE=fake
.venv/bin/python -m uvicorn nook_server.main:app --host 127.0.0.1 --port 8787 --no-access-log
```

For setup from scratch, first run `python3 -m venv .venv`. Reuse the same newly generated device token in Android settings; generating a new value every start requires updating the phone. `.env` can supply configuration instead; keep it out of Git. Disable access logs because the compatibility WebSocket URL carries its token in the query string. No original secrets/account identifiers were imported.

```bash
.venv/bin/python -m pytest server/tests -q
.venv/bin/python -m ruff check server/src server/tests scripts/smoke_local.py
.venv/bin/python -m mypy --strict server/src
.venv/bin/python scripts/smoke_local.py
```

## Android

See [Android setup](android/README.md). Build from `android/` with JDK 17 and Android SDK 36. Connect a USB phone with `adb reverse tcp:8787 tcp:8787`, then set the engine address to `ws://127.0.0.1:8787` and enter the token. Leave the engine address blank for the original phone-only Claude behavior.

## Rebuild references

- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Current status](docs/STATUS.md)
- [Device protocol](docs/DEVICE_PROTOCOL.md)
- [Provider feasibility](docs/PROVIDER_COMPATIBILITY.md)
- [Baseline review](docs/BASELINE_REVIEW.md)
- [Avatar](design/avatar/README.md)

Baseline: Desku commit `2aea122`. MIT attribution is preserved in [LICENSE](LICENSE). No commits, remote repository, provider provisioning or deployment have been created.
# Toad
# Toad

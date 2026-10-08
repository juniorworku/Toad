# Toad

AI desk companion: a Kotlin/Compose Android app (`android/`, package `com.toad.companion`) and a Python FastAPI engine (`server/src/toad_server/`). What each feature does and where it's tested: [docs/FEATURES.md](docs/FEATURES.md).

## Skills

Use the repo skills in `.claude/skills/`: `toad-engine` (run/test/debug the engine), `toad-agent` (agent definition and tools), `toad-android` (phone app), `toad-apps` (Composio in Python), `toad-pages` (desk pages and the UI kit), `composio` (vendored upstream; don't edit, it's hash-locked in `skills-lock.json`).

## Commands (from the repo root)

```bash
.claude/skills/toad-engine/scripts/check.sh                      # all Python tests, lint, format, mypy, agent/tool parity
source scripts/android-env.sh && scripts/validate-android.sh     # Android JVM tests, APK, lint
.venv/bin/python -m uvicorn toad_server.main:app --port 8787 --no-access-log   # engine (reads ./.env)
```

Call Python tools as `.venv/bin/python -m <tool>`. Ruff line length is 100 (`server/pyproject.toml`, `ruff.toml`); mypy runs `--strict`.

## Rules

- **Paid and outward actions need the user's go-ahead:** `PROVIDER_MODE=openai`, `server/scripts/smoke_*.py`, `fake_phone.py` against a live engine, `agent/toad_agent.py` commands, `call_me.py`, `connect_app.py`, Fly deploys, installing on a phone, `dpm set-device-owner`.
- **Never print secrets.** `.env` holds `DEVICE_TOKEN` and provider keys; check whether a key is set with `grep -c '^KEY=.' .env`, not by reading it.
- **The protocol is shared with `EngineLink.kt`.** JSON keys are camelCase on the wire; `server/tests/test_protocol.py` compares the engine against the Kotlin source. Change both sides together.
- **Consent rules live in code:** memory saves (`memory_policy.py`) and calls to other people (`tools.allows_call`) need the user's own words. Keep them enforced server-side, not only in prompts.
- **Agent tools:** a function tool in `agent/toad-agent.json` must be implemented in `tools.py`; `check_agent.py` enforces it.
- **Tests use fakes** (`server/tests/fakes.py`: `FakeLive`, `FakeBrain`, `FakeDevice`, `Rig` with a controlled clock). New engine behavior gets a test there; nothing in the suite may call a real service.
- Don't commit `.env`, `data/`, `android/local.properties`, `.tools/` or `.venv/`.

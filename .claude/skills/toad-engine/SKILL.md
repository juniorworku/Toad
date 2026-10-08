---
name: toad-engine
description: Run, test and debug Toad's Python engine (the FastAPI server in server/ that the desk phone connects to). Use when starting the engine, running the server or agent test suites, checking lint and types, reading the device WebSocket protocol, inspecting /api/overview, or diagnosing why the phone, voice session, brain, check-ins or away calls misbehave.
---

# Toad engine

Toad is a desk-companion app: a Kotlin Android phone app (`android/`) plus a Python engine (`server/`). The phone streams mic audio to the engine; the engine runs a GPT-Live voice session, hands delegated work to a saved Agents API agent ("Toad", `agent/toad-agent.json`), runs that agent's tools, and speaks first when check-ins come due.

Always work from the repository root and call tools through `.venv/bin/python -m …` (console scripts in `.venv/bin` may carry a stale path).

## Check everything (no network, no paid calls)

```bash
.claude/skills/toad-engine/scripts/check.sh
```

Runs the server and agent test suites, Ruff lint and format checks, and strict mypy over the server, agent CLI and server scripts. Run it after any change to `server/`, `agent/` or `scripts/`, and before saying a change works.

## Start the engine

```bash
python3 scripts/setup.py            # once: venv, locked deps, private .env with a new DEVICE_TOKEN
.venv/bin/python -m uvicorn toad_server.main:app --host 0.0.0.0 --port 8787 --no-access-log
```

Settings come from `./.env` (template: `server/.env.example`). `PROVIDER_MODE=fake` (the default) needs no keys: taps get a labeled diagnostic transcript and a test tone, mic audio is counted but not recognized. `PROVIDER_MODE=openai` with `OPENAI_API_KEY` uses GPT-Live and the saved agent, which **costs money per minute and per turn**: ask before starting it. `scripts/start-toad.sh` keeps the engine and the USB link alive for a demo.

Then open `http://localhost:8787/agent.html` (dashboard; the token is filled in automatically on localhost) or `http://localhost:8787/` (browser test client).

```bash
.claude/skills/toad-engine/scripts/overview.sh [http://localhost:8787]
```

prints a short summary of `/api/overview` (device, voice, brain, focus, check-ins, memories) using the token from `.env` without echoing it.

## Where things live

| Module (`server/src/toad_server/`) | Job |
| --- | --- |
| `main.py` | routes: `/device` socket, `/api/overview`, `/api/apps/connect`, `/p/<id>`, `/agent(.html)`, `/`; provider wiring; token redaction in logs |
| `desk.py` | the engine: one phone, voice session lifecycle, delegations → brain, check-ins, presence welcome-back, Today screen, away calls, desk controls |
| `tools.py` | the 15 desk tools the agent calls, plus Composio pass-through |
| `brain.py` | saved-agent sync, persistent session, serialized turns, tool results, session recovery |
| `live.py`, `prompt.py`, `transcript.py` | GPT-Live client, voice instructions, transcript folding |
| `store.py`, `pages.py`, `today.py` | atomic JSON state, sandboxed pages, Today screen |
| `apps.py`, `phone.py` | Composio apps, AgentPhone calls |
| `memory_policy.py` | "only save when asked", enforced in code |

Tests live in `server/tests/`; `fakes.py` has the scripted voice (`FakeLive`), brain (`FakeBrain`), phone (`FakeDevice`) and a controlled clock (`Rig`). Main suites: `test_engine.py` (the desk), `test_away.py` (calls), `test_apps.py` (Composio), `test_companion.py` (reminders, focus time, briefings, breaks, app-change consent), `test_protocol.py` (against the Kotlin source). New behavior gets a test in the same style.

## Device protocol (must stay compatible with `android/…/engine/EngineLink.kt`)

`ws://HOST:8787/device?token=DEVICE_TOKEN`. Audio both ways is binary raw mono PCM16 LE at 24 kHz (~100 ms / 4,800-byte frames). JSON keys are camelCase on the wire; never convert them to snake_case.

- Phone → engine: `start`, `stop`, `mute`, `unmute`, `camera{enabled}`, `photo{requestId,image}`, `photo_error{requestId,reason}`, `forget{id}`, `forget_all`, `say{text}` (screen tap), `presence{present}`.
- Engine → phone: `state{live,muted,camera,thinking}`, `transcript{role,delta}`, `desk{memories,focus,checkins}`, `capture{requestId,countdownSeconds}`, `checkin{about}`, `link{url,label}`, `calling{about}`, `control{action}`, `page{id,title,url}`, `interrupt`, `error{message}`.

Messages the brain sees start with `[Heard]` (speech), `[Tapped on the desk screen]` (button) or `[Desk event]` (the app). The memory and call consent rules read the user's own words only.

## Debugging checklist

- Phone connects then drops: wrong token (HTTP 401 on upgrade), or a second device replaced it (close code 4000).
- No reply after speaking: a delegation must always be answered; look for `desk: brain failed` in the engine log (the user hears the "Sorry…" line).
- Check-in never fires: it waits for the phone unless away calls are configured; `get_desk_status` and the dashboard show pending check-ins.
- Uvicorn logs the socket path; `main.RedactToken` hides `token=`. Never paste raw logs with a token into chat.

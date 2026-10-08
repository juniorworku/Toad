# Toad engine (Python)

This is the backend that makes the desk phone a proactive buddy. It is a Python (FastAPI) rebuild of Desku's Node/TypeScript engine with the same architecture, device protocol and behavior:

- **GPT-Live** (`gpt-live-1`) is Toad's ears and voice.
- A saved **Agents API** agent, also called "Toad" (`../agent/toad-agent.json`), is its brain.
- This server sits between them, runs the tools, and starts conversations when check-ins come due.

```
 phone (mic, speaker, camera) ──WS /device──► Desk engine ──WS──► GPT-Live (voice, full duplex)
                                                   │                   │ session.delegation.created
                                                   │ ◄─────────────────┘
                                                   ├──► Agents API session "Toad" (thinks, picks tools)
                                                   │       └─ function calls ──► tools here: focus, check-ins,
                                                   │                             memory, to-dos, pages, camera, calls
                                                   └──► session.commentary.append ──► GPT-Live says the answer
 scheduler ── check-in due ──► open voice session ──► brain writes the check-in ──► Toad speaks first
```

`PROVIDER_MODE=fake` (the default) swaps both providers for a labeled diagnostic stand-in, so the engine, the phone app and the browser client can be exercised with no keys and no cost. Typed input comes back as `[Fake provider] Received: …` with a test tone; it is not AI.

## Why it's split this way

- **Voice sessions are short.** GPT-Live is billed per minute while open. With `ALWAYS_LISTEN=0` the engine opens a session on Talk, the wake phrase or a due check-in, and closes it after `IDLE_CLOSE_SECONDS` of quiet. With `ALWAYS_LISTEN=1` (default) it keeps one open while the phone is connected and reopens a dropped one at most every 10 s; Stop pauses that until Talk.
- **The brain persists.** One Agents API session, created from the saved agent, holds the whole conversation across voice sessions. Its ID is stored in `DATA_DIR/toad.json`. When `agent/toad-agent.json` changes, the engine updates the saved agent on startup and starts a fresh session (sessions copy the agent config when created). A deleted or failed session is replaced once, automatically.
- **Client delegation.** GPT-Live's delegation event carries no text, so the engine keeps the transcript and sends the brain `[Heard] <what the user said since the last delegation>` plus recent context. Mid-turn text from the brain is spoken only when the user has to act (the camera); otherwise it goes to GPT-Live as silent context. Every delegation is answered, with an apology if the brain fails.
- **The memory rule is enforced in code.** `save_memory` is refused unless the user's own words ask for it ("remember…", "don't forget…") or are a yes to Toad's offer (`memory_policy.py`). Calling anyone other than the user needs the same kind of consent (`tools.allows_call`).
- **Toad can start the conversation.** Due check-ins open a voice session, the brain writes the check-in and GPT-Live speaks it unprompted. Check-ins that come due while the phone is offline are delivered when it reconnects (or turn into a phone call, below).
- **It notices you.** The phone's on-device face detection sends `presence`. Arriving puts the Today screen up; coming back after 10+ minutes away with a focus set gets a welcome-back question (at most every 30 minutes, never in quiet hours).

## Setup

You need Python 3.12+. From the repository root:

```bash
python3 scripts/setup.py          # .venv, locked dependencies, private .env with a new DEVICE_TOKEN
.venv/bin/python -m uvicorn toad_server.main:app --host 0.0.0.0 --port 8787 --no-access-log
```

Settings are read from `./.env` (template with every option: [`.env.example`](.env.example)). For the real AI set `PROVIDER_MODE=openai` and `OPENAI_API_KEY` (with `api.agents.read`, `api.agents.write` and `api.responses.write`, on a paid tier). `TOAD_AGENT_ID` reuses an existing saved agent; empty creates one.

Then open `http://localhost:8787` for the browser test client (paste the token unless you're on localhost, press **Connect**, then **Talk**; use headphones) or `http://localhost:8787/agent` for the agent page.

## Agent page (`/agent`)

A read-only page showing what Toad is connected to and what it keeps, refreshed every 5 seconds: desk phone, voice, brain, apps (one chip per Composio connection), phone calls and web search; current and recent focus and upcoming check-ins; memories; the tools the agent can call; pages Toad made (open or delete); agent and session IDs and the instructions. It reads `GET /api/overview`, which needs `Authorization: Bearer DEVICE_TOKEN` because memories and focus are personal. Opened on the same computer (localhost), the page fills in the token itself.

## Pages Toad makes (`/p/<id>`)

For answers better seen than heard (a schedule, tickets, a comparison), Toad writes a self-contained page; the engine stores it in `DATA_DIR/pages/`, serves it at `/p/<id>` with the Toad UI kit injected, and the phone opens it. The Today screen (to-dos, focus with its check-in countdown, memories) is built the same way, straight from the store.

- **The link is the key.** IDs are 128 random bits, so the phone opens pages without the token. Deleting needs it (`DELETE /api/pages/<id>` → 204, or 404).
- **Sandboxed.** Pages often contain text from emails and the web, so they're served with a `sandbox` CSP and no `allow-same-origin`: scripts run but can't read the token, call the engine, fetch anything or submit forms. Scripts and styles may come from jsDelivr or cdnjs, fonts from Google Fonts, images only as `data:` URIs.
- **Limits.** 512 KB per page, the newest 50 are kept.

## Your apps (Composio)

With `COMPOSIO_API_KEY` (a Platform project key, `ak_…`) set, the engine opens one Composio session for the owner (`COMPOSIO_USER_ID`, default `toad-owner`) and adds its meta tools to the agent: `COMPOSIO_SEARCH_TOOLS`, `COMPOSIO_GET_TOOL_SCHEMAS`, `COMPOSIO_MULTI_EXECUTE_TOOL`, `COMPOSIO_MANAGE_CONNECTIONS` (the remote sandbox tools are left out). The engine runs them; the key never leaves the server. When an app isn't connected, its Connect Link appears on the desk screen as a `link` message; open it, approve, ask again. You can also connect from the agent page or `scripts/connect_app.py`. Before sending, posting, creating, changing or deleting anything, Toad says what it will do and waits for a yes (in the agent instructions; not enforced in code).

## Calling you when you're away (AgentPhone)

With `AGENTPHONE_API_KEY`, `AGENTPHONE_NUMBER` (Toad's own number) and `OWNER_PHONE` set:

- **When it calls:** the phone is offline when a check-in comes due (not in the first 2 minutes after startup); or Toad asked the check-in and heard no reply for `AWAY_CALL_AFTER_SECONDS` (default 60); or the camera hasn't seen you for 2 minutes. Anything you say at the desk cancels it. Never during `QUIET_HOURS` (default `22-8`, local) unless you asked; one call at a time.
- **The call** runs on AgentPhone's hosted voice AI with the check-in, the time and your memories. Afterwards the transcript goes to the brain, which can update the focus or schedule a check-in; it saves a memory only if you asked on the call.
- **On request** (`call_phone`): "Call me" rings your phone. "Call my friend at +1 …" (US/Canada only) needs the number read back and your yes; the callee hears that it's an AI calling for you, and Toad tells you at the desk how it went.

## Device protocol (`ws://HOST:8787/device?token=DEVICE_TOKEN`)

All audio is raw mono PCM16, little-endian, 24 kHz, sent as binary frames in both directions (about 100 ms / 4,800 bytes per frame). JSON keys are camelCase.

| Phone → engine | |
|---|---|
| `{type:"start"}` / `{type:"stop"}` | Open the voice session (Talk or wake word), or end it (pauses always-listening) |
| `{type:"mute"}` / `{type:"unmute"}` | Mute the mic: the engine drops audio and tells GPT-Live |
| `{type:"camera", enabled}` | Camera privacy switch: when off, the camera tool fails honestly |
| `{type:"photo", requestId, image}` / `{type:"photo_error", requestId, reason}` | Reply to `capture` (base64 JPEG) |
| `{type:"forget", id}` / `{type:"forget_all"}` | Delete memories from the screen |
| `{type:"say", text}` | A tap on a screen button; the brain answers it out loud |
| `{type:"presence", present}` | The always-on camera sees (or stops seeing) someone |

| Engine → phone | |
|---|---|
| `{type:"state", live, muted, camera, thinking}` | `live` is `idle`, `connecting` or `open` |
| `{type:"transcript", role, delta}` | Live captions for both sides |
| `{type:"desk", memories, focus, checkins}` | On connect and on every change |
| `{type:"capture", requestId, countdownSeconds}` | Take one photo (countdown is 0: the camera is always on) |
| `{type:"checkin", about}` | A check-in is starting: wake the screen |
| `{type:"page", id, title, url}` | Open `url` (relative, versioned with `?v=`) |
| `{type:"link", url, label}` | An app Connect Link to open |
| `{type:"calling", about}` | Toad is phoning the user or someone for them |
| `{type:"control", action}` | `camera_on`, `camera_off`, `close_camera`, `mute_mic`, `show_memories`, `hide_memories`, `end_conversation` |
| `{type:"interrupt"}` | Drop queued speech (barge-in, or the session stopped) |
| `{type:"error", message}` | Shown to the user |

Only one phone is connected at a time; a newer connection replaces the older one (close code 4000). A wrong token gets HTTP 401 on the upgrade. Uvicorn's log of the socket path has the token redacted.

## Running it elsewhere

- **Always on, laptop:** `scripts/start-toad.sh` restarts the engine if it exits and keeps `adb reverse` alive for a USB phone.
- **Fly.io:** `Dockerfile`, `.dockerignore` and `fly.toml` are at the repo root (the image also needs `agent/toad-agent.json`). One Machine with a volume at `/data`, keys as Fly secrets: `fly deploy --ha=false`. `scripts/switch-to-cloud.sh` and `scripts/switch-to-laptop.sh` move the state and the phone between the two. Run one engine at a time.
- **Phone without internet:** `.venv/bin/python server/scripts/usb_bridge.py https://your-engine` plus `adb reverse tcp:8787 tcp:8787`; the phone keeps `ws://127.0.0.1:8787`.

## Code map

| `src/toad_server/` | |
|---|---|
| `main.py` | HTTP routes, device socket, provider wiring, token redaction |
| `desk.py` | the engine: device, voice lifecycle, delegations, check-ins, presence, calls, controls |
| `tools.py` | the 12 desk tools and the Composio pass-through |
| `brain.py` | saved agent sync, persistent session, streamed tool calls, recovery |
| `live.py`, `prompt.py`, `transcript.py`, `providers.py` | GPT-Live client, voice instructions, transcript folding, the fake provider |
| `store.py`, `pages.py`, `today.py`, `assets/` | JSON state, pages, the Today screen, the UI kit |
| `apps.py`, `phone.py`, `memory_policy.py` | Composio, AgentPhone, the memory rule |
| `public/` | the browser test client and the agent page |

## Tests and checks

```bash
.claude/skills/toad-engine/scripts/check.sh
```

runs everything offline: the server suite (`tests/`, 110 tests, with a fake GPT-Live, a fake brain, a fake phone, a loopback WebSocket provider, mock AgentPhone and Composio, and the real OpenAI SDK against a mock HTTP/SSE transport), the agent CLI suite, Ruff, strict mypy, and a check that every function tool in `agent/toad-agent.json` is implemented here. The ported Desku suites are `test_engine.py`, `test_away.py` and `test_apps.py`. They cover:

- audio flow, voice turns, delegation answered with the right ID, empty delegations, brain failure
- refusing memories the user didn't ask for
- the camera round trip, and the camera switched off
- proactive check-ins, late check-ins, holding them while the phone is offline
- mute, idle close, always-listening reopen, Stop pausing it, barge-in
- desk controls, pages, to-dos and the Today screen, presence welcome-back
- away calls: offline desk, no reply, a reply cancelling the call, quiet hours, camera absence, startup grace, call consent across turns, the call transcript reaching the brain, AgentPhone errors
- apps: meta tools routed through the session, Connect Links reaching the screen, Composio errors with their log IDs
- HTTP: agent page, overview auth and contents, apps connect, page CSP and deletion

Live checks need `.env` filled in and cost money; each says what it does:

| `scripts/` | |
|---|---|
| `smoke_brain.py` | the brain alone against the real Agents API, with the demo photo as the camera |
| `smoke_apps.py` | a real Composio session plus the brain ("what's on my calendar?") |
| `smoke_page.py` | asks the brain for a page and writes it with the kit for a browser |
| `fake_phone.py` | a stand-in phone against a running engine: speaks lines (`say`, `espeak-ng` or `--wav`), answers camera requests, saves Toad's audio |
| `call_me.py`, `connect_app.py` | one real AgentPhone call; connect one app |
| `usb_bridge.py` | relays a USB phone to a remote engine |

The step-by-step live acceptance run (providers, the real phone, apps, calls) is in [docs/LIVE_TESTING_STEPS.md](../docs/LIVE_TESTING_STEPS.md).

## Verified, and not yet

Verified offline: everything above, by the test suites and a local run of the engine in fake mode with the USB bridge and `fake_phone.py` in front of it (HTTP routes, token handling, device socket through the bridge, audio resampling, tap round trip).

Not verified yet: any live provider call (no keys were used), the real phone against this Python engine, apps, phone calls, and the deployment. Desku's own live runs (GPT-Live voice in and out, the camera tool reading the demo list, a check-in spoken first, the memory rule, context carried across voice sessions) were against the TypeScript engine; this engine sends the same events, but that still has to be confirmed live.

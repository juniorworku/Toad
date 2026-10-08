# Toad

> Your old phone already has eyes, ears and a voice. Toad gives it a brain and a useful job.

Toad turns a spare Android phone (Android 8.0+) into a desk companion: a moss-green toad with raised eyes and a wide smile, sitting on a stand next to you. You talk to it, show it things through the camera, and ask it to remember what matters. It helps you pick one thing to work on, keeps your to-do list and reminders, checks in when the focus timer ends, briefs you on your day when you sit down, and suggests a break when you've been at it too long. If you're away from the desk, it can phone you.

Toad has two parts: a Kotlin/Compose **Android app** that is the eyes, ears, voice and face, and a **Python engine** (FastAPI) that runs the conversation, the brain's tools, reminders and check-ins, and the integrations.

## How it fits together

```
 Android phone (android/)                Python engine (server/)                 Providers
 ┌──────────────────────┐  WS /device   ┌──────────────────────────┐  WS   ┌──────────────────────┐
 │ mic · speaker · cam  │ ◄───────────► │ desk: voice, delegation, │ ◄───► │ GPT-Live (voice)     │
 │ toad face · screens  │  PCM16 24kHz  │ check-ins, presence,     │       ├──────────────────────┤
 │ wake word · kiosk    │  + JSON       │ tools, pages, calls      │ ◄───► │ Agents API "Toad"    │
 └──────────────────────┘               └──────────────────────────┘       │ (brain + web search) │
                                           │ agent page, test client       ├──────────────────────┤
                                           │ data/toad.json, data/pages    │ Composio · AgentPhone│
                                                                           └──────────────────────┘
```

- **Engine mode** (Settings → engine address set): the phone streams the mic up and plays Toad's voice back, answers camera requests, and shows the engine's memories, focus timer, check-ins, pages and app links. Talk, the wake phrase and check-ins open the voice session; screen buttons go to the brain as taps.
- **On-phone mode** (address blank): Claude runs on the phone itself with six local tools, no engine needed.
- **The brain** is one saved Agents API agent, defined in [`agent/toad-agent.json`](agent/toad-agent.json): Toad's instructions, hosted web search and 15 desk tools (`get_desk_status`, `set_focus`, `finish_focus`, `set_reminder`, `cancel_reminder`, `save_memory`, `delete_memory`, `look_through_camera`, `call_phone`, `control_desk`, `show_page`, `add_todo`, `complete_todo`, `remove_todo`, `show_today`), plus your connected apps through Composio. [`agent/toad_agent.py`](agent/README.md) drives the same agent from a terminal.

The phone app follows design 1a "Nightlight": six screens that change with what Toad is doing (idle, listening, speaking, camera read, timer check-in, memories & privacy), and Toad's face shows the state (dozing, listening, thinking, talking, muted, peeking) instead of a spinner.

## Quick start

Needs Python 3.12+. From the repository root:

```bash
python3 scripts/setup.py                  # .venv, locked deps, private .env with a new DEVICE_TOKEN
.venv/bin/python -m uvicorn toad_server.main:app --host 0.0.0.0 --port 8787 --no-access-log
```

Open `http://localhost:8787/agent` (agent page) or `http://localhost:8787/` (browser test client). The default `PROVIDER_MODE=fake` needs no keys: it returns labeled diagnostic text and a test tone, not AI. For the real Toad, set `PROVIDER_MODE=openai` and `OPENAI_API_KEY` in `.env` (paid; see [server/README.md](server/README.md)).

Phone over USB (JDK 17 and the Android SDK are installed repo-locally by the toolchain setup in [android/README.md](android/README.md)):

```bash
source scripts/android-env.sh
(cd android && ./gradlew :app:installDebug)
adb reverse tcp:8787 tcp:8787
```

In the app: long-press the clock → Settings → engine `ws://127.0.0.1:8787` and the `DEVICE_TOKEN` from `.env`. On Wi-Fi use `ws://<laptop LAN IP>:8787` (debug builds allow `ws://`; release builds need `wss://`).

## What it does, and how it was checked

"Tested" means automated tests that run with fakes, no paid services and no phone. "Live" means checked against the real providers or a real phone, which is the [live testing steps](docs/LIVE_TESTING_STEPS.md) still to be run for Toad.

| Feature | Status | How it was verified |
|---|---|---|
| Voice conversation through GPT-Live, with delegation to the brain | Built | Engine tests with a fake GPT-Live and brain; GPT-Live client tested against a loopback WebSocket provider. **Not yet live.** |
| Brain: saved agent, persistent session, tools, recovery | Built | The real OpenAI Python SDK against a mock HTTP/SSE transport. **Not yet live.** |
| Toad speaks first: check-ins when the timer ends | Built | Tests: due, late, offline-then-reconnect, once only |
| Memory only when asked, enforced in code | Built | Policy tests; the tool refuses unasked saves, including from call transcripts |
| Camera: instant photo on request, honest when off | Built | Engine tests (round trip, switched off, timeout, disconnect) |
| To-dos and the live Today screen | Built | Tests: add, check off, remove, same page updated in place, escaping |
| Pages on the desk screen (sandboxed, UI kit) | Built | Tests: storage limits, CSP, kit injection, versioned links, delete auth |
| Presence: Today on arrival, welcome back after 10+ minutes (also while always listening) | Built | Tests with scripted presence and a controlled clock |
| Reminders: in N minutes or at a time, once, daily or weekdays; cancel by words | Built | Tests incl. weekends, daylight saving, away calls |
| Focus time: finish a focus with an outcome; minutes focused today | Built | Tests; shown on the Today screen and in desk status |
| Morning briefing the first time you sit down each day | Built | Tests: once a day, not before 5 AM, not in quiet hours |
| Break nudges after a long stretch at the desk | Built | Tests: short glances don't reset, a real break does, off with 0 |
| Changes to your apps need your yes, enforced in code | Built | Tests: sends/creates/deletes refused without a yes to Toad's question; reads allowed |
| Desk controls (camera, mute, memories, end conversation) | Built | Tests, including end-after-goodbye |
| Barge-in, mute, idle close, always-listening reopen, Stop | Built | Tests with a controlled clock |
| Apps through Composio (Python SDK) | Built | Tests against a fake SDK pinned to composio 0.25's shapes. **Not yet live.** |
| Phone calls through AgentPhone (away, on request, a friend) | Built | Tests: offline, no reply, camera absence, quiet hours, startup grace, consent, errors; HTTP client against a mock API. **Not yet live.** |
| Agent page and browser test client | Built | HTTP tests and a local run through the USB bridge |
| Terminal agent client | Built | 44 tests against mocked API responses. **Not yet live.** |
| Android app (both modes, kiosk, wake word, toad character) | Built | 13 JVM tests, debug APK and lint (zero errors). **Not yet on a real phone.** |
| "Hey Toad" wake phrase | Built | `scripts/check-wake-word.sh` checks synthetic voices. **Not yet with a real mic.** |

Run the whole offline suite with `.claude/skills/toad-engine/scripts/check.sh` and `scripts/validate-android.sh`.

## The demo

1. "Hey Toad… help me plan my afternoon." It offers to look at your list.
2. You hold up a handwritten to-do list; it reads it and suggests one item.
3. You choose together; it sets a 25-minute focus and puts it on the Today screen.
4. "Remember that I'm working on this." The memory appears on screen.
5. The timer ends: Toad speaks first and asks how it went. "Done, the first draft is written": it records the session and your focus time. If you've left the desk, it calls you.
6. "Remind me at 3 to call Mom." At 3, Toad reminds you out loud.
7. Next morning you sit down: Toad gives a two-sentence briefing of your day.
8. Later, in a new conversation: "What was I supposed to focus on?" It answers from memory.

## Privacy model

| What | Where it goes | Kept? |
|---|---|---|
| Background audio while waiting for "Hey Toad" | Processed in memory on the phone by Vosk, then dropped | Never |
| What you say in a voice session | Streamed to GPT-Live through the engine (`store: false`); the engine keeps a short transcript in memory for the brain | Not written to disk |
| Camera | On-phone face detection about once a second, frames dropped; a photo is taken only when Toad needs to look, and goes to the brain | Frames never; a photo only in the brain session |
| Memories, focus, to-dos, check-ins | `data/toad.json` on the engine | Until you delete them |
| Pages | `data/pages/` on the engine, newest 50 | Until replaced or deleted |
| Keys (OpenAI, Composio, AgentPhone) | The engine's `.env` only; never on the phone | Until you replace them |

Muted means nothing is listening, not even for the wake phrase.

## Locked kiosk

Toad can lock a phone so it runs only Toad: no home screen, status bar or lock screen; it boots into Toad and keeps the screen on while charging. On a phone with no accounts, install the app and run `adb shell dpm set-device-owner com.toad.companion/.kiosk.ToadAdmin`. To get out, hold the top of the screen for 5 seconds and enter `toad.kioskPin` from `android/local.properties`. If the PIN is lost, the only way out is a factory reset.

## Repository

```
android/         Kotlin/Compose app (com.toad.companion): screens, toad character, voice, camera, kiosk
server/          Python engine (toad_server), tests, live-check scripts         → server/README.md
agent/           the saved agent definition and the terminal client             → agent/README.md
scripts/         setup, smoke test, Android validation, start/switch/demo tools → scripts/README.md
design/avatar/   the toad character reference
demo/            the handwritten to-do photo used by the demo and smoke tests
docs/            features, live testing steps, protocol, status, decisions
.claude/skills/  Claude Code skills for this repo (below)
Dockerfile, fly.toml   one-machine cloud deployment
```

## Claude Code skills

`.claude/skills/` holds skills that Claude Code loads in this repo:

| Skill | For |
|---|---|
| `toad-engine` | running, testing and debugging the Python engine; `scripts/check.sh` runs every offline check |
| `toad-agent` | changing the agent's instructions or tools; `scripts/check_agent.py` proves every tool is implemented |
| `toad-android` | building, installing and driving the phone app, kiosk and wake phrase |
| `toad-apps` | Toad's Composio integration in Python |
| `toad-pages` | writing and previewing desk pages with the UI kit |
| `composio` | the upstream Composio skill, vendored unchanged (`.agents/skills/composio`, pinned in `skills-lock.json`) |

## Docs

- [Live testing steps](docs/LIVE_TESTING_STEPS.md): the remaining acceptance run with real providers and a real phone
- [Handoff](HANDOFF.md): where things stand and what to do next
- [Features](docs/FEATURES.md): every feature, where it lives in the code, and its tests
- [Engine](server/README.md) · [Device protocol](docs/DEVICE_PROTOCOL.md) · [Status](docs/STATUS.md) · [Decisions](docs/DECISIONS.md)
- History: [workflow](docs/WORKFLOW.md), [Android validation](docs/ANDROID_VALIDATION.md)

## License

MIT. See [LICENSE](LICENSE).

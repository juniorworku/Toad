# Parity with Desku

Baseline: Desku commit `2aea122`. "Same" means the same behavior, wire format and rules; model wording can differ. Every row marked Same on the server side has a test, most of them ported one-for-one from Desku's `server/test/*.test.ts`.

## Engine (TypeScript → Python)

| Desku | Toad | Status | Tests |
| --- | --- | --- | --- |
| `index.ts` routes: `/healthz`, `/agent` → `/agent.html`, `/`, `GET /api/overview` (bearer), `POST /api/apps/connect`, `GET /p/<id>`, `DELETE /api/pages/<id>` (204/404), `/device` upgrade with constant-time token check | `main.py` | Same | `test_http.py`, `test_device.py`, `test_pages_tools.py` |
| Token filled in for localhost pages | `main.is_local` + `toad.token` | Same | `test_http.py` |
| Composio connections cached 30 s, never while pending | `main.app_connections` | Same | — |
| `Desk.ts`: one device, replacement closes the old one (4000) | `desk.attach` | Same | `test_device.py` |
| Voice session on demand / always listening, reopen ≥ 10 s, Stop pauses, idle close | `desk.start/stop/tick` | Same | `test_engine.py`, `test_lifecycle.py` |
| Delegation: 400 ms settle, `[Heard] …` + recent 8 turns, camera progress spoken, other progress silent, answer or `Done.` | `desk.delegated/_turn` | Same | `test_engine.py` |
| Brain failure → `error` to phone + "Sorry…" spoken | `desk._turn` | Same | `test_engine.py` |
| Screen tap → `[Tapped on the desk screen] …`, noted in transcript, not repeated next turn | `desk.on_tapped` | Same | `test_engine.py` |
| Barge-in `interrupt` within 3 s of Toad's audio, once per second | `desk.transcript` | Same | `test_engine.py`, `test_desk.py` |
| Check-ins: fired once, `[Desk event] Check-in due (N minutes late…)`, fallback line, wait while offline | `desk.tick/deliver_checkin` | Same | `test_engine.py`, `test_lifecycle.py` |
| Presence: Today on arrival (not for a short glance), welcome back after 10 min, at most every 30 min, not in quiet hours | `desk.on_presence` | Same | `test_engine.py` |
| Away calls: offline (after 2-min startup grace), no reply in 60 s, camera absence > 2 min, quiet hours, one at a time, transcript → brain | `desk.call_away` | Same | `test_away.py` |
| Calls on request: call me (even in quiet hours), call a friend (US/CA, consent across turns), outcome spoken, 402/401 explained | `desk.place_call/call_for_user`, `call_problem` | Same | `test_away.py` |
| Desk controls and their replies | `desk.control` | Same | `test_engine.py` |
| `tools.ts`: 12 tools, outputs and error texts, `allowsCall`, Composio pass-through | `tools.py` | Same | `test_engine.py`, `test_away.py`, `test_apps.py`; `check_agent.py` |
| `today.ts` Today screen in kit classes | `today.py` | Same | `test_engine.py`, `test_http.py` |
| `AgentBrain.ts`: definition hash sync, session per definition, serialized turns, 150 s timeout, one session recovery, idempotent tool results | `brain.py` | Same | `test_brain.py` |
| `MemoryPolicy.ts` | `memory_policy.py` | Same | `test_memory_policy.py` |
| `LiveClient.ts`: queue until `session.started`, drop early audio, 1,800-char clip, graceful close | `live.py` | Same | `test_live.py` |
| `live/prompt.ts` voice instructions | `prompt.py` | Same (Toad) | `test_engine.py` |
| `Transcript.ts` | `transcript.py` | Same | `test_live.py`, `test_engine.py` |
| `Store.ts`: fields, ids (`m1`, `t1`), atomic write, incoming-file handover, 50 focus history, fired check-ins kept a day | `store.py` | Same | `test_store.py` |
| `Pages.ts`: 128-bit ids, 512 KB, newest 50, CSP, kit injection | `pages.py` | Same | `test_pages_tools.py` |
| `Apps.ts` (Composio TS SDK) | `apps.py` (Composio Python SDK 0.25) | Same behavior, Python SDK calls | `test_apps.py` |
| `AgentPhone.ts` | `phone.py` (httpx) | Same | `test_away.py` |
| `config.ts` | `config.py` | Same settings (plus `PROVIDER_MODE`) | `test_http.py` |
| `public/index.html`, `public/agent.html` | `toad_server/public/` | Same, rebranded | `test_http.py` |
| `server/scripts/*.ts` (smoke-brain, smoke-apps, smoke-page, fake-phone, call-me, connect-app, usb-bridge) | `server/scripts/*.py` | Same; `fake_phone.py` also uses `espeak-ng` or WAV files on Linux | local run |
| 42 server tests (node:test; its README still says 26) | 110 pytest tests | Every Desku case ported, plus Toad-only cases | `check.sh` |

## Everything else

| Desku | Toad | Status |
| --- | --- | --- |
| `app/` Kotlin app, `com.deskbuddy` | `android/app/`, `com.toad.companion` | Same code, rebranded; `EngineLink.kt` and `CompanionViewModel.kt` identical apart from names |
| Blue Desku character (`ui/Desku.kt`) | Moss-green toad (`ui/Toad.kt`), same six expressions, eye-follow, voice-driven mouth | Changed on purpose |
| Wake phrase "Hey Desku" (8 measured variants) | "Hey Toad" (1 variant, decoys kept) | Needs real-speech measurement |
| 13 JVM tests | 13 JVM tests | Same, passing |
| `agent/desku-agent.json` | `agent/toad-agent.json` | Same tools and instructions, rebranded |
| `agent/desku.sh` (bash + curl + jq) | `agent/toad_agent.py` (Python + httpx) | Same commands and API calls; 41 tests |
| `scripts/*.sh` | `scripts/*.sh` | Same steps; Linux support added (espeak-ng, systemd-inhibit, repo-local adb) |
| `Dockerfile`, `fly.toml` (Node) | `Dockerfile`, `fly.toml` (Python, app `toad-engine`) | Same deployment shape |
| `.agents/skills/composio` + `.claude/skills/composio` + `skills-lock.json` | Vendored byte-identical | Same |
| — | `.claude/skills/toad-*` | New: repo skills for engine, agent, Android, apps, pages |

## Intentional differences

- **Provider mode.** Toad has `PROVIDER_MODE=fake` (default) so the stack runs with no keys; Desku required an OpenAI key to start.
- **Stop doesn't cancel a running brain turn.** As in Desku the reply is dropped for the closed session, but the turn finishes, so the agent session never keeps an unanswered tool call.
- **The device token never reaches the log.** Uvicorn logs the socket path; Toad redacts `token=`. Desku's Node server didn't log paths.
- **Strict message validation.** A non-boolean `enabled`/`present` or a non-string `say` text is rejected with `invalid <type> message` instead of being coerced, and an odd-length audio frame gets an `error` instead of being dropped silently.
- **Commands to GPT-Live are never dropped.** Only queued mic audio is capped (about 6 s); speech, mute and close always go out, and a failing close can't leave a billed session running.
- **Phone and number settings are explicit.** Toad doesn't hardcode Desku's AgentPhone number or OpenAI project; set your own.
- **Stricter output limits on the device socket.** A phone that stops reading is closed (1013) once 128 frames are queued, instead of buffering without limit.

# Features

What Toad does, where it lives, and which tests cover it. Everything on the engine side runs in the offline suite (`.claude/skills/toad-engine/scripts/check.sh`); live checks are in [LIVE_TESTING_STEPS.md](LIVE_TESTING_STEPS.md).

## Conversation

| Feature | Code (`server/src/toad_server/`) | Tests |
| --- | --- | --- |
| One phone at a time; a newer connection replaces the older (close 4000); constant-time token check; token redacted from logs | `main.py`, `desk.attach` | `test_device.py`, `test_http.py` |
| Voice session on demand or always listening (reopen at most every 10 s, Stop pauses until Talk), idle close | `desk.start/stop/tick` | `test_engine.py`, `test_lifecycle.py` |
| Delegation to the brain: `[Heard] …` plus recent context, camera progress spoken, every delegation answered (apology on failure) | `desk.delegated/_turn` | `test_engine.py` |
| Screen taps go to the brain as `[Tapped on the desk screen] …` | `desk.on_tapped` | `test_engine.py` |
| Barge-in: the phone drops queued speech when you talk over Toad | `desk.transcript` | `test_engine.py`, `test_desk.py` |
| Desk controls: camera on/off, close camera, mute, show/hide memories, end the conversation | `desk.control` | `test_engine.py` |
| The brain: a saved Agents API agent synced from `agent/toad-agent.json`, one persistent session, serialized turns, 150 s timeout, one automatic session recovery | `brain.py` | `test_brain.py` |
| Voice: GPT-Live client with queued start-up commands; commands are never dropped, only stale mic audio is capped | `live.py`, `prompt.py`, `transcript.py` | `test_live.py` |

## Helping you work

| Feature | Code | Tests |
| --- | --- | --- |
| Focus with a check-in where Toad speaks first; late and offline check-ins | `tools.set_focus`, `desk.tick/deliver_checkin` | `test_engine.py`, `test_lifecycle.py` |
| **Finishing a focus** with an outcome; **focus time today** and sessions finished today | `tools.finish_focus`, `today.focus_today` | `test_companion.py` |
| **Reminders**: in N minutes or at a local time, once, daily or on weekdays; cancel by id or words; spoken as reminders (or a call when away); daylight-saving safe | `tools.set_reminder/cancel_reminder`, `desk.fire`, `prompt.parse_at/next_occurrence` | `test_companion.py` |
| To-do list (add, check off, remove); finished items kept a week | `tools.py`, `store.py` | `test_engine.py`, `test_companion.py` |
| Today screen: to-dos, focus with countdown, reminders, focus time, memories | `today.render_today` | `test_engine.py`, `test_http.py`, `test_companion.py` |
| Pages on the desk screen: sandboxed, 512 KB, newest 50, UI kit with its fonts | `pages.py`, `tools.show_page` | `test_pages.py`, `test_pages_tools.py` |
| Memory only when you ask, enforced in code | `memory_policy.py` | `test_memory_policy.py`, `test_engine.py` |

## Noticing you (camera presence)

| Feature | Code | Tests |
| --- | --- | --- |
| Today screen when you arrive (not for a short glance away) | `desk.on_presence` | `test_engine.py` |
| **Morning briefing** the first time you're seen each day (after 5 AM): to-dos, reminders, calendar | `desk.on_presence` | `test_companion.py` |
| Welcome back after 10+ minutes away, asking about your focus; **works while always listening**, skipped mid-conversation | `desk.on_presence`, `desk.conversation_active` | `test_engine.py`, `test_companion.py` |
| **Break nudges** after `BREAK_AFTER_MINUTES` at the desk (default 50); a real break (2+ minutes away) resets the clock | `desk.maybe_suggest_break` | `test_companion.py` |
| Quiet hours: no briefings, welcomes, nudges or unrequested calls | `desk.quiet` | `test_companion.py`, `test_away.py` |

## Reaching out

| Feature | Code | Tests |
| --- | --- | --- |
| Away calls through AgentPhone: phone offline, no reply in 60 s, or not seen for 2 minutes; startup grace; one at a time; transcript goes back to the brain | `desk.call_away`, `phone.py` | `test_away.py` |
| Calls on request: call me, or a friend (US/Canada, with consent across turns); outcome spoken; a second call in the same turn refused | `desk.place_call/call_for_user`, `tools.allows_call` | `test_away.py` |
| Your apps through Composio (Python SDK); Connect Links on the screen | `apps.py` | `test_apps.py` |
| **Changes to your apps need your yes**, enforced in code: sending, creating, changing or deleting is refused unless your latest words say yes to Toad's question | `tools.app_writes/allows_app_write` | `test_companion.py` |

## Around the engine

| Piece | Where | Tests |
| --- | --- | --- |
| Device protocol shared with the phone app | `docs/DEVICE_PROTOCOL.md` | `test_protocol.py` (against the Kotlin source) |
| Agent page, browser test client, `/api/overview`, `/api/apps/connect` | `main.py`, `public/` | `test_http.py` |
| Android app: Nightlight screens, toad character, wake phrase "Hey Toad", camera presence, kiosk, on-phone Claude mode | `android/` | 13 JVM tests, lint |
| Terminal agent client | `agent/toad_agent.py` | `agent/tests/` |
| Live-check scripts, USB bridge | `server/scripts/` | local run |
| Operating scripts, Docker, Fly | `scripts/`, `Dockerfile`, `fly.toml` | `bash -n` |

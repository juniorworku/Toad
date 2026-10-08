# Workflow and history

## Working method

1. Write down the behavior first (tests in `server/tests/`, with the fakes in `fakes.py`), then implement it.
2. Keep the device protocol in step with the Android app; `test_protocol.py` checks it against the Kotlin source.
3. Run `.claude/skills/toad-engine/scripts/check.sh` (and `scripts/validate-android.sh` for phone changes) before calling a change done. Use simulated providers; live checks are a separate, explicit step ([LIVE_TESTING_STEPS.md](LIVE_TESTING_STEPS.md)).
4. Update [STATUS.md](STATUS.md), [FEATURES.md](FEATURES.md) and [DECISIONS.md](DECISIONS.md), then commit a reviewable batch.
5. Keep tokens, `.env`, generated state and local Android configuration out of Git.

## October 8, 2026: foundation

Kotlin/Compose app with the moss-green toad, Python FastAPI engine with the device socket, atomic JSON store, memory consent policy, GPT-Live adapter, saved-agent adapter, pages and desk tools. Setup script, lifecycle scheduler (reconnect, idle close, end after reply, Stop), once-only persisted check-ins. Repo-local Android toolchain: debug APK, JVM tests and lint passing.

## October 8, 2026: the complete engine

Brain message formats, the "Sorry" fallback so every delegation is answered, full voice instructions, tool outputs and errors, the kit-styled Today screen, presence welcome-back, Composio apps, AgentPhone away calls and calls on request, desk controls, the agent page and browser test client, `/api/overview` and `/api/apps/connect`. The Python terminal agent client, the live-check scripts, the operating scripts with Linux support, Docker/Fly files, the vendored `composio` skill, five Toad skills, `CLAUDE.md` and the live testing steps.

Fixed along the way: GPT-Live waited forever on an empty delegation or a brain failure; Stop cancelled brain turns mid-tool-call; uvicorn logged the device token; pages loaded without the kit's fonts. An independent review then found and fixed: a full command queue could drop spoken replies and leave a billed session open; a failed tool-result submit replayed the whole turn; two `call_phone` calls in one turn both reported success; brain timeouts had an empty error message.

## October 8, 2026: companion habits

A gap review of the companion found: welcome-back never ran with always-listening on (the default); finishing a focus had no tool, so "what did I finish?" was always empty; there were no standalone reminders and no way to cancel a check-in; no break nudges despite camera presence; no start-of-day briefing; app-change consent was prompt-only; finished to-dos piled up forever.

Added `finish_focus`, `set_reminder` and `cancel_reminder`, focus time today, reminders and focus time on the Today screen, the morning briefing, break nudges, quiet hours for everything Toad starts, code-enforced app-change consent, and a week's retention for finished to-dos. The phone shows reminders as a notice. Each behavior has tests in `test_companion.py`.

## Repeatable checks

```bash
python3 scripts/setup.py --check
.claude/skills/toad-engine/scripts/check.sh
source scripts/android-env.sh && scripts/validate-android.sh
.venv/bin/python scripts/smoke_local.py
```

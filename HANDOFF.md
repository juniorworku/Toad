# Handoff

State of Toad as of October 9, 2026 (commit `087112b`), and what to do next. Read [CLAUDE.md](CLAUDE.md) for the rules of the repo and [docs/FEATURES.md](docs/FEATURES.md) for what each feature does.

## Where things stand

**Built and passing offline:** the Python engine (voice through GPT-Live, the saved "Toad" agent with 15 desk tools, check-ins, reminders, focus time, morning briefing, break nudges, presence, pages, Composio apps, AgentPhone calls, the agent page and browser test client), the Android app (engine and on-phone modes, kiosk, "Hey Toad"), the terminal agent client, the live-check scripts, the operating scripts, Docker/Fly files and the Claude Code skills.

Last full check run:

| Check | Result |
| --- | --- |
| `.claude/skills/toad-engine/scripts/check.sh` | 125 server tests, 44 agent client tests, Ruff, strict mypy, agent/tool check: all pass |
| `scripts/validate-android.sh` | 13 JVM tests pass, debug APK builds, lint 0 errors / 33 warnings |
| `scripts/smoke_local.py` | pass (fake mode) |
| Engine behind `server/scripts/usb_bridge.py`, driven by `fake_phone.py` | pass (fake mode) |

**Never run for real:** any OpenAI, Composio or AgentPhone call (no keys have been used); the app on a physical phone; the Fly deployment. The Docker image is built and checked locally. Everything "works" only against fakes until the live steps below are done.

## Next steps, in order

1. ~~Verify the Docker image.~~ **Done October 9:** `docker build -t toad-engine .` succeeds (301 MB). The container (`docker run --rm -p 8787:8787 -e DEVICE_TOKEN=… toad-engine`) serves `/healthz`, the agent page and test client, `/api/overview` (401 without the token), and the phone socket (tap round trip passes; a wrong token gets 401); the log redacts the token. It runs in fake mode unless `PROVIDER_MODE=openai` and `OPENAI_API_KEY` are passed. Not yet deployed to Fly.
2. **Live testing.** Follow [docs/LIVE_TESTING_STEPS.md](docs/LIVE_TESTING_STEPS.md) stage by stage (A engine + agent sync → B brain alone → C browser voice → D stand-in phone → E real phone → F apps → G calls → H kiosk/cloud). It costs money from stage A on; fill in its results table. The biggest unknowns: whether the OpenAI account has GPT-Live and Agents API access, voice quality and echo on a real phone, and how the brain words briefings, reminders and break nudges.
3. **Measure the wake phrase.** `voice/WakeWord.kt` has one variant (`"hey toad"`). Record real speech (several voices, a real room), run it through the Vosk grammar (`scripts/check-wake-word.sh` for synthetic voices needs `espeak-ng` and `android/scripts/fetch-wake-model.sh`), and add the variants the model actually hears, plus decoys for near-misses. Keep `scripts/check-wake-word.sh` in sync with `WakeWord.kt`.
4. **Tune the habits from real use.** Defaults: `BREAK_AFTER_MINUTES=50`, `MORNING_BRIEFING=1`, briefing after 5 AM, welcome-back after 10 minutes away at most every 30, `QUIET_HOURS=22-8`. Constants are at the top of `server/src/toad_server/desk.py`.
5. **Deploy** (optional): Fly app `toad-engine`, one Machine, volume `toad_data` at `/data`, keys as Fly secrets. `scripts/switch-to-cloud.sh` / `switch-to-laptop.sh` move the state and the phone. Change `primary_region` in `fly.toml` first.

## Open gaps (not started)

| Gap | Notes |
| --- | --- |
| Languages other than English | Voice instructions, agent instructions, memory and consent regexes, wake grammar are all English |
| On-phone mode lacks the engine's habits | No reminders, briefings or break nudges when Claude runs on the phone; replies only speak after the whole reply is ready |
| Ambient listening | Toad hears you only in an open voice session; always-listening keeps one open (billed per minute) |
| Battery and heat for 24/7 | Untuned; the always-on camera and an open voice session both cost power |
| Release build | No release signing; debug APK is ~77 MB with R8 off; 33 lint warnings |
| App-change consent coverage | Writes are recognized by Composio tool names (`…_SEND_…`, `…_CREATE_…`, …); an oddly named write tool would slip through. See `tools.APP_WRITE` |
| Engine end-of-day recap | Data is there (`focused_today`, `finished_today`, `done_today` in `get_desk_status`); there's no proactive recap event |

## Things to know before changing code

- **Paid and outward actions need the user's go-ahead** (see CLAUDE.md for the list). The `.env` has `PROVIDER_MODE=fake` and no provider keys; keep it that way unless live testing.
- **Protocol changes touch both sides.** `server/tests/test_protocol.py` compares the engine with `EngineLink.kt` and `CompanionViewModel.kt`; reminders rely on the `Reminder: ` prefix in check-ins (the phone shows them as a notice).
- **Agent tools:** a tool in `agent/toad-agent.json` must be implemented in `server/src/toad_server/tools.py`; `.claude/skills/toad-agent/scripts/check_agent.py` enforces it. Changing the JSON starts a new brain session on the next live start.
- **Tests use fakes and a controlled clock** (`server/tests/fakes.py`). Briefings and break nudges are off in the test rig unless a test turns them on.
- **`LICENSE` keeps a second copyright line.** It's required by the MIT terms the code was received under; don't remove it.
- **`composio` skill** in `.agents/skills/` is vendored upstream and hash-locked in `skills-lock.json`; Toad-specific guidance goes in `.claude/skills/toad-apps`.
- **Logs:** the engine redacts `token=` from uvicorn's lines; still never paste a token or `.env` into chat or issues.

## Environment on this machine

- Python 3.12 venv at `.venv` (`python3 scripts/setup.py` recreates it from `server/requirements.lock`).
- Java 17 and the Android SDK are repo-local in `.tools/` (`source scripts/android-env.sh`).
- `junior` is in the `docker` group (since October 8; needs a new login, or `sg docker -c "…"`). A local test image `toad-engine:test` exists.
- No `espeak-ng`, `ffmpeg` or phone attached; `fake_phone.py` accepts WAV files with `--wav` instead of text-to-speech.

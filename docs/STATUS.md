# Status

Updated October 8, 2026. What each feature does and where it's tested: [FEATURES.md](FEATURES.md).

## Done

- **Python engine.** Device socket and protocol, GPT-Live voice with client delegation, the saved "Toad" agent with 15 desk tools plus web search, check-ins where Toad speaks first, the to-do list and Today screen, pages with the UI kit, desk controls, barge-in, mute, idle close, always-listening, Composio apps, AgentPhone away calls and calls on request, the agent page and the browser test client.
- **Companion habits.** Reminders (once, daily, weekdays; cancel by words), finishing a focus with an outcome and focus time today, a morning briefing, welcome-back that works while always listening, break nudges after a long stretch, quiet hours for everything Toad starts on its own, and changes to your apps refused in code unless you said yes.
- **Android app** (`com.toad.companion`, moss-green toad, "Hey Toad"): engine and on-phone modes, kiosk; reminders show as a notice instead of the focus check-in screen.
- **Agent:** `agent/toad-agent.json` and the terminal client `agent/toad_agent.py`.
- **Operating tools:** setup, local smoke test, start/switch/demo/wake-word/avatar scripts, live-check scripts in `server/scripts/`, Docker and Fly files.
- **Claude Code skills:** `toad-engine`, `toad-agent`, `toad-android`, `toad-apps`, `toad-pages`, and the vendored `composio` skill.

## Verified offline

- `.claude/skills/toad-engine/scripts/check.sh`: all server and agent client tests, Ruff lint and format, strict mypy (server, agent client, server scripts) and the agent/tool check pass.
- Protocol conformance against the Kotlin source: every message type the engine sends is handled by `EngineLink.kt`, and every type the app sends is accepted by the engine.
- `scripts/validate-android.sh`: JVM tests pass, the debug APK builds, lint has zero errors.
- A local fake-mode run of the engine behind `server/scripts/usb_bridge.py`, driven by `server/scripts/fake_phone.py`: HTTP routes, bearer auth, localhost token fill-in, the device socket through the bridge, a tap round trip, audio resampling, the token redacted from the log. `scripts/smoke_local.py` passes.

## Not verified yet

Nothing below has run: there are no provider keys in this environment and no phone attached. Steps: [LIVE_TESTING_STEPS.md](LIVE_TESTING_STEPS.md).

1. Any live OpenAI call: saved-agent sync, a brain turn, a GPT-Live voice session.
2. The real phone against the engine: audio, echo, camera, presence, pages, the toad on screen, the reminder notice.
3. How the brain words briefings, welcomes, break nudges and reminders, and whether it uses the new tools as instructed.
4. "Hey Toad" with a real microphone (one grammar variant, unmeasured).
5. Composio with a connected app; AgentPhone calls; the Fly deployment and the switch scripts.

## Known gaps

- Languages other than English.
- No ambient listening: Toad hears you only in an open voice session (always-listening keeps one open, at a cost per minute).
- On-phone mode (Claude on the phone) speaks only after the whole reply is ready and has none of the engine's reminders, briefings or break nudges.
- Battery and heat for 24/7 use are untuned; no release signing; the debug APK is about 77 MB (R8 off).
- App-change consent recognizes writes by Composio tool names (`…_SEND_…`, `…_CREATE_…`, etc.); an unusually named write tool would not be caught.

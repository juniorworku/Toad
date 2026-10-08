# Status

Updated October 8, 2026. Feature-by-feature mapping: [PARITY.md](PARITY.md).

## Done

- **Python engine at parity with Desku's engine.** Device socket and protocol, GPT-Live voice with client delegation, the saved "Toad" agent with all 12 desk tools plus web search, check-ins where Toad speaks first, presence (Today on arrival, welcome back), the to-do list and Today screen, pages with the UI kit, desk controls, barge-in, mute, idle close, always-listening, Composio apps, AgentPhone away calls and calls on request, the agent page and the browser test client.
- **Android app** ported from Desku and rebranded (`com.toad.companion`, moss-green toad, "Hey Toad"), both engine and on-phone modes, kiosk.
- **Agent:** `agent/toad-agent.json` and the terminal client `agent/toad_agent.py`.
- **Operating tools:** setup, local smoke test, start/switch/demo/wake-word/avatar scripts, live-check scripts in `server/scripts/`, Docker and Fly deployment files.
- **Claude Code skills:** `toad-engine`, `toad-agent`, `toad-android`, `toad-apps`, `toad-pages`, and the vendored `composio` skill.

## Verified (offline, October 8, 2026)

- `.claude/skills/toad-engine/scripts/check.sh`: **110 server tests** and **41 agent CLI tests** pass; Ruff lint and format, strict mypy (server, agent CLI, server scripts) and the agent/tool parity check pass. All 42 of Desku's server test cases are ported.
- Protocol conformance against the Kotlin source: every message type the engine sends is handled by `EngineLink.kt`, and every type the app sends is accepted by the engine.
- `scripts/validate-android.sh`: **13 JVM tests** pass, the debug APK builds, lint has zero errors.
- A local run of the engine (fake mode) behind `server/scripts/usb_bridge.py`, driven by `server/scripts/fake_phone.py` and a raw WebSocket client: HTTP routes, bearer auth, localhost token fill-in, the device socket through the bridge, a screen tap round trip, audio resampling, and the token redacted from the server log.
- `scripts/smoke_local.py` passes.

## Not verified yet

Nothing below has run, because there are no provider keys in this environment and no phone attached. Steps: [LIVE_TESTING_STEPS.md](LIVE_TESTING_STEPS.md).

1. Any live OpenAI call: saved-agent sync, a brain turn, a GPT-Live voice session.
2. The real phone against the Python engine: audio quality, echo, camera, presence, pages, the toad character on screen.
3. "Hey Toad" with a real microphone (the grammar has one variant and is unmeasured).
4. Composio with a connected app; AgentPhone calls; the Fly deployment and the switch scripts.
5. `scripts/check-wake-word.sh` (needs the Vosk model and espeak-ng on this host).

## Known gaps carried over from Desku

- The "ask before writing to an app" rule is in the agent instructions only, not enforced in code.
- No ambient listening; Toad hears you only in an open voice session.
- Interrupting by voice relies on GPT-Live; queued phone audio is dropped on `interrupt`.
- Release signing and APK size (debug APK about 77 MB, R8 off).

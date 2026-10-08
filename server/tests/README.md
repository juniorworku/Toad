# Server tests

Run from the repository root:

```bash
.venv/bin/python -m pytest server/tests -q
```

No test calls a real service. `fakes.py` provides a scripted GPT-Live session (`FakeLive`), a scripted brain (`FakeBrain`), a stand-in phone (`FakeDevice`) and `Rig`, a desk with a controlled clock. Companion habits (briefing, break nudges) are off in the rig unless a test turns them on.

| File | Covers |
| --- | --- |
| `test_engine.py` | voice turns, delegation, camera, check-ins, mute, idle close, taps, controls, pages, presence, to-dos |
| `test_companion.py` | reminders, focus time, morning briefing, break nudges, welcome-back while listening, app-change consent |
| `test_away.py` | away calls, calls on request, consent, quiet hours, the AgentPhone client |
| `test_apps.py` | Composio session, tools, Connect Links, errors |
| `test_brain.py` | saved-agent sync, sessions, tool results, recovery, timeouts, the real SDK on a mock transport |
| `test_live.py` | the GPT-Live client against a loopback WebSocket provider |
| `test_device.py`, `test_desk.py`, `test_lifecycle.py` | the device socket, transport, scheduler |
| `test_http.py`, `test_pages.py`, `test_pages_tools.py` | HTTP routes, overview, pages, the kit |
| `test_store.py`, `test_memory_policy.py`, `test_protocol.py` | state, the memory rule, protocol against the Kotlin source |

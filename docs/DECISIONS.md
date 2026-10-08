# Decisions

Append a dated row when a change alters behavior, the protocol or the provider architecture.

## Architecture

| Decision | Why |
| --- | --- |
| Python (FastAPI) engine, Kotlin/Compose Android app | Requested |
| Name Toad; package `com.toad.companion`; moss-green toad character | Product identity |
| File-backed JSON state, one engine worker, one phone | Simple and reliable for one desk; the engine owns the phone socket and the scheduler |
| GPT-Live for voice with client delegation; one saved Agents API agent as the brain, with a persistent session | Short billed voice sessions, long-lived memory of the conversation |
| `PROVIDER_MODE=fake` is the default | The whole stack runs with no keys; live mode is opt-in |
| `store: false` in the GPT-Live session config | Documented field; conversations aren't stored |
| Composio through its Python SDK (0.25), called in a worker thread | The SDK is synchronous; call shapes checked against the installed package |
| Vendor the upstream `composio` skill byte-identical, with Toad-specific `toad-*` skills beside it | Keeps the upstream hash valid |

## Behavior (October 8, 2026)

| Decision | Why |
| --- | --- |
| Brain messages start with `[Heard]`, `[Tapped on the desk screen]` or `[Desk event]` | The agent's instructions and the consent rules depend on knowing who spoke |
| A screen tap isn't echoed to the phone as a user caption | A tap is context for the brain, not speech |
| Every delegation is answered, with "Sorry…" if the brain fails or heard nothing | Otherwise GPT-Live waits forever |
| Stop doesn't cancel a running brain turn; its reply is dropped | Cancelling mid-turn can strand a tool call in the remote session |
| A failed tool-result submit fails the turn (the user hears "Sorry") | Replaying the turn in a new session would repeat side-effecting tools |
| Only mic audio is capped in the GPT-Live command queue; commands are never dropped | A stalled provider must not lose spoken replies or the close command |
| `end_conversation` doesn't pause always-listening; taps don't undo Stop | Stop is the user's explicit pause; a goodbye only ends the current session |
| The Today screen renders only while a phone is attached; `DELETE /api/pages/<id>` returns 204/404 | Nothing to show without a phone; the agent page expects 204 |
| Uvicorn log lines have `token=` redacted | Uvicorn logs the WebSocket path even with `--no-access-log` |
| Memory saves and calls to other people need the user's own words, in code | Ambient talk is never stored; outward actions need consent |

## Companion habits (October 8, 2026)

| Decision | Why |
| --- | --- |
| Reminders reuse check-ins with a `Reminder: ` prefix and an optional `repeat` (`daily`, `weekdays`) | One scheduler, offline delivery and away calls for free; the prefix keeps the phone's focus timer and screens correct |
| Repeats keep the local clock time across daylight-saving changes; missed occurrences are skipped, not replayed | "Every weekday at 9" should mean 9, and a week offline shouldn't produce five reminders |
| The phone shows a reminder as a notice, not the focus check-in screen | That screen's timer and "10 more minutes" buttons don't fit a reminder |
| Welcome-back, briefing and break nudges are skipped only during an actual conversation (speech in the last 30 s, a brain turn, a call), not whenever a voice session is open | With always-listening a session is always open, so a "session open" test switched these off for good |
| Morning briefing: first sighting each day after 5 AM, at most once a day (stored), never in quiet hours | Useful at the start of the day, never a wake-up call |
| Break nudge after `BREAK_AFTER_MINUTES` (50) seen at the desk; absences under 2 minutes don't reset it; at most once per stretch | A nudge, not nagging |
| Quiet hours apply to everything Toad starts on its own, not only calls | Toad shouldn't start talking at night |
| Changes to the user's apps (Composio tools named `…_SEND_…`, `…_CREATE_…`, `…_DELETE_…` and similar) are refused unless the user's latest words are a yes to Toad's question | The confirm-before-writing rule was prompt-only; now it holds even if the model forgets |
| Finished to-dos are kept for a week | Enough for "what did I get done?", without the list growing forever |
| New behaviors default off in the test rig and are enabled per test | Each behavior is tested in isolation |

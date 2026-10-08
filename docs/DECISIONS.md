# Rebuild decisions

| Decision | Status |
| --- | --- |
| Python server, Kotlin Android | Requested by user |
| Fresh sibling repository | Requested by user |
| Toad name; `com.toad.companion`; moss-green toad | Initial implementation choice; easy to revise before Android migration |
| Both original operating modes | Required for whole-project parity |
| File-backed storage, one worker/device | Baseline parity decision |
| Exact source voice/saved-agent provider support | Unverified; milestone 1 gate |
| Existing behavior gaps | See implementation plan; no silent behavior changes approved |

Append dated decisions when implementation changes behavior or provider architecture.

## October 8, 2026 — engine parity batch

| Decision | Why |
| --- | --- |
| Port Desku's engine behavior exactly: brain message prefixes (`[Heard]`, `[Tapped on the desk screen]`, `[Desk event]`), tool outputs and errors, voice instructions, Today screen, away calls, presence | Parity; the agent's instructions depend on these strings |
| A screen tap is not echoed to the phone as a user caption | Desku's behavior: a tap is context for the brain, not speech |
| Every delegation is answered, with "Sorry…" if the brain fails or heard nothing | Otherwise GPT-Live waits forever for the delegation result |
| Stop no longer cancels a running brain turn; its reply is dropped instead | Cancelling mid-turn can strand a tool call in the remote session and lose its context |
| The Today screen renders only while a phone is attached | Desku's `showToday` behavior |
| `DELETE /api/pages/<id>` returns 204/404 | Desku's behavior; the agent page expects it |
| Uvicorn log lines have `token=` redacted | Uvicorn logs the WebSocket path even with `--no-access-log` |
| Composio through its Python SDK (0.25, `sessions.create/use`, `execute(arguments=)`), called in a worker thread | The SDK is synchronous; shapes checked against the installed package |
| `store: false` kept in the GPT-Live session config | Documented field in the installed SDK; matches the privacy model |
| Keep `PROVIDER_MODE=fake` as the default | Lets the whole stack run with no keys; live mode is opt-in |
| Vendor Desku's `composio` skill byte-identical, add Toad-specific skills beside it | Keeps the upstream hash valid; Toad specifics live in `toad-*` skills |
| Only mic audio is bounded in the GPT-Live command queue; commands are never dropped | A stalled provider must not lose spoken replies or the close command |
| A failed tool-result submit fails the turn (the user hears "Sorry") | Desku's behavior; replaying in a new session would repeat side-effecting tools |
| `end_conversation` doesn't pause always-listening; taps don't undo Stop | Desku's behavior |

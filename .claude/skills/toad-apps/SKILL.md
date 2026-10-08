---
name: toad-apps
description: Toad's connected apps (Gmail, Google Calendar, Slack and 500+ more) through Composio, as wired into the Python engine. Use when enabling or debugging apps in Toad, connecting an app for the desk owner, reading a Composio error or log ID from the engine, or changing server/src/toad_server/apps.py. For general Composio product questions, use the composio skill.
---

# Toad's apps (Composio, Python)

This is the Toad-specific companion to the vendored `composio` skill (`.agents/skills/composio`, linked into `.claude/skills/`). That skill decides product and credentials; this one is how Toad uses them. Toad is a **Composio Platform** integration: one project key (`COMPOSIO_API_KEY`, `ak_…`) on the server, one stable user for the desk's single owner (`COMPOSIO_USER_ID`, default `toad-owner`). The key never reaches the phone.

## How it's wired

- `server/src/toad_server/apps.py` (`Apps`): on engine startup it reuses the saved session (`appsSessionId` in `DATA_DIR/toad.json`) or creates one, and turns the session's meta tools into function tools on the Toad agent: `COMPOSIO_SEARCH_TOOLS`, `COMPOSIO_GET_TOOL_SCHEMAS`, `COMPOSIO_MULTI_EXECUTE_TOOL`, `COMPOSIO_MANAGE_CONNECTIONS`. The remote sandbox tools are skipped. Results over 12,000 characters are truncated.
- When the agent calls one, `tools.py` forwards it to `Apps.run`; any Connect Link in the result goes to the phone as `{"type":"link"}`.
- `GET /api/overview` lists connections (cached 30 s, never while one is pending); `POST /api/apps/connect` `{"app":"gmail"}` returns a link for the agent page's buttons.

## Python SDK shapes (composio 0.25, checked against the installed package)

The Python SDK is synchronous; Toad calls it through `asyncio.to_thread`. Don't copy TypeScript names.

| Need | Python |
| --- | --- |
| client | `Composio(api_key=...)` (default OpenAI provider: tools are `{"type":"function","function":{...}}`) |
| new / reuse session | `composio.sessions.create(user_id=...)` / `composio.sessions.use(session_id)` |
| tools | `session.tools()` |
| run a tool | `session.execute(slug, arguments={...})` → `.data`, `.error`, `.log_id` |
| connect link | `session.authorize(toolkit)` → `.redirect_url`; `.wait_for_connection(timeout_seconds)` |
| connections | `composio.connected_accounts.list(user_ids=[...], limit=100)` → `.items[]` with `.toolkit.slug`, `.status`, `.is_disabled` |

Before changing these calls, re-check the installed package (`.venv/lib/python3.12/site-packages/composio/`) or current docs, as the composio skill requires. `server/tests/test_apps.py` pins the shapes with a fake SDK.

## Turn it on and connect an app

1. Put `COMPOSIO_API_KEY` in `.env` (check it's set without printing it: `grep -c '^COMPOSIO_API_KEY=.' .env`). Restart the engine; the log says `apps: session … (N tools)`.
2. Connect apps from the agent page (`/agent.html` → Connect an app), or the terminal:

```bash
.venv/bin/python server/scripts/connect_app.py googlecalendar     # prints a link, waits for approval
.venv/bin/python server/scripts/smoke_apps.py "What's on my calendar today?"   # paid OpenAI call
```

Connecting writes to the owner's Composio account; confirm with the user first. Inside the locked kiosk, links can't open a browser, so connect from a computer.

## Rules that stay in force

- Reading is fine when asked; before sending, posting, creating, changing or deleting anything, Toad says exactly what it will do and waits for a yes (agent instructions; not yet enforced in code).
- Errors carry Composio's log ID (`… (Composio log log_…)`): get it before diagnosing, per the composio skill's errors reference.

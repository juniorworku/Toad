# Toad on the OpenAI Agents API

`toad_agent.py` is a small single-file terminal app that calls the [Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview) directly with `httpx`. It does the following:

- saves a reusable agent named **Toad** from `toad-agent.json`
- starts sessions from that agent's ID
- streams output and events
- answers Toad's function calls locally
- handles errors

`toad-agent.json` is the single definition of Toad's agent. The engine in `../server/` creates or updates the saved agent from it on startup (`PROVIDER_MODE=openai`) and keeps its own session; this app saves its own agent ID and session in `agent/state/`, separate from the engine's. To check the definition against the server's tools, run `.venv/bin/python .claude/skills/toad-agent/scripts/check_agent.py`.

## Setup

You need the repo's Python 3.12 virtualenv (`.venv`) with `httpx`. The app uses nothing else outside the standard library. Run the commands below from the repo root.

```bash
cp agent/.env.example agent/.env
```

Fill in `agent/.env`:

| Variable | Required | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | yes | Needs the `api.agents.read`, `api.agents.write` and `api.responses.write` permissions |
| `OPENAI_PROJECT` | no | Your own project ID (`proj_...`). If it's blank, no `OpenAI-Project` header is sent and the key's default project is used |
| `TOAD_TZ` | no | IANA time zone for the time Toad reports, e.g. `America/New_York`. If it's blank, the system zone is used |
| `OPENAI_BASE_URL` | no | Defaults to `https://api.openai.com/v1` |

Values in `agent/.env` override variables exported in your shell, like `set -a; . .env` does in the bash version. You can also skip the file and export the variables. `agent/.env` and `agent/state/` are gitignored.

## Run

```bash
.venv/bin/python agent/toad_agent.py create-agent
```

This saves the agent from `toad-agent.json` and writes its ID to `agent/state/agent_id`. Running it again reuses that agent. Pass `--force` to create a new one after you edit the JSON. Changes to a saved agent only apply to new sessions.

```bash
.venv/bin/python agent/toad_agent.py start "Hey Toad, I'm working on the grant intro for 25 minutes. Check in on me after."
```

This creates a session with `agent_id` and `environment: {type: "none"}`, sends the message, and streams the first turn. If you don't pass a message, it sends `Hi Toad, I just sat down at my desk.`

```bash
.venv/bin/python agent/toad_agent.py say "Remember the grant is due Friday at noon. What was I working on?"
```

This subscribes to the session's event stream, then sends a follow-up.

| Command | What it does |
|---|---|
| `create-agent [--force]` | Saves the agent, or reuses the saved one |
| `start ["message"]` | Starts a new session from the saved agent and streams the first turn |
| `say "message"` | Sends a follow-up to the current session and streams the reply |
| `chat` | Interactive loop on the current session. Starts a session if there isn't one |
| `tick` | Sends any due check-ins to Toad, which then checks in with you. Run it from cron, e.g. `* * * * * cd /path/to/Toad && .venv/bin/python agent/toad_agent.py tick` |
| `status` | Session status, error and pending required actions |
| `items` | Saved messages and tool calls |
| `cancel` | Cancels the active turn |
| `end` | Deletes the session |

Run the app with no arguments, or with an unknown command, to print the usage.

## How it works

- **Environment `none`.** Toad answers, searches the web and calls your functions. It doesn't run code or touch files, so it needs no sandbox, runtime or executor.
- **Requests.** Every request sends these headers:
  - `Authorization: Bearer …`
  - `OpenAI-Beta: agents=v1`
  - `Content-Type: application/json`
  - `OpenAI-Project`, only when `OPENAI_PROJECT` is set
- **Tools.** Web search runs on OpenAI's side. Four function tools run in this app against `agent/state/desk.json`:
  - `get_desk_status`: time, focus, memories and check-ins
  - `set_focus`: records the task and optionally schedules a check-in
  - `save_memory`
  - `delete_memory`

  Other tools return an error, and Toad tells you it can't do that here:
  - `look_through_camera`: the terminal has no camera.
  - `call_phone`, `control_desk` and `show_page` run through the Toad server in `../server/`.
  - The to-do tools (`add_todo`, `complete_todo`, `remove_todo`, `show_today`) also run through the server.
  - `COMPOSIO_*` app tools also run through the server.

  On `agent.session.requires_action`, the app retrieves the session and runs each pending `function_call` from `required_actions`. It then posts an `agent.session.input.tool_result` with the same `turn_id` and `call_id`. A tool failure goes back as `success: false` with an error message, so Toad can recover. Answered call IDs are recorded in `agent/state/answered_calls` so they aren't answered twice.
- **Streaming.** The app reads the server-sent `data:` lines:
  - `output_text.delta` is printed as Toad's reply.
  - Reasoning summaries and all other event types are printed dimmed to stderr.
  - The turn ends on `agent.session.turn.completed`.
  - `turn.failed`, `turn.cancelled`, `session.failed`, `environment.failed` and `error` events stop the app with a message and a non-zero exit code.
  - If the stream closes early, the app prints the saved session status.

  `say` opens the event stream on a background thread first. It waits up to one second for the connection, then posts the message, so it doesn't miss the turn's first events.
- **Errors and retries.** HTTP errors print as `code: message (param: x)`. Network failures, 429s and 500/502/503/504 responses are retried up to 4 times with exponential backoff (2, 4, 8 and 16 seconds). Message posts send a random `Idempotency-Key`, and tool-result posts send `tool-<call_id>`, so a retry can't create a duplicate.
- **Colors.** Output is only colored when stdout is a terminal.

## State

| File | Contents |
|---|---|
| `state/agent_id` | The saved agent's ID |
| `state/session_id` | The current session's ID |
| `state/desk.json` | Focus, memories and check-ins. Starts as `{"memories":[],"focus":null,"checkins":[]}`. Timestamps are epoch seconds (`started_at`, `due_at`, `created_at`) |
| `state/answered_calls` | Function call IDs that have already been answered |

## Testing

```bash
.venv/bin/python -m pytest agent/tests -q
.venv/bin/python -m ruff check agent
.venv/bin/python -m ruff format --line-length 100 agent
.venv/bin/python -m mypy --strict agent/toad_agent.py
```

The tests in `tests/test_toad_agent.py` use `httpx.MockTransport` and a temporary state directory. They need no network or real key. They cover:

- creating, reusing and recreating the agent
- a streamed turn with a `set_focus` call
- tool errors
- retries and HTTP error formatting
- `tick`
- the local tools

## Verified

This app has been verified against mocked API responses only, and against a local stand-in server for the threaded `say` stream. It has not been run against the live Agents API yet. The bash original it was ported from was tested live.

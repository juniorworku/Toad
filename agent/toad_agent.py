#!/usr/bin/env python3
"""Toad on the OpenAI Agents API, driven from Python with httpx.

  toad_agent.py create-agent [--force]   save the reusable "Toad" agent, remember its ID
  toad_agent.py start ["message"]        new session from the saved agent, stream the first turn
  toad_agent.py say "message"            send a follow-up to the current session and stream it
  toad_agent.py chat                     interactive loop on the current session
  toad_agent.py tick                     deliver due check-ins to the session (run from cron)
  toad_agent.py status | items | cancel | end

Function tools (get_desk_status, set_focus, save_memory, delete_memory) run here, against
state/desk.json. Credentials come from OPENAI_API_KEY (or agent/.env, which is gitignored).
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import math
import os
import queue
import sys
import threading
import time
import uuid
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

HERE = Path(__file__).resolve().parent
DEFAULT_API = "https://api.openai.com/v1"
DEFAULT_MESSAGE = "Hi Toad, I just sat down at my desk."
EMPTY_DB = '{"memories":[],"focus":null,"checkins":[]}\n'
RETRY_CODES = {"000", "429", "500", "502", "503", "504"}
MAX_RETRIES = 4
NETWORK_ERROR = '{"error":{"code":"network_error","message":"could not reach the API"}}'
SERVER_ONLY = (
    "Phone calls, desk controls and pages run through the Toad server in server/, "
    "not this terminal app."
)
COMPOSIO_ONLY = "Apps (Composio) run through the Toad server in server/, not this terminal app."
TODOS_ONLY = "To-dos run through the Toad server in server/, not this terminal app."
NO_CAMERA = "No camera in the terminal app. Ask the user to describe or paste it instead."
REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=30.0)
STREAM_TIMEOUT = httpx.Timeout(120.0, connect=30.0, read=None)


class ApiError(Exception):
    """An API call failed after retries; the error line has already been printed."""


class NoSession(Exception):
    """There is no saved session to talk to."""


class ToolError(Exception):
    """A function tool failed; the message goes back to the agent with success false."""


# ---------------------------------------------------------------- small helpers


def compact(value: Any) -> str:
    """JSON like `jq -c`."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def text_of(value: Any) -> str:
    """A value as `jq -r` prints it: strings raw, everything else as JSON."""
    return value if isinstance(value, str) else compact(value)


def present(value: Any) -> bool:
    """jq's truthiness for `//`: everything except null and false."""
    return value is not None and value is not False


def first_present(*values: Any) -> Any:
    for value in values:
        if present(value):
            return value
    return values[-1] if values else None


def get(value: Any, *keys: str) -> Any:
    """Nested `.a.b` lookup that yields None (jq null) for anything missing."""
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def explain_error(body: str) -> str:
    """Turn an API error body into one readable line: "code: message (param: x)"."""
    try:
        data = json.loads(body)
    except ValueError:
        return body
    err = first_present(get(data, "error"), data)
    if not isinstance(err, dict):
        return text_of(err)
    code = first_present(err.get("code"), err.get("type"), "error")
    message = first_present(err.get("message"), compact(err))
    param = f" (param: {text_of(err['param'])})" if present(err.get("param")) else ""
    return f"{text_of(code)}: {text_of(message)}{param}"


def load_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser for agent/.env (comments, `export`, quotes)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            values[key] = value
    return values


def format_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return text_of(value)


def as_number(value: Any) -> int | float | None:
    """Accept a JSON number, or a string holding one (like `--argjson` would)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        if isinstance(parsed, int | float) and not isinstance(parsed, bool):
            return parsed
    return None


# ---------------------------------------------------------------- config


@dataclass
class Config:
    api_key: str
    base_url: str = DEFAULT_API
    project: str = ""
    tz_name: str = ""
    state_dir: Path = HERE / "state"
    agent_file: Path = HERE / "toad-agent.json"

    @classmethod
    def from_env(cls, env: Mapping[str, str], state_dir: Path | None = None) -> Config:
        return cls(
            api_key=env.get("OPENAI_API_KEY", ""),
            base_url=(env.get("OPENAI_BASE_URL") or DEFAULT_API).rstrip("/"),
            project=env.get("OPENAI_PROJECT", ""),
            tz_name=env.get("TOAD_TZ", ""),
            state_dir=state_dir or HERE / "state",
        )


def make_client() -> httpx.Client:
    """Default HTTP client. Tests pass their own (with httpx.MockTransport) instead."""
    return httpx.Client(timeout=REQUEST_TIMEOUT)


# ---------------------------------------------------------------- the app


class ToadAgent:
    def __init__(
        self,
        config: Config,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        new_key: Callable[[], str] = lambda: str(uuid.uuid4()),
        subscribe_wait: float = 1.0,
    ) -> None:
        self.config = config
        self.client = client
        self.sleep = sleep
        self.clock = clock
        self.new_key = new_key
        self.subscribe_wait = subscribe_wait
        self.quiet = False
        self.state = config.state_dir
        self.db_path = self.state / "desk.json"
        self.state.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self.db_path.write_text(EMPTY_DB, encoding="utf-8")
        tty = sys.stdout.isatty()
        self.dim, self.red, self.bold, self.off = (
            ("\033[2m", "\033[31m", "\033[1m", "\033[0m") if tty else ("", "", "", "")
        )
        self.headers = {
            "Authorization": f"Bearer {config.api_key}",
            "OpenAI-Beta": "agents=v1",
            "Content-Type": "application/json",
        }
        if config.project:
            self.headers["OpenAI-Project"] = config.project

    # -------------------------------------------------------------- output

    def log(self, message: str) -> None:
        if self.quiet:
            return
        print(f"{self.dim}{message}{self.off}", file=sys.stderr, flush=True)

    def fail(self, message: str) -> None:
        if self.quiet:
            return
        print(f"{self.red}Error:{self.off} {message}", file=sys.stderr, flush=True)

    def out(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    # -------------------------------------------------------------- HTTP

    def api(self, method: str, path: str, body: Any = None, key: str | None = None) -> Any:
        """Call the API and return the parsed body (raw text if it isn't JSON).

        Retries 429/5xx and network failures with backoff; the idempotency key makes retried
        POSTs safe. Raises ApiError after printing the error line.
        """
        headers = dict(self.headers)
        if key:
            headers["Idempotency-Key"] = key
        content = compact(body) if body is not None else None
        attempt = 0
        while True:
            try:
                response = self.client.request(
                    method, self.config.base_url + path, headers=headers, content=content
                )
                code, out = str(response.status_code), response.text
            except httpx.TransportError:
                code, out = "000", NETWORK_ERROR
            if code.startswith("2") and len(code) == 3:
                if not out.strip():
                    return None
                try:
                    return json.loads(out)
                except ValueError:
                    return out
            if code in RETRY_CODES:
                attempt += 1
                if attempt <= MAX_RETRIES:
                    delay = 2**attempt
                    self.log(f"HTTP {code} ({explain_error(out)}), retrying in {delay}s")
                    self.sleep(delay)
                    continue
            self.fail(f"HTTP {code} on {method} {path}: {explain_error(out)}")
            raise ApiError(code)

    def stream_lines(
        self,
        method: str,
        path: str,
        body: Any,
        errors: list[str],
        on_connect: Callable[[httpx.Response], None] | None = None,
    ) -> Generator[str, None, None]:
        """Yield the lines of a server-sent event stream. Not retried, like `curl -N`.

        Transport errors end the iteration and are recorded in `errors`. An HTTP error comes
        through as one compact JSON line, which follow_stream reports.
        """
        headers = {**self.headers, "Accept": "text/event-stream"}
        content = compact(body) if body is not None else None
        try:
            with self.client.stream(
                method,
                self.config.base_url + path,
                headers=headers,
                content=content,
                timeout=STREAM_TIMEOUT,
            ) as response:
                if on_connect:
                    on_connect(response)
                if not response.is_success:
                    text = response.read().decode("utf-8", errors="replace")
                    try:
                        yield compact(json.loads(text))
                    except ValueError:
                        yield compact(
                            {
                                "error": {
                                    "code": f"http_{response.status_code}",
                                    "message": text.strip()[:500],
                                }
                            }
                        )
                    return
                yield from response.iter_lines()
        except httpx.TransportError as exc:
            errors.append(str(exc) or type(exc).__name__)

    # -------------------------------------------------------------- state

    def read_db(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.db_path.read_text(encoding="utf-8"))
        return data

    def write_db(self, data: dict[str, Any]) -> None:
        tmp = self.db_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.db_path)

    def read_state(self, name: str) -> str:
        path = self.state / name
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    def session_id(self) -> str:
        sid = self.read_state("session_id")
        if not sid:
            self.fail("No session yet. Run: toad_agent.py start")
            raise NoSession
        return sid

    def now(self) -> int:
        return int(self.clock())

    def now_text(self) -> str:
        """Like `date '+%A %B %-d, %-I:%M %p %Z'`, in TOAD_TZ when set."""
        moment = datetime.fromtimestamp(self.clock()).astimezone()
        if self.config.tz_name:
            try:
                moment = moment.astimezone(ZoneInfo(self.config.tz_name))
            except (ZoneInfoNotFoundError, ValueError):
                pass
        hour = moment.hour % 12 or 12
        return f"{moment:%A %B} {moment.day}, {hour}:{moment:%M %p %Z}"

    # -------------------------------------------------------------- function tools

    def run_tool(self, name: str, args: dict[str, Any]) -> str:
        """Run one function tool and return its result. Raises ToolError on failure."""
        now = self.now()
        if name == "get_desk_status":
            db = self.read_db()
            focus = db.get("focus")
            checkins = db.get("checkins") or []
            focus_status = None
            if isinstance(focus, dict):
                focus_status = {
                    "task": focus.get("task"),
                    "minutes_ago": math.floor((now - focus["started_at"]) / 60),
                }
            return compact(
                {
                    "local_time": self.now_text(),
                    "focus": focus_status,
                    "memories": [
                        {"id": m.get("id"), "text": m.get("text")} for m in db.get("memories") or []
                    ],
                    "due_checkins": [c.get("about") for c in checkins if c["due_at"] <= now],
                    "upcoming_checkins": [
                        {"about": c.get("about"), "in_minutes": math.ceil((c["due_at"] - now) / 60)}
                        for c in checkins
                        if c["due_at"] > now
                    ],
                }
            )
        if name == "set_focus":
            task = text_of(args["task"]) if present(args.get("task")) else ""
            if not task:
                raise ToolError("task is required")
            raw_minutes = args.get("checkin_minutes")
            minutes = None
            if present(raw_minutes):
                minutes = as_number(raw_minutes)
                if minutes is None:
                    raise ToolError("checkin_minutes must be a number")
            db = self.read_db()
            db["focus"] = {"task": task, "started_at": now}
            checkins = [
                c
                for c in db.get("checkins") or []
                if not str(c.get("about", "")).startswith("Focus check-in")
            ]
            if minutes is not None:
                checkins.append(
                    {
                        "id": f"c{now}",
                        "due_at": now + minutes * 60,
                        "about": f"Focus check-in: {task}",
                    }
                )
            db["checkins"] = checkins
            self.write_db(db)
            if minutes is not None:
                return f"Focus set. Check-in scheduled in {format_number(raw_minutes)} minutes."
            return "Focus set. No check-in scheduled."
        if name == "save_memory":
            text = text_of(args["text"]) if present(args.get("text")) else ""
            if not text:
                raise ToolError("text is required")
            db = self.read_db()
            memories = db.setdefault("memories", [])
            numbers = [int(str(m["id"]).removeprefix("m")) for m in memories]
            new_id = f"m{max(numbers, default=0) + 1}"
            memories.append({"id": new_id, "text": text, "created_at": now})
            self.write_db(db)
            return f"Saved as {new_id}."
        if name == "delete_memory":
            memory_id = text_of(args["id"]) if present(args.get("id")) else ""
            db = self.read_db()
            memories = db.get("memories") or []
            if not any(m.get("id") == memory_id for m in memories):
                raise ToolError(f"No memory with id {memory_id}")
            db["memories"] = [m for m in memories if m.get("id") != memory_id]
            self.write_db(db)
            return f"Deleted {memory_id}."
        if name in (
            "call_phone",
            "control_desk",
            "show_page",
            "finish_focus",
            "set_reminder",
            "cancel_reminder",
        ):
            raise ToolError(SERVER_ONLY)
        if name.startswith("COMPOSIO_"):
            raise ToolError(COMPOSIO_ONLY)
        if name in ("add_todo", "complete_todo", "remove_todo", "show_today"):
            raise ToolError(TODOS_ONLY)
        if name == "look_through_camera":
            raise ToolError(NO_CAMERA)
        raise ToolError(f"Unknown function {name}")

    def handle_required_actions(self, sid: str) -> bool:
        """Answer every pending function call on the session (on requires_action)."""
        try:
            session = self.api("GET", f"/agents/sessions/{sid}")
        except ApiError:
            return False
        required = get(session, "required_actions") or []
        actions = [a for a in required if isinstance(a, dict) and a.get("type") == "function_call"]
        if not actions:
            self.fail(
                "Session needs an action this app doesn't handle: "
                + compact(get(session, "required_actions"))
            )
            return False
        answered_path = self.state / "answered_calls"
        for action in actions:
            name = text_of(action.get("name"))
            call_id = text_of(action.get("call_id"))
            turn_id = text_of(action.get("turn_id"))
            answered = (
                answered_path.read_text(encoding="utf-8").splitlines()
                if (answered_path.is_file())
                else []
            )
            if call_id in answered:
                continue
            # arguments arrive as an object; accept a JSON string too.
            raw = action.get("arguments")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = None
            args: dict[str, Any] = raw if isinstance(raw, dict) else {}
            self.log(f"→ tool {name} {compact(args)}")
            try:
                result, ok = self.run_tool(name, args), True
            except ToolError as exc:
                result, ok = str(exc), False
            except (OSError, ValueError, KeyError, TypeError) as exc:  # e.g. a broken desk.json
                result, ok = f"{type(exc).__name__}: {exc}", False
            self.log(f"← {result}")
            event = {
                "events": [
                    {
                        "type": "agent.session.input.tool_result",
                        "call_id": call_id,
                        "turn_id": turn_id,
                        "success": ok,
                        "output": result if ok else None,
                        "error": None if ok else result,
                    }
                ]
            }
            try:
                self.api("POST", f"/agents/sessions/{sid}/events", event, f"tool-{call_id}")
            except ApiError:
                return False
            with answered_path.open("a", encoding="utf-8") as fh:
                fh.write(call_id + "\n")
        return True

    # -------------------------------------------------------------- streaming

    def follow_stream(self, lines: Iterable[str]) -> bool:
        """Read server-sent events until the turn ends.

        Prints the agent's text to stdout and everything else, dimmed, to stderr. Returns True
        only for agent.session.turn.completed.
        """
        printed = False
        for raw in lines:
            line = raw.rstrip("\r")
            if line.startswith("data:"):
                data = line[5:].removeprefix(" ")
            elif line.startswith("{"):  # HTTP error body instead of a stream
                self.fail(explain_error(line))
                return False
            else:
                continue
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = text_of(event["type"]) if present(event.get("type")) else ""

            if not self.read_state("session_id"):
                sid = first_present(get(event, "session", "id"), event.get("session_id"))
                if present(sid):
                    (self.state / "session_id").write_text(text_of(sid) + "\n", encoding="utf-8")
                    self.log(f"session {text_of(sid)}")

            if kind == "agent.session.turn.output_text.delta":
                if not printed:
                    self.out(f"{self.bold}Toad:{self.off} ")
                self.out(text_of(event.get("delta")))
                printed = True
            elif kind == "agent.session.turn.output_text.done":
                if not printed:
                    self.out(f"{self.bold}Toad:{self.off} {text_of(event.get('text'))}")
                self.out("\n")
                printed = False
            elif fnmatch.fnmatchcase(kind, "*reasoning_summary*delta"):
                sys.stderr.write(f"{self.dim}{text_of(event.get('delta'))}{self.off}")
                sys.stderr.flush()
            elif fnmatch.fnmatchcase(kind, "*reasoning_summary*done"):
                sys.stderr.write("\n")
                sys.stderr.flush()
            elif kind == "agent.session.requires_action":
                self.log(f"[{kind}]")
                if not self.handle_required_actions(self.session_id()):
                    return False
            elif kind == "agent.session.turn.completed":
                self.log("[turn completed]")
                return True
            elif kind in ("agent.session.turn.failed", "agent.session.turn.cancelled"):
                detail = first_present(
                    get(event, "turn", "error"),
                    event.get("error"),
                    get(event, "turn", "status"),
                    event,
                )
                self.fail(f"{kind}: {compact(detail)}")
                return False
            elif kind in ("agent.session.failed", "agent.session.environment.failed"):
                detail = first_present(
                    get(event, "session", "error"),
                    get(event, "environment", "error"),
                    event.get("error"),
                    event,
                )
                self.fail(f"{kind}: {compact(detail)}")
                return False
            elif kind == "error":
                self.fail(f"stream error: {explain_error(data)}")
                return False
            else:
                self.log(f"[{kind}]")
        # The stream ended without a turn outcome. Saved state says what actually happened.
        self.fail("Stream closed before the turn finished.")
        sid = self.read_state("session_id")
        if sid:
            try:
                session = self.api("GET", f"/agents/sessions/{sid}")
            except ApiError:
                session = None
            if isinstance(session, dict):
                summary = {k: session.get(k) for k in ("status", "error", "required_actions")}
                self.log(f"Session status: {compact(summary)}")
        return False

    def run_stream(self, lines: Iterable[str], errors: list[str]) -> bool:
        """follow_stream; connection errors are shown only if the turn didn't complete."""
        ok = self.follow_stream(lines)
        if not ok and errors:
            self.log(f"connection: {'; '.join(errors)}")
        return ok

    # -------------------------------------------------------------- commands

    def create_agent(self, force: bool = False) -> str:
        agent_id = self.read_state("agent_id")
        if not force and agent_id:
            if self._agent_exists(agent_id):
                self.log(f"Using saved agent {agent_id} (--force to recreate)")
                return agent_id
            self.log(f"Saved agent {agent_id} is gone; creating a new one.")
        definition = json.loads(self.config.agent_file.read_text(encoding="utf-8"))
        agent = self.api("POST", "/agents", definition)
        new_id = text_of(get(agent, "id"))
        (self.state / "agent_id").write_text(new_id + "\n", encoding="utf-8")
        self.log(
            f"Created agent {new_id} ({text_of(get(agent, 'name'))}, "
            f"{text_of(get(agent, 'model'))})"
        )
        return new_id

    def _agent_exists(self, agent_id: str) -> bool:
        """GET the saved agent with retries, without printing anything (`2>/dev/null`)."""
        self.quiet = True
        try:
            self.api("GET", f"/agents/{agent_id}")
            return True
        except ApiError:
            return False
        finally:
            self.quiet = False

    def start(self, message: str = "") -> bool:
        message = message or DEFAULT_MESSAGE
        agent_id = self.create_agent()
        (self.state / "session_id").unlink(missing_ok=True)
        print(f"{self.bold}You:{self.off} {message}", flush=True)
        # Environment "none": Toad talks, searches and calls our functions; it needs no sandbox.
        body = {
            "agent_id": agent_id,
            "environment": {"type": "none"},
            "input": message,
            "stream": True,
            "metadata": {"app": "toad"},
        }
        errors: list[str] = []
        lines = self.stream_lines("POST", "/agents/sessions", body, errors)
        try:
            return self.run_stream(lines, errors)
        finally:
            lines.close()

    def say(self, message: str) -> bool:
        sid = self.session_id()
        print(f"{self.bold}You:{self.off} {message}", flush=True)
        # Subscribe first so the turn's early events aren't missed, then send.
        subscription = _BackgroundStream(self, f"/agents/sessions/{sid}/events?stream=true")
        subscription.connected.wait(self.subscribe_wait)
        body = {
            "events": [
                {
                    "type": "agent.session.input.message",
                    "input": [
                        {"role": "user", "content": [{"type": "input_text", "text": message}]}
                    ],
                }
            ]
        }
        try:
            self.api("POST", f"/agents/sessions/{sid}/events", body, self.new_key())
            return self.run_stream(subscription.lines(), subscription.errors)
        except ApiError:
            return False
        finally:
            subscription.close()

    def tick(self) -> bool:
        now = self.now()
        db = self.read_db()
        checkins = db.get("checkins") or []
        due = "; ".join(text_of(c.get("about")) for c in checkins if c["due_at"] <= now)
        if not due:
            self.log("No check-ins due.")
            return True
        db["checkins"] = [c for c in checkins if c["due_at"] > now]
        self.write_db(db)
        return self.say(
            f"[Desk event, not typed by the user] Check-in due: {due}. Check in with the user now."
        )

    def chat(self) -> bool:
        if not self.read_state("session_id") and not self.start():
            return False
        interactive = sys.stdin.isatty()
        while True:
            if interactive:
                sys.stdout.write("> ")
                sys.stdout.flush()
            line = sys.stdin.readline()
            if not line:
                return True
            message = line.rstrip("\n")
            if message:
                try:
                    self.say(message)
                except NoSession:
                    pass

    def status(self) -> None:
        session = self.api("GET", f"/agents/sessions/{self.session_id()}")
        summary = {k: get(session, k) for k in ("id", "status", "error", "required_actions")}
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    def items(self) -> None:
        page = self.api("GET", f"/agents/sessions/{self.session_id()}/items?order=asc&limit=100")
        print(json.dumps(get(page, "data"), indent=2, ensure_ascii=False))

    def cancel(self) -> None:
        body = {"events": [{"type": "agent.session.input.cancel"}]}
        result = self.api(
            "POST", f"/agents/sessions/{self.session_id()}/events", body, self.new_key()
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def end(self) -> None:
        self.api("DELETE", f"/agents/sessions/{self.session_id()}")
        (self.state / "session_id").unlink(missing_ok=True)
        self.log("Session deleted.")


class _BackgroundStream:
    """An event stream read on a thread, so `say` can subscribe before it posts."""

    def __init__(self, app: ToadAgent, path: str) -> None:
        self.errors: list[str] = []
        self.connected = threading.Event()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._response: httpx.Response | None = None
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(app, path), daemon=True)
        self._thread.start()

    def _on_connect(self, response: httpx.Response) -> None:
        self._response = response
        self.connected.set()

    def _run(self, app: ToadAgent, path: str) -> None:
        try:
            for line in app.stream_lines("GET", path, None, self.errors, self._on_connect):
                if self._closed.is_set():
                    break
                self._queue.put(line)
        except (httpx.HTTPError, httpx.StreamError, OSError, ValueError) as exc:
            # closed from the main thread, or a broken stream
            if not self._closed.is_set():
                self.errors.append(str(exc) or type(exc).__name__)
        finally:
            self.connected.set()
            self._queue.put(None)

    def lines(self) -> Iterator[str]:
        while (line := self._queue.get()) is not None:
            yield line

    def close(self) -> None:
        self._closed.set()
        if self._response is not None:
            with contextlib.suppress(httpx.HTTPError, httpx.StreamError, OSError, RuntimeError):
                self._response.close()


# ---------------------------------------------------------------- entry point


def usage() -> str:
    return (__doc__ or "").strip() + "\n"


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
    state_dir: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> int:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "help"
    commands = ("create-agent", "start", "say", "chat", "tick", "status", "items", "cancel", "end")
    if command not in commands:
        sys.stdout.write(usage())
        return 0
    if env is None:
        env = {**os.environ, **load_env_file(HERE / ".env")}
    config = Config.from_env(env, state_dir)
    if not config.api_key:
        print(
            "Error: OPENAI_API_KEY is not set. Export it, or create agent/.env from .env.example.",
            file=sys.stderr,
        )
        return 1
    app = ToadAgent(config, client or make_client(), sleep=sleep, clock=clock)
    arg = args[1] if len(args) > 1 else ""
    try:
        if command == "create-agent":
            print(app.create_agent(force=arg == "--force"))
            return 0
        if command == "start":
            return 0 if app.start(arg) else 1
        if command == "say":
            if not arg:
                app.fail('Usage: toad_agent.py say "message"')
                return 1
            return 0 if app.say(arg) else 1
        if command == "chat":
            return 0 if app.chat() else 1
        if command == "tick":
            return 0 if app.tick() else 1
        if command == "status":
            app.status()
        elif command == "items":
            app.items()
        elif command == "cancel":
            app.cancel()
        elif command == "end":
            app.end()
        return 0
    except (ApiError, NoSession):
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

"""Tests for agent/toad_agent.py against mocked Agents API responses (no network)."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import toad_agent

AGENT_DIR = Path(toad_agent.__file__).resolve().parent

NOW = 1_800_000_000
ENV = {"OPENAI_API_KEY": "sk-test", "OPENAI_BASE_URL": "https://api.test/v1"}

Route = Callable[[httpx.Request], httpx.Response]


def sse(*events: dict[str, Any]) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


class FakeApi:
    """Routes "METHOD /path" to queued responses and records every request."""

    def __init__(self) -> None:
        self.routes: dict[str, list[Route]] = {}
        self.requests: list[httpx.Request] = []

    def on(self, key: str, *responses: Route | httpx.Response) -> None:
        for response in responses:
            route = response if callable(response) else (lambda _r, resp=response: resp)
            self.routes.setdefault(key, []).append(route)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/v1")
        key = f"{request.method} {path}"
        queue = self.routes.get(key)
        if not queue:
            return httpx.Response(500, json={"error": {"message": f"unexpected {key}"}})
        route = queue.pop(0) if len(queue) > 1 else queue[0]
        return route(request)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def sent(self, method: str, path: str) -> list[httpx.Request]:
        return [
            r
            for r in self.requests
            if r.method == method and r.url.path.removeprefix("/v1") == path
        ]


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def state(tmp_path: Path) -> Path:
    return tmp_path / "state"


def run(
    api: FakeApi,
    state: Path,
    *argv: str,
    env: dict[str, str] | None = None,
    sleeps: list[float] | None = None,
) -> int:
    return toad_agent.main(
        list(argv),
        env=env or ENV,
        client=api.client(),
        state_dir=state,
        sleep=(sleeps.append if sleeps is not None else lambda _s: None),
        clock=lambda: NOW,
    )


def make_app(api: FakeApi, state: Path) -> toad_agent.ToadAgent:
    config = toad_agent.Config.from_env(ENV, state)
    return toad_agent.ToadAgent(config, api.client(), sleep=lambda _s: None, clock=lambda: NOW)


def desk(state: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((state / "desk.json").read_text())
    return data


def body(request: httpx.Request) -> Any:
    return json.loads(request.content)


AGENT = {"id": "agent_1", "name": "Toad", "model": "gpt-6-astra"}


# ---------------------------------------------------------------- create-agent


def test_create_agent_posts_definition_and_saves_id(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST /agents", httpx.Response(200, json=AGENT))
    assert run(api, state, "create-agent") == 0

    (request,) = api.sent("POST", "/agents")
    definition = json.loads((AGENT_DIR / "toad-agent.json").read_text())
    assert body(request) == definition
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert request.headers["OpenAI-Beta"] == "agents=v1"
    assert request.headers["Content-Type"] == "application/json"
    assert "OpenAI-Project" not in request.headers
    assert "Idempotency-Key" not in request.headers
    assert (state / "agent_id").read_text().strip() == "agent_1"
    out = capsys.readouterr()
    assert out.out == "agent_1\n"
    assert "Created agent agent_1 (Toad, gpt-6-astra)" in out.err
    assert json.loads((state / "desk.json").read_text()) == {
        "memories": [],
        "focus": None,
        "checkins": [],
    }


def test_create_agent_sends_project_header_when_set(api: FakeApi, state: Path) -> None:
    api.on("POST /agents", httpx.Response(200, json=AGENT))
    assert run(api, state, "create-agent", env={**ENV, "OPENAI_PROJECT": "proj_mine"}) == 0
    assert api.sent("POST", "/agents")[0].headers["OpenAI-Project"] == "proj_mine"


def test_create_agent_reuses_saved_agent(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state.mkdir()
    (state / "agent_id").write_text("agent_old\n")
    api.on("GET /agents/agent_old", httpx.Response(200, json={"id": "agent_old"}))
    assert run(api, state, "create-agent") == 0
    assert api.sent("POST", "/agents") == []
    out = capsys.readouterr()
    assert out.out == "agent_old\n"
    assert "Using saved agent agent_old (--force to recreate)" in out.err


def test_create_agent_recreates_when_saved_agent_is_gone(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state.mkdir()
    (state / "agent_id").write_text("agent_old\n")
    api.on("GET /agents/agent_old", httpx.Response(404, json={"error": {"type": "not_found"}}))
    api.on("POST /agents", httpx.Response(200, json=AGENT))
    assert run(api, state, "create-agent") == 0
    assert len(api.sent("POST", "/agents")) == 1
    assert (state / "agent_id").read_text().strip() == "agent_1"
    err = capsys.readouterr().err
    assert "Saved agent agent_old is gone; creating a new one." in err
    assert "HTTP 404" not in err  # the existence check is silent, like 2>/dev/null


def test_create_agent_force_skips_check(api: FakeApi, state: Path) -> None:
    state.mkdir()
    (state / "agent_id").write_text("agent_old\n")
    api.on("POST /agents", httpx.Response(200, json=AGENT))
    assert run(api, state, "create-agent", "--force") == 0
    assert api.sent("GET", "/agents/agent_old") == []


# ---------------------------------------------------------------- start + tools


def test_start_streams_turn_and_answers_set_focus(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST /agents", httpx.Response(200, json=AGENT))
    stream = sse(
        {"type": "agent.session.created", "session": {"id": "sess_1"}},
        {"type": "agent.session.turn.reasoning_summary_text.delta", "delta": "thinking"},
        {"type": "agent.session.turn.reasoning_summary_text.done"},
        {"type": "agent.session.requires_action"},
        {"type": "agent.session.turn.output_text.delta", "delta": "Got it"},
        {"type": "agent.session.turn.output_text.delta", "delta": ", go."},
        {"type": "agent.session.turn.output_text.done", "text": "Got it, go."},
        {"type": "agent.session.turn.completed"},
    )
    api.on(
        "POST /agents/sessions",
        httpx.Response(200, content=stream, headers={"Content-Type": "text/event-stream"}),
    )
    action = {
        "type": "function_call",
        "name": "set_focus",
        "call_id": "call_1",
        "turn_id": "turn_1",
        "arguments": json.dumps({"task": "grant intro", "checkin_minutes": 25}),
    }
    api.on(
        "GET /agents/sessions/sess_1",
        httpx.Response(200, json={"id": "sess_1", "required_actions": [action]}),
    )
    api.on("POST /agents/sessions/sess_1/events", httpx.Response(200, json={}))

    assert run(api, state, "start", "Working on the grant intro") == 0

    (create,) = api.sent("POST", "/agents/sessions")
    assert body(create) == {
        "agent_id": "agent_1",
        "environment": {"type": "none"},
        "input": "Working on the grant intro",
        "stream": True,
        "metadata": {"app": "toad"},
    }
    assert create.headers["Accept"] == "text/event-stream"

    (result,) = api.sent("POST", "/agents/sessions/sess_1/events")
    assert result.headers["Idempotency-Key"] == "tool-call_1"
    assert body(result) == {
        "events": [
            {
                "type": "agent.session.input.tool_result",
                "call_id": "call_1",
                "turn_id": "turn_1",
                "success": True,
                "output": "Focus set. Check-in scheduled in 25 minutes.",
                "error": None,
            }
        ]
    }

    db = desk(state)
    assert db["focus"] == {"task": "grant intro", "started_at": NOW}
    assert db["checkins"] == [
        {"id": f"c{NOW}", "due_at": NOW + 25 * 60, "about": "Focus check-in: grant intro"}
    ]
    assert (state / "session_id").read_text().strip() == "sess_1"
    assert (state / "answered_calls").read_text() == "call_1\n"

    out = capsys.readouterr()
    assert out.out == "You: Working on the grant intro\nToad: Got it, go.\n"
    assert "thinking" in out.err
    assert "[turn completed]" in out.err


def test_start_uses_default_message(api: FakeApi, state: Path) -> None:
    api.on("POST /agents", httpx.Response(200, json=AGENT))
    api.on(
        "POST /agents/sessions",
        httpx.Response(200, content=sse({"type": "agent.session.turn.completed"})),
    )
    assert run(api, state, "start") == 0
    assert body(api.sent("POST", "/agents/sessions")[0])["input"] == toad_agent.DEFAULT_MESSAGE


def test_start_reports_failed_turn(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST /agents", httpx.Response(200, json=AGENT))
    stream = sse(
        {"type": "agent.session.created", "session_id": "sess_1"},
        {"type": "agent.session.turn.failed", "turn": {"error": {"code": "boom"}}},
    )
    api.on("POST /agents/sessions", httpx.Response(200, content=stream))
    assert run(api, state, "start", "hi") == 1
    assert 'agent.session.turn.failed: {"code":"boom"}' in capsys.readouterr().err


def test_stream_closing_early_prints_session_status(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST /agents", httpx.Response(200, json=AGENT))
    stream = sse({"type": "agent.session.created", "session": {"id": "sess_1"}})
    api.on("POST /agents/sessions", httpx.Response(200, content=stream))
    api.on(
        "GET /agents/sessions/sess_1",
        httpx.Response(200, json={"id": "sess_1", "status": "running", "extra": 1}),
    )
    assert run(api, state, "start", "hi") == 1
    err = capsys.readouterr().err
    assert "Stream closed before the turn finished." in err
    assert 'Session status: {"status":"running","error":null,"required_actions":null}' in err


def test_stream_http_error_body_is_explained(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST /agents", httpx.Response(200, json=AGENT))
    api.on(
        "POST /agents/sessions",
        httpx.Response(400, json={"error": {"code": "bad_input", "message": "nope"}}),
    )
    assert run(api, state, "start", "hi") == 1
    assert "bad_input: nope" in capsys.readouterr().err


# ---------------------------------------------------------------- say + tool errors


def session(state: Path, sid: str = "sess_1") -> None:
    state.mkdir(exist_ok=True)
    (state / "session_id").write_text(sid + "\n")


def test_say_subscribes_then_posts_and_reports_tool_error(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session(state)
    stream = sse(
        {"type": "agent.session.requires_action"},
        {"type": "agent.session.turn.output_text.done", "text": "What should I save?"},
        {"type": "agent.session.turn.completed"},
    )
    api.on("GET /agents/sessions/sess_1/events", httpx.Response(200, content=stream))
    action = {
        "type": "function_call",
        "name": "save_memory",
        "call_id": "call_9",
        "turn_id": "turn_2",
        "arguments": {"text": ""},
    }
    api.on("GET /agents/sessions/sess_1", httpx.Response(200, json={"required_actions": [action]}))
    api.on("POST /agents/sessions/sess_1/events", httpx.Response(200, json={}))

    assert run(api, state, "say", "remember this") == 0

    kinds = [(r.method, r.url.path) for r in api.requests]
    assert kinds[0] == ("GET", "/v1/agents/sessions/sess_1/events")
    assert api.requests[0].url.params["stream"] == "true"
    message, result = api.sent("POST", "/agents/sessions/sess_1/events")
    assert body(message) == {
        "events": [
            {
                "type": "agent.session.input.message",
                "input": [
                    {"role": "user", "content": [{"type": "input_text", "text": "remember this"}]}
                ],
            }
        ]
    }
    key = message.headers["Idempotency-Key"]
    assert len(key) == 36 and key.count("-") == 4
    assert result.headers["Idempotency-Key"] == "tool-call_9"
    event = body(result)["events"][0]
    assert event["success"] is False
    assert event["output"] is None
    assert event["error"] == "text is required"
    assert event["turn_id"] == "turn_2"
    assert desk(state)["memories"] == []
    assert capsys.readouterr().out == "You: remember this\nToad: What should I save?\n"


def test_already_answered_calls_are_skipped(api: FakeApi, state: Path) -> None:
    session(state)
    (state / "answered_calls").write_text("call_1\n")
    action = {"type": "function_call", "name": "get_desk_status", "call_id": "call_1"}
    api.on("GET /agents/sessions/sess_1", httpx.Response(200, json={"required_actions": [action]}))
    assert make_app(api, state).handle_required_actions("sess_1") is True
    assert api.sent("POST", "/agents/sessions/sess_1/events") == []


def test_unhandled_required_action_fails(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session(state)
    api.on(
        "GET /agents/sessions/sess_1",
        httpx.Response(200, json={"required_actions": [{"type": "approval"}]}),
    )
    assert make_app(api, state).handle_required_actions("sess_1") is False
    assert "Session needs an action this app doesn't handle" in capsys.readouterr().err


def test_say_requires_message_and_session(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(api, state, "say") == 1
    assert "Usage" in capsys.readouterr().err
    assert run(api, state, "say", "hi") == 1
    assert "No session yet" in capsys.readouterr().err


# ---------------------------------------------------------------- retries and errors


def test_retries_on_503_then_succeeds(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session(state)
    api.on(
        "GET /agents/sessions/sess_1",
        httpx.Response(503, json={"error": {"code": "overloaded", "message": "busy"}}),
        httpx.Response(503, text="Service Unavailable"),
        httpx.Response(200, json={"id": "sess_1", "status": "idle", "secret": "x"}),
    )
    sleeps: list[float] = []
    assert run(api, state, "status", sleeps=sleeps) == 0
    assert sleeps == [2, 4]
    out = capsys.readouterr()
    assert json.loads(out.out) == {
        "id": "sess_1",
        "status": "idle",
        "error": None,
        "required_actions": None,
    }
    assert "HTTP 503 (overloaded: busy), retrying in 2s" in out.err
    assert "HTTP 503 (Service Unavailable), retrying in 4s" in out.err


def test_retries_network_errors_and_gives_up(
    state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session(state)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    sleeps: list[float] = []
    code = toad_agent.main(
        ["status"],
        env=ENV,
        client=httpx.Client(transport=httpx.MockTransport(down)),
        state_dir=state,
        sleep=sleeps.append,
        clock=lambda: NOW,
    )
    assert code == 1
    assert sleeps == [2, 4, 8, 16]
    err = capsys.readouterr().err
    assert (
        "Error: HTTP 000 on GET /agents/sessions/sess_1: network_error: could not reach the API"
        in err
    )


def test_http_404_is_formatted(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session(state, "sess_bad")
    api.on(
        "GET /agents/sessions/sess_bad",
        httpx.Response(
            404,
            json={
                "error": {
                    "type": "not_found_error",
                    "message": "No session found",
                    "param": "session_id",
                }
            },
        ),
    )
    sleeps: list[float] = []
    assert run(api, state, "status", sleeps=sleeps) == 1
    assert sleeps == []
    err = capsys.readouterr().err
    assert (
        "Error: HTTP 404 on GET /agents/sessions/sess_bad: "
        "not_found_error: No session found (param: session_id)"
    ) in err


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"error":{"code":"c","message":"m"}}', "c: m"),
        ('{"error":{"message":"m"}}', "error: m"),
        ('{"error":{"code":"c"}}', 'c: {"code":"c"}'),
        ('{"code":"c","message":"m","param":"p"}', "c: m (param: p)"),
        ('"plain"', "plain"),
        ("not json", "not json"),
    ],
)
def test_explain_error(raw: str, expected: str) -> None:
    assert toad_agent.explain_error(raw) == expected


# ---------------------------------------------------------------- tick


def test_tick_sends_due_checkins(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session(state)
    (state / "desk.json").write_text(
        json.dumps(
            {
                "memories": [],
                "focus": None,
                "checkins": [
                    {"id": "c1", "due_at": NOW - 60, "about": "Focus check-in: grant intro"},
                    {"id": "c2", "due_at": NOW + 600, "about": "Later"},
                ],
            }
        )
    )
    api.on(
        "GET /agents/sessions/sess_1/events",
        httpx.Response(200, content=sse({"type": "agent.session.turn.completed"})),
    )
    api.on("POST /agents/sessions/sess_1/events", httpx.Response(200, json={}))

    assert run(api, state, "tick") == 0

    (message,) = api.sent("POST", "/agents/sessions/sess_1/events")
    text = body(message)["events"][0]["input"][0]["content"][0]["text"]
    assert text == (
        "[Desk event, not typed by the user] Check-in due: Focus check-in: grant intro. "
        "Check in with the user now."
    )
    assert [c["id"] for c in desk(state)["checkins"]] == ["c2"]


def test_tick_with_nothing_due(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(api, state, "tick") == 0
    assert api.requests == []
    assert "No check-ins due." in capsys.readouterr().err


# ---------------------------------------------------------------- local tools


def test_unknown_function_returns_error(api: FakeApi, state: Path) -> None:
    with pytest.raises(toad_agent.ToolError, match="^Unknown function do_magic$"):
        make_app(api, state).run_tool("do_magic", {})


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("call_phone", toad_agent.SERVER_ONLY),
        ("control_desk", toad_agent.SERVER_ONLY),
        ("show_page", toad_agent.SERVER_ONLY),
        ("COMPOSIO_SEARCH_TOOLS", toad_agent.COMPOSIO_ONLY),
        ("add_todo", toad_agent.TODOS_ONLY),
        ("complete_todo", toad_agent.TODOS_ONLY),
        ("remove_todo", toad_agent.TODOS_ONLY),
        ("show_today", toad_agent.TODOS_ONLY),
        ("look_through_camera", toad_agent.NO_CAMERA),
    ],
)
def test_server_only_tools_return_errors(
    api: FakeApi, state: Path, name: str, message: str
) -> None:
    with pytest.raises(toad_agent.ToolError) as excinfo:
        make_app(api, state).run_tool(name, {})
    assert str(excinfo.value) == message
    assert "Toad" in message or "camera" in message


def test_memory_tools_and_desk_status(api: FakeApi, state: Path) -> None:
    app = make_app(api, state)
    assert app.run_tool("save_memory", {"text": "Grant due Friday"}) == "Saved as m1."
    assert app.run_tool("save_memory", {"text": "Likes tea"}) == "Saved as m2."
    assert app.run_tool("delete_memory", {"id": "m1"}) == "Deleted m1."
    with pytest.raises(toad_agent.ToolError, match="No memory with id m9"):
        app.run_tool("delete_memory", {"id": "m9"})
    assert app.run_tool("save_memory", {"text": "Third"}) == "Saved as m3."
    assert desk(state)["memories"][0] == {"id": "m2", "text": "Likes tea", "created_at": NOW}

    assert app.run_tool("set_focus", {"task": "taxes"}) == "Focus set. No check-in scheduled."
    db = desk(state)
    db["focus"]["started_at"] = NOW - 125
    db["checkins"] = [
        {"id": "a", "due_at": NOW - 1, "about": "due one"},
        {"id": "b", "due_at": NOW + 61, "about": "soon"},
    ]
    app.write_db(db)
    status = json.loads(app.run_tool("get_desk_status", {}))
    assert status["focus"] == {"task": "taxes", "minutes_ago": 2}
    assert status["memories"] == [{"id": "m2", "text": "Likes tea"}, {"id": "m3", "text": "Third"}]
    assert status["due_checkins"] == ["due one"]
    assert status["upcoming_checkins"] == [{"about": "soon", "in_minutes": 2}]
    assert list(status) == [
        "local_time",
        "focus",
        "memories",
        "due_checkins",
        "upcoming_checkins",
    ]


def test_set_focus_replaces_old_focus_checkin(api: FakeApi, state: Path) -> None:
    app = make_app(api, state)
    app.write_db(
        {
            "memories": [],
            "focus": None,
            "checkins": [
                {"id": "old", "due_at": 1, "about": "Focus check-in: old"},
                {"id": "keep", "due_at": 2, "about": "Something else"},
            ],
        }
    )
    with pytest.raises(toad_agent.ToolError, match="task is required"):
        app.run_tool("set_focus", {})
    assert app.run_tool("set_focus", {"task": "new", "checkin_minutes": 10}).endswith("10 minutes.")
    assert [c["id"] for c in desk(state)["checkins"]] == ["keep", f"c{NOW}"]


def test_now_text_uses_toad_tz(api: FakeApi, state: Path) -> None:
    config = toad_agent.Config.from_env({**ENV, "TOAD_TZ": "America/New_York"}, state)
    # 2026-10-05 18:03:00 UTC is Monday 2:03 PM EDT.
    app = toad_agent.ToadAgent(config, api.client(), clock=lambda: 1_791_223_380)
    assert app.now_text() == "Monday October 5, 2:03 PM EDT"


# ---------------------------------------------------------------- misc


def test_help_and_missing_key(
    api: FakeApi, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(api, state) == 0
    assert "create-agent [--force]" in capsys.readouterr().out
    assert run(api, state, "bogus") == 0
    assert "tick" in capsys.readouterr().out
    assert toad_agent.main(["status"], env={}, client=api.client(), state_dir=state) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_end_deletes_session(api: FakeApi, state: Path) -> None:
    session(state)
    api.on("DELETE /agents/sessions/sess_1", httpx.Response(200, json={"deleted": True}))
    assert run(api, state, "end") == 0
    assert not (state / "session_id").exists()


def test_env_file_parser(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# c\nOPENAI_API_KEY=sk-1\nexport OPENAI_PROJECT='proj_x'\nTOAD_TZ=\n")
    assert toad_agent.load_env_file(env) == {
        "OPENAI_API_KEY": "sk-1",
        "OPENAI_PROJECT": "proj_x",
        "TOAD_TZ": "",
    }

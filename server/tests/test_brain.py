import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from toad_server.brain import AgentBrain, SDKGateway, SessionGone
from toad_server.store import Store

Json = dict[str, Any]


class Gateway(SDKGateway):
    def __init__(self) -> None:
        self.syncs = 0
        self.turns: list[str | None] = []
        self.results: list[tuple[list[Json], str]] = []
        self.fail_once = False
        self.active = 0
        self.maximum = 0
        self.closed = 0
        self.never_finish = False

    async def sync(self, definition: Json, agent_id: str | None) -> str:
        self.syncs += 1
        return agent_id or "synthetic-agent"

    @asynccontextmanager
    async def turn(
        self, agent_id: str, session_id: str | None, text: str
    ) -> AsyncIterator[AsyncIterator[Json]]:
        self.turns.append(session_id)
        if self.fail_once:
            self.fail_once = False
            raise SessionGone("gone")
        self.active += 1
        self.maximum = max(self.maximum, self.active)

        async def events() -> AsyncIterator[Json]:
            if self.never_finish:
                await asyncio.Event().wait()
            if not session_id:
                yield {"type": "agent.session.created", "session": {"id": "synthetic-session"}}
            action = {
                "type": "function_call",
                "call_id": "call-1",
                "turn_id": "turn-1",
                "name": "save_memory",
                "arguments": '{"text":"tea"}',
            }
            for _ in range(2):
                yield {
                    "type": "agent.session.requires_action",
                    "session": {"id": "synthetic-session", "required_actions": [action]},
                }
            await asyncio.sleep(0.001)
            yield {"type": "agent.session.turn.output_text.done", "text": "Saved."}
            yield {"type": "agent.session.turn.completed"}

        try:
            yield events()
        finally:
            self.active -= 1
            self.closed += 1

    async def submit(self, session_id: str, events: list[Json], key: str) -> None:
        self.results.append((events, key))


async def tools(name: str, args: Json) -> Json:
    return {"ok": True, "output": "Saved as m1."}


@pytest.mark.asyncio
async def test_sync_session_reuse_and_duplicate_actions(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    gateway = Gateway()
    brain = AgentBrain(gateway, {"model": "gpt-6-astra"}, store)
    await brain.init()
    await brain.init()
    assert gateway.syncs == 1
    assert await brain.ask("remember tea", tools) == "Saved."
    assert len(gateway.results) == 1
    assert gateway.results[0][1] == "tool-call-1"
    assert gateway.results[0][0][0]["success"] is True
    assert await brain.ask("hello again", tools) == "Saved."
    assert gateway.turns == [None, "synthetic-session"]
    reloaded = Store(tmp_path)
    await reloaded.load()
    assert reloaded.snapshot()["agent"]["sessionId"] == "synthetic-session"


@pytest.mark.asyncio
async def test_definition_change_creates_new_session(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    gateway = Gateway()
    first = AgentBrain(gateway, {"model": "gpt-6-astra", "instructions": "one"}, store)
    await first.init()
    await first.ask("first", tools)
    second = AgentBrain(gateway, {"model": "gpt-6-astra", "instructions": "two"}, store)
    await second.init()
    await second.ask("second", tools)
    assert gateway.turns == [None, None]


@pytest.mark.asyncio
async def test_unusable_session_recovers_once_and_turns_are_serialized(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    gateway = Gateway()
    brain = AgentBrain(gateway, {"model": "gpt-6-astra"}, store)
    await brain.init()
    await brain.ask("first", tools)
    gateway.fail_once = True
    await asyncio.gather(brain.ask("second", tools), brain.ask("third", tools))
    assert gateway.maximum == 1
    assert gateway.turns == [None, "synthetic-session", None, "synthetic-session"]


@pytest.mark.asyncio
async def test_timeout_closes_stream_and_releases_turn_lock(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    gateway = Gateway()
    gateway.never_finish = True
    brain = AgentBrain(gateway, {"model": "gpt-6-astra"}, store, timeout_seconds=0.02)
    await brain.init()
    with pytest.raises(TimeoutError):
        await brain.ask("waiting", tools)
    assert gateway.active == 0 and gateway.closed == 1
    assert not brain.lock.locked()


@pytest.mark.asyncio
async def test_sdk_wire_session_and_tool_submission(tmp_path: Path) -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path == "/v1/agents":
            return httpx2.Response(200, json={"id": "agent-sdk", "model": "gpt-6-astra"})
        if request.url.path.endswith("/events"):
            return httpx2.Response(200)
        events = [
            {"type": "agent.session.created", "session": {"id": "session-sdk"}},
            {
                "type": "agent.session.requires_action",
                "session": {
                    "id": "session-sdk",
                    "required_actions": [
                        {
                            "type": "function_call",
                            "call_id": "call-sdk",
                            "turn_id": "turn-sdk",
                            "name": "save_memory",
                            "arguments": {"text": "tea"},
                        }
                    ],
                },
            },
            {"type": "agent.session.turn.output_text.done", "text": "Saved through SDK."},
            {"type": "agent.session.turn.completed"},
        ]
        import json

        data = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        return httpx2.Response(200, text=data, headers={"Content-Type": "text/event-stream"})

    async with AsyncOpenAI(
        api_key="synthetic-test",
        base_url="https://mock.invalid/v1",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    ) as client:
        store = Store(tmp_path)
        await store.load()
        brain = AgentBrain(SDKGateway(client), {"model": "gpt-6-astra"}, store)
        await brain.init()
        assert await brain.ask("remember tea", tools) == "Saved through SDK."
    assert requests[-1].headers["Idempotency-Key"] == "tool-call-sdk"

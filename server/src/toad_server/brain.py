"""Persistent saved-agent turns, streamed tools and one unusable-session recovery."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import uuid4

from openai import ConflictError, NotFoundError

from .store import Store

Json = dict[str, Any]
ToolRunner = Callable[[str, Json], Awaitable[Json]]
Progress = Callable[[str, list[str]], Awaitable[None]]


class SessionGone(RuntimeError):
    pass


class SDKGateway:
    """SDK boundary isolated so protocol tests can inject a fake without network access."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def sync(self, definition: Json, agent_id: str | None) -> str:
        if agent_id:
            await self.client.beta.agents.update(agent_id, **definition)
            return agent_id
        agent = await self.client.beta.agents.create(**definition)
        return str(agent.id)

    @asynccontextmanager
    async def turn(
        self, agent_id: str, session_id: str | None, text: str
    ) -> AsyncIterator[AsyncIterator[Json]]:
        # Only opening the stream and posting the message mean "the session is gone"; a failure
        # later in the turn (a tool result) fails the turn rather than replaying it elsewhere.
        try:
            if session_id:
                # Subscribe before sending so the turn's first events aren't missed.
                stream = await self.client.beta.agents.sessions.events.stream(session_id)
            else:
                stream = await self.client.beta.agents.sessions.create(
                    agent_id=agent_id,
                    environment={"type": "none"},
                    input=text,
                    stream=True,
                    metadata={"app": "toad-server"},
                )
        except (NotFoundError, ConflictError) as error:
            raise SessionGone("saved session is unavailable") from error
        async with stream:
            if session_id:
                message = {
                    "type": "agent.session.input.message",
                    "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
                }
                try:
                    await self.submit(session_id, [message], str(uuid4()))
                except (NotFoundError, ConflictError) as error:
                    raise SessionGone("saved session is unavailable") from error

            async def events() -> AsyncIterator[Json]:
                async for event in stream:
                    yield cast(Json, event.to_dict())

            yield events()

    async def submit(self, session_id: str, events: list[Json], key: str) -> None:
        await self.client.beta.agents.sessions.events.create(
            session_id, events=events, idempotency_key=key
        )


class AgentBrain:
    def __init__(
        self, gateway: SDKGateway, definition: Json, store: Store, timeout_seconds: float = 150
    ) -> None:
        self.gateway, self.definition, self.store = gateway, definition, store
        self.definition_hash = hashlib.sha256(
            json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        self.lock = asyncio.Lock()
        self.timeout_seconds = timeout_seconds

    async def init(self, agent_id: str | None = None) -> None:
        link = self.store.snapshot()["agent"]
        identifier = agent_id or link["agentId"]
        if (
            identifier
            and link["agentId"] == identifier
            and link["definitionHash"] == self.definition_hash
        ):
            return
        identifier = await self.gateway.sync(self.definition, identifier)
        await self.store.set_agent_link(
            {"agentId": identifier, "definitionHash": self.definition_hash}
        )

    async def ask(self, text: str, tools: ToolRunner, progress: Progress | None = None) -> str:
        async with self.lock:
            for attempt in range(2):
                try:
                    async with asyncio.timeout(self.timeout_seconds):
                        return await self._run(text, tools, progress)
                except TimeoutError:
                    raise TimeoutError("brain turn timed out") from None
                except SessionGone:
                    if attempt or not self.store.snapshot()["agent"]["sessionId"]:
                        raise
                    await self.store.set_agent_link({"sessionId": None, "sessionHash": None})
        raise RuntimeError("brain turn did not complete")

    async def _run(self, text: str, tools: ToolRunner, progress: Progress | None) -> str:
        link = self.store.snapshot()["agent"]
        if not link["agentId"]:
            raise RuntimeError("brain not initialized")
        session_id = link["sessionId"] if link["sessionHash"] == self.definition_hash else None
        answered: set[str] = set()
        unsent = ""
        previous = ""
        async with self.gateway.turn(link["agentId"], session_id, text) as events:
            async for event in events:
                match event.get("type"):
                    case "agent.session.created":
                        session_id = event["session"]["id"]
                        await self.store.set_agent_link(
                            {"sessionId": session_id, "sessionHash": self.definition_hash}
                        )
                    case "agent.session.turn.output_text.done":
                        if unsent:
                            previous = unsent
                        unsent = event["text"]
                    case "agent.session.requires_action":
                        session_id = event["session"]["id"]
                        actions = event["session"]["required_actions"]
                        if unsent:
                            if progress:
                                await progress(
                                    unsent,
                                    [a["name"] for a in actions if a["type"] == "function_call"],
                                )
                            previous, unsent = unsent, ""
                        for action in actions:
                            if action["type"] != "function_call" or action["call_id"] in answered:
                                continue
                            answered.add(action["call_id"])
                            args = action.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except ValueError:
                                    args = {}
                            result = await tools(
                                action["name"], args if isinstance(args, dict) else {}
                            )
                            output = {
                                "type": "agent.session.input.tool_result",
                                "turn_id": action["turn_id"],
                                "call_id": action["call_id"],
                                "success": result["ok"],
                            }
                            output["output" if result["ok"] else "error"] = result.get(
                                "output" if result["ok"] else "error", ""
                            )
                            await self.gateway.submit(
                                session_id, [output], "tool-" + action["call_id"]
                            )
                    case "agent.session.turn.completed":
                        return str(unsent or previous)
                    case "agent.session.failed":
                        raise SessionGone("saved session failed")
                    case "agent.session.turn.failed" | "agent.session.turn.cancelled":
                        turn = event.get("turn") or {}
                        detail = turn.get("error") or turn.get("status")
                        raise RuntimeError(f"{event['type']}: {json.dumps(detail)}")
                    case "error":
                        raise RuntimeError(f"agent stream error: {json.dumps(event)}")
        raise RuntimeError("agent stream closed before the turn finished")

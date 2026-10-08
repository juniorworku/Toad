"""GPT-Live primary WebSocket adapter with client delegation and bounded commands."""

import asyncio
import base64
import contextlib
import json
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from .config import Settings
from .providers import Emit


class LiveVoice:
    def __init__(self, settings: Settings, instructions: str):
        self.settings = settings
        self.instructions = instructions
        self.commands: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self.socket: ClientConnection | None = None
        self.started = False
        self.sequence = 0
        self.closed = asyncio.Event()

    async def command(self, event: dict[str, Any]) -> None:
        self.sequence += 1
        event.setdefault("event_id", f"toad_{self.sequence}")
        self.commands.put_nowait(event)

    async def commentary(self, content: str, delegation_id: str | None = None) -> None:
        await self.command(
            {
                "type": "session.commentary.append",
                "content": self.clip(content),
                "delegation_id": delegation_id,
            }
        )

    async def thinking(self, content: str, delegation_id: str | None = None) -> None:
        await self.command(
            {
                "type": "session.thinking.append",
                "content": self.clip(content),
                "delegation_id": delegation_id,
            }
        )

    async def mute(self, muted: bool) -> None:
        await self.command(
            {"type": "session.input_audio.mute" if muted else "session.input_audio.unmute"}
        )

    async def say(self, text: str) -> None:
        # Typed input is handled by the brain, never presented as a spoken user transcript.
        await self.thinking("The user selected: " + text)

    async def append_audio(self, pcm: bytes) -> None:
        if self.started and pcm and len(pcm) % 2 == 0:
            try:
                self.commands.put_nowait(
                    {
                        "type": "session.input_audio.append",
                        "audio": base64.b64encode(pcm).decode("ascii"),
                    }
                )
            except asyncio.QueueFull:
                # Do not let a slow provider accumulate stale microphone audio.
                pass

    @staticmethod
    def clip(content: str) -> str:
        return content if len(content) <= 1800 else content[:1799] + "…"

    async def run(self, emit: Emit) -> None:
        headers = {"Authorization": "Bearer " + self.settings.openai_api_key.get_secret_value()}
        async with connect(
            self.settings.live_url, additional_headers=headers, max_size=8 * 1024 * 1024, proxy=None
        ) as socket:
            self.socket = socket
            writer: asyncio.Task[None] | None = None
            await socket.send(
                json.dumps(
                    {
                        "type": "session.start",
                        "event_id": "toad_start",
                        "session": {
                            "model": self.settings.live_model,
                            "instructions": self.instructions,
                            "audio": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "output": {"voice": self.settings.live_voice},
                            },
                            "delegation": {"type": "client"},
                            "store": False,
                        },
                    }
                )
            )

            async def send() -> None:
                while True:
                    command = await self.commands.get()
                    try:
                        await socket.send(json.dumps(command))
                    finally:
                        self.commands.task_done()

            try:
                async for raw in socket:
                    event = json.loads(raw)
                    match event.get("type"):
                        case "session.started":
                            self.started = True
                            if writer is None:
                                writer = asyncio.create_task(send())
                            await emit({"event": "started"})
                        case "session.output_audio.delta":
                            await emit(base64.b64decode(event["delta"]))
                        case "session.input_transcript.delta" | "session.output_transcript.delta":
                            role = (
                                "user"
                                if event["type"] == "session.input_transcript.delta"
                                else "assistant"
                            )
                            await emit(
                                {
                                    "event": "transcript",
                                    "role": role,
                                    "delta": event["delta"],
                                    "start_ms": event.get("start_ms", 0),
                                }
                            )
                        case "session.delegation.created":
                            if event["delegation"]["target"] == "client":
                                await emit({"event": "delegation", "id": event["delegation"]["id"]})
                        case "session.closed":
                            self.closed.set()
                            break
                        case "error":
                            await emit(
                                {"event": "error", "message": "voice service rejected a command"}
                            )
            finally:
                self.started = False
                self.socket = None
                if writer:
                    writer.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await writer

    async def close(self) -> None:
        if self.socket and self.started:
            await self.command({"type": "session.close"})
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.closed.wait(), 5)
        if self.socket:
            await self.socket.close()

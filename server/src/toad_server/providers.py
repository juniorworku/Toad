"""Explicit diagnostic fake: returns text and a tone, never AI speech."""

import asyncio
import math
import struct
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

Event = dict[str, Any]
Emit = Callable[[Event | bytes], Awaitable[None]]


class Voice(Protocol):
    async def run(self, emit: Emit) -> None: ...
    async def say(self, text: str) -> None: ...
    async def append_audio(self, pcm: bytes) -> None: ...
    async def commentary(self, content: str, delegation_id: str | None = None) -> None: ...
    async def thinking(self, content: str, delegation_id: str | None = None) -> None: ...
    async def mute(self, muted: bool) -> None: ...
    async def close(self) -> None: ...


class FakeVoice:
    def __init__(self, instructions: str = "") -> None:
        self.instructions = instructions
        self.requests: asyncio.Queue[str] = asyncio.Queue(maxsize=16)
        self.received_audio_bytes = 0

    async def run(self, emit: Emit) -> None:
        await emit({"event": "started"})
        while True:
            text = await self.requests.get()
            try:
                await emit({"event": "thinking", "value": True})
                await asyncio.sleep(0.02)
                await emit(
                    {
                        "event": "transcript",
                        "role": "assistant",
                        "delta": f"[Fake provider] Received: {text}",
                    }
                )
                await emit({"event": "thinking", "value": False})
                pcm = b"".join(
                    struct.pack("<h", int(1000 * math.sin(2 * math.pi * 440 * i / 24000)))
                    for i in range(2400)
                )
                for _ in range(3):
                    await emit(pcm)
                    await asyncio.sleep(0.1)
            finally:
                self.requests.task_done()

    async def say(self, text: str) -> None:
        self.requests.put_nowait(text)

    async def append_audio(self, pcm: bytes) -> None:
        self.received_audio_bytes += len(pcm)

    async def commentary(self, content: str, delegation_id: str | None = None) -> None:
        await self.say(content)

    async def thinking(self, content: str, delegation_id: str | None = None) -> None:
        pass

    async def mute(self, muted: bool) -> None:
        pass

    async def close(self) -> None:
        pass

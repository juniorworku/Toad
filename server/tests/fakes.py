"""Fakes shared by the engine tests: a scripted voice session, brain, phone and controlled clock."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from fastapi import WebSocket

from toad_server.config import Settings
from toad_server.desk import Desk, Progress, ToolRunner
from toad_server.providers import Emit
from toad_server.store import Store

Json = dict[str, Any]


class FakeLive:
    """Stands in for GPT-Live: records commands, and the test drives its events."""

    def __init__(self, instructions: str) -> None:
        self.instructions = instructions
        self.sent: list[tuple[Any, ...]] = []
        self.emitter: Emit | None = None
        self.running = asyncio.Event()
        self.closed = asyncio.Event()

    @property
    def is_open(self) -> bool:
        return not self.closed.is_set()

    async def run(self, emit: Emit) -> None:
        self.emitter = emit
        self.sent.append(("connect",))
        self.running.set()
        await self.closed.wait()

    async def emit(self, event: Json | bytes) -> None:
        await self.running.wait()
        assert self.emitter
        await self.emitter(event)

    async def started(self) -> None:
        await self.emit({"event": "started", "id": "live_1"})

    async def user(self, text: str, start_ms: int = 0) -> None:
        await self.emit(
            {"event": "transcript", "role": "user", "delta": text, "start_ms": start_ms}
        )

    async def assistant(self, text: str, start_ms: int = 0) -> None:
        await self.emit(
            {"event": "transcript", "role": "assistant", "delta": text, "start_ms": start_ms}
        )

    async def delegate(self, identifier: str) -> None:
        await self.emit({"event": "delegation", "id": identifier})

    async def say(self, text: str) -> None:
        self.sent.append(("say", text))

    async def append_audio(self, pcm: bytes) -> None:
        self.sent.append(("audio", len(pcm)))

    async def commentary(self, content: str, delegation_id: str | None = None) -> None:
        self.sent.append(("commentary", content, delegation_id))

    async def thinking(self, content: str, delegation_id: str | None = None) -> None:
        self.sent.append(("thinking", content, delegation_id))

    async def mute(self, muted: bool) -> None:
        self.sent.append(("mute",) if muted else ("unmute",))

    async def close(self) -> None:
        if not self.closed.is_set():
            self.sent.append(("close",))
        self.closed.set()

    def spoken(self) -> list[tuple[Any, ...]]:
        return [m for m in self.sent if m[0] == "commentary"]


Script = Callable[[str, ToolRunner, Progress | None], Awaitable[str]]


class FakeBrain:
    """Scripted brain: runs the given tool calls, then answers."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self.asked: list[str] = []
        self.tools: list[ToolRunner] = []

    async def ask(self, text: str, tools: ToolRunner, progress: Progress | None = None) -> str:
        self.asked.append(text)
        self.tools.append(tools)
        return await self.script(text, tools, progress)


def answer(reply: str) -> Script:
    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        return reply

    return script


class FakeDevice:
    """Stands in for the phone's WebSocket; `say`/`mic` drive the desk like the phone would."""

    def __init__(self, desk: Desk) -> None:
        self.desk = desk
        self.json: list[Json] = []
        self.binary: list[int] = []
        self.closed = False

    async def send_json(self, value: Json) -> None:
        self.json.append(value)

    async def send_bytes(self, value: bytes) -> None:
        self.binary.append(len(value))

    async def close(self, **kwargs: Any) -> None:
        self.closed = True

    async def say(self, message: Json) -> None:
        await self.desk.message(json.dumps(message))
        await settle(self.desk)

    async def mic(self, size: int) -> None:
        await self.desk.microphone(bytes(size))

    def of(self, kind: str) -> list[Json]:
        return [m for m in self.json if m.get("type") == kind]

    def last(self, kind: str) -> Json | None:
        found = self.of(kind)
        return found[-1] if found else None


async def settle(desk: Desk, rounds: int = 3) -> None:
    """Lets spawned turns run and flushes everything queued for the phone."""
    for _ in range(rounds):
        for _ in range(20):
            await asyncio.sleep(0)
        pending = [t for t in desk.brain_tasks | desk.background if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=1)
        if desk.peer:
            await asyncio.wait_for(desk.peer.queue.join(), 1)


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


class Rig:
    """A desk with a controlled clock (wall ms for the store, seconds for activity)."""

    def __init__(self, tmp_path: Path, brain: FakeBrain, start: str, **settings: Any) -> None:
        self.wall = ms(start)
        self.base = self.wall
        self.store = Store(tmp_path, clock=lambda: self.wall)
        self.brain = brain
        self.lives: list[FakeLive] = []
        options: Json = {
            "device_token": "test",
            "data_dir": tmp_path,
            "always_listen": False,
            "idle_close_seconds": 60,
            "time_zone": "America/New_York",
            "delegation_settle_seconds": 0,
            "quiet_hours": None,
        }
        options.update(settings)
        self.desk = Desk(
            Settings(**options),
            self.store,
            voice_factory=self.new_live,
            clock=lambda: (self.wall - self.base) / 1000,
            log=lambda message: None,
        )
        self.desk.brain = brain
        self.device = FakeDevice(self.desk)

    def new_live(self, instructions: str) -> FakeLive:
        live = FakeLive(instructions)
        self.lives.append(live)
        return live

    async def load(self) -> "Rig":
        await self.store.load()
        await self.desk.pages.load()
        return self

    async def attach(self, device: FakeDevice | None = None) -> FakeDevice:
        device = device or self.device
        await self.desk.attach(cast(WebSocket, device))
        await settle(self.desk)
        return device

    def advance(self, milliseconds: int) -> None:
        self.wall += milliseconds

    async def tick(self) -> None:
        await self.desk.tick()
        await settle(self.desk)

    async def open(self) -> FakeLive:
        """Talk button: opens a voice session and lets it start."""
        await self.device.say({"type": "start"})
        live = self.lives[-1]
        await live.running.wait()
        await live.started()
        await settle(self.desk)
        return live

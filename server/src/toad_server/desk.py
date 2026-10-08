"""One device, one voice session, ordered sends and cancellation-safe audio."""

import asyncio
import contextlib
import json
import secrets
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from anyio import BrokenResourceError, ClosedResourceError
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .brain import AgentBrain
from .config import Settings
from .pages import Pages
from .protocol import Camera, Forget, Photo, PhotoError, Presence, Say, device_message
from .providers import FakeVoice, Voice
from .store import Store
from .tools import Tools
from .transcript import Transcript

Json = dict[str, Any]


@dataclass(eq=False)
class Peer:
    socket: WebSocket
    queue: asyncio.Queue[tuple[int | None, Json | bytes]]
    writer: asyncio.Task[None] | None = None
    closed: asyncio.Event = field(default_factory=asyncio.Event)


class Desk:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        voice_factory: Callable[[], Voice] = FakeVoice,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings, self.store = settings, store
        self.voice_factory, self.clock = voice_factory, clock
        self.peer: Peer | None = None
        self.voice: Voice | None = None
        self.voice_task: asyncio.Task[None] | None = None
        self.generation = 0
        self.live = "idle"
        self.muted, self.camera, self.thinking = False, True, False
        self.present: bool | None = None
        self.last_activity = self.clock()
        self.last_open = float("-inf")
        self.listen_paused = False
        self.scheduler_task: asyncio.Task[None] | None = None
        self.tick_lock = asyncio.Lock()
        self.last_voice = float("-inf")
        self.last_interrupt = float("-inf")
        self.photos: dict[str, asyncio.Future[str]] = {}
        self._connections = asyncio.Lock()
        self.pages = Pages(settings.data_dir)
        self.brain: AgentBrain | None = None
        self.brain_busy = 0
        self.transcripts = Transcript()
        self.brain_tasks: set[asyncio.Task[None]] = set()
        self.delegations: set[str] = set()
        self.close_after_reply = False

    def state(self) -> Json:
        return {
            "type": "state",
            "live": self.live,
            "muted": self.muted,
            "camera": self.camera,
            "thinking": self.thinking or self.brain_busy > 0,
        }

    async def send(self, message: Json | bytes, generation: int | None = None) -> None:
        peer = self.peer
        if not peer or peer.closed.is_set():
            return
        try:
            peer.queue.put_nowait((generation, message))
        except asyncio.QueueFull:
            peer.closed.set()
            await peer.socket.close(code=1013, reason="device output queue full")

    async def _writer(self, peer: Peer) -> None:
        try:
            while True:
                generation, message = await peer.queue.get()
                try:
                    if generation is not None and generation != self.generation:
                        continue
                    if isinstance(message, bytes):
                        await peer.socket.send_bytes(message)
                    else:
                        await peer.socket.send_json(message)
                finally:
                    peer.queue.task_done()
        except (
            RuntimeError,
            OSError,
            WebSocketDisconnect,
            BrokenResourceError,
            ClosedResourceError,
        ):
            peer.closed.set()

    async def attach(self, socket: WebSocket) -> Peer:
        async with self._connections:
            if self.peer:
                old = self.peer
                await self._detach(old)
                with contextlib.suppress(
                    RuntimeError,
                    OSError,
                    WebSocketDisconnect,
                    BrokenResourceError,
                    ClosedResourceError,
                ):
                    await old.socket.close(code=1000, reason="replaced by another device")
            peer = Peer(socket, asyncio.Queue(self.settings.outbound_queue_size))
            self.peer = peer
            peer.writer = asyncio.create_task(self._writer(peer))
            await self.send(self.state())
            await self.send(self.store.desk())
            if self.settings.provider_mode == "fake":
                await self.send(
                    {
                        "type": "error",
                        "message": "Diagnostic fake provider: text and test tones only; AI is not connected.",
                    }
                )
            if self.settings.always_listen:
                await self.start()
            return peer

    async def _detach(self, peer: Peer) -> None:
        if self.peer is not peer:
            return
        self.peer = None
        peer.closed.set()
        await self.stop()
        if peer.writer:
            peer.writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await peer.writer
        for future in self.photos.values():
            if not future.done():
                future.set_exception(ConnectionError("the desk phone disconnected"))
        self.photos.clear()

    async def detach(self, peer: Peer) -> None:
        async with self._connections:
            await self._detach(peer)

    async def close(self) -> None:
        if self.scheduler_task:
            self.scheduler_task.cancel()
            await asyncio.gather(self.scheduler_task, return_exceptions=True)
            self.scheduler_task = None
        async with self._connections:
            if self.peer:
                peer = self.peer
                await self._detach(peer)
                with contextlib.suppress(
                    RuntimeError,
                    OSError,
                    WebSocketDisconnect,
                    BrokenResourceError,
                    ClosedResourceError,
                ):
                    await peer.socket.close(code=1001, reason="engine shutdown")
            else:
                await self.stop()

    async def start(self) -> None:
        if self.voice_task and not self.voice_task.done():
            return
        self.last_open = self.last_activity = self.clock()
        self.generation += 1
        self.transcripts = Transcript()
        self.delegations.clear()
        self.close_after_reply = False
        generation = self.generation
        voice = self.voice_factory()
        self.voice = voice
        self.live = "connecting"
        await self.send(self.state())

        async def emit(event: Json | bytes) -> None:
            if generation != self.generation:
                return
            if isinstance(event, bytes):
                self.last_activity = self.last_voice = self.clock()
                await self.send(event, generation)
            elif event["event"] == "started":
                self.live = "open"
                await voice.mute(self.muted)
                await self.send(self.state())
            elif event["event"] == "thinking":
                self.thinking = event["value"]
                await self.send(self.state())
            elif event["event"] == "transcript":
                await self.transcript(event["role"], event["delta"], event.get("start_ms", 0))
            elif event["event"] == "delegation":
                identifier = event["id"]
                if identifier not in self.delegations:
                    self.delegations.add(identifier)
                    self.spawn_brain(self.delegated(voice, generation, identifier))
            elif event["event"] == "error":
                await self.send({"type": "error", "message": event["message"]})

        async def run() -> None:
            try:
                await voice.run(emit)
            except Exception:
                await self.send({"type": "error", "message": "voice provider failed"})
            finally:
                if generation == self.generation:
                    self.live, self.thinking = "idle", False
                    await self.send(self.state())

        self.voice_task = asyncio.create_task(run())

    async def stop(self) -> None:
        self.generation += 1
        pending = list(self.brain_tasks)
        for turn in pending:
            turn.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        task, self.voice_task = self.voice_task, None
        voice, self.voice = self.voice, None
        if voice:
            await voice.close()
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.live, self.thinking = "idle", False
        await self.send({"type": "interrupt"})
        await self.send(self.state())

    async def transcript(self, role: str, delta: str, start_ms: int = 0) -> None:
        self.last_activity = self.clock()
        self.transcripts.add(role, delta, start_ms)
        now = self.clock()
        if role == "user" and delta.strip() and now - self.last_voice < 3:
            if now - self.last_interrupt > 1:
                self.last_interrupt = now
                await self.send({"type": "interrupt"})
        await self.send({"type": "transcript", "role": role, "delta": delta})

    async def microphone(self, pcm: bytes) -> None:
        if len(pcm) % 2:
            await self.send(
                {"type": "error", "message": "PCM16 frames must have an even byte length"}
            )
            return
        if self.voice and self.live == "open" and not self.muted:
            await self.voice.append_audio(pcm)

    async def message(self, raw: str) -> None:
        try:
            parsed = json.loads(raw)
        except ValueError:
            await self.send({"type": "error", "message": "messages must be JSON"})
            return
        try:
            message = device_message.validate_python(parsed)
        except ValidationError:
            kind = parsed.get("type") if isinstance(parsed, dict) else None
            await self.send({"type": "error", "message": f"invalid or unknown message type {kind}"})
            return
        if message.type == "start":
            self.listen_paused = False
            await self.start()
        elif message.type == "stop":
            self.listen_paused = True
            await self.stop()
        elif message.type in ("mute", "unmute"):
            self.muted = message.type == "mute"
            if self.voice:
                await self.voice.mute(self.muted)
            await self.send(self.state())
        elif isinstance(message, Camera):
            self.camera = message.enabled
            await self.send(self.state())
        elif isinstance(message, Presence):
            self.present = message.present
        elif isinstance(message, Forget):
            await self.store.delete_memory(message.id)
            await self.send(self.store.desk())
        elif message.type == "forget_all":
            await self.store.clear_memories()
            await self.send(self.store.desk())
        elif isinstance(message, (Photo, PhotoError)):
            future = self.photos.pop(message.requestId, None)
            if future and not future.done():
                if isinstance(message, Photo):
                    future.set_result(message.image)
                else:
                    future.set_exception(RuntimeError(message.reason))
        elif isinstance(message, Say):
            text = message.text.strip()
            if text:
                self.listen_paused = False
                self.last_activity = self.clock()
                await self.start()
                self.transcripts.note("user", text)
                await self.send({"type": "transcript", "role": "user", "delta": text})
                if self.voice:
                    if self.brain:
                        self.spawn_brain(self.ask_brain(self.voice, self.generation, text, None))
                    else:
                        try:
                            await self.voice.say(text)
                        except asyncio.QueueFull:
                            await self.send({"type": "error", "message": "voice turn queue full"})

    async def capture(self) -> str:
        if not self.peer or not self.camera:
            raise RuntimeError("camera unavailable")
        identifier = secrets.token_hex(12)
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self.photos[identifier] = future
        try:
            await self.send({"type": "capture", "requestId": identifier, "countdownSeconds": 0})
            return await asyncio.wait_for(future, self.settings.camera_timeout_seconds)
        finally:
            self.photos.pop(identifier, None)

    def spawn_brain(self, coroutine: "Coroutine[Any, Any, None]") -> None:
        task = asyncio.create_task(coroutine)
        self.brain_tasks.add(task)
        task.add_done_callback(self.brain_tasks.discard)

    async def delegated(self, voice: Voice, generation: int, identifier: str) -> None:
        await asyncio.sleep(self.settings.delegation_settle_seconds)
        if generation != self.generation:
            return
        text = self.transcripts.take_user_request()
        if text:
            await self.ask_brain(voice, generation, text, identifier)

    async def ask_brain(
        self, voice: Voice, generation: int, text: str, identifier: str | None
    ) -> None:
        if not self.brain:
            await voice.commentary("The thinking service isn't configured.", identifier)
            return
        self.brain_busy += 1
        await self.send(self.state())
        tools = Tools(
            self,
            "" if text.startswith("[Desk event]") else text,
            None if text.startswith("[Desk event]") else self.transcripts.previous_assistant(),
        )

        async def progress(content: str, pending: list[str]) -> None:
            if generation != self.generation:
                return
            if "look_through_camera" in pending:
                await voice.commentary(content, identifier)
            else:
                await voice.thinking(content, identifier)

        try:
            context = text + "\n\nRecent voice context:\n" + self.transcripts.recent()
            answer = await self.brain.ask(context, tools, progress)
            if generation == self.generation:
                await voice.commentary(answer, identifier)
        except Exception:
            if generation == self.generation:
                await self.send(
                    {"type": "error", "message": "brain turn failed; check provider configuration"}
                )
        finally:
            self.last_activity = self.clock()
            self.brain_busy -= 1
            if generation == self.generation:
                await self.send(self.state())

    async def show_page(self, page: Json) -> None:
        await self.send(
            {
                "type": "page",
                "id": page["id"],
                "title": page["title"],
                "url": f"/p/{page['id']}?v={page['updatedAt']}",
            }
        )

    def start_scheduler(self) -> None:
        if self.scheduler_task is None or self.scheduler_task.done():
            self.scheduler_task = asyncio.create_task(self.scheduler())

    async def scheduler(self) -> None:
        while True:
            await asyncio.sleep(self.settings.scheduler_interval_seconds)
            try:
                await self.tick()
            except Exception:
                await self.send({"type": "error", "message": "scheduled desk update failed"})

    async def tick(self) -> None:
        async with self.tick_lock:
            now = self.clock()
            active = self.voice_task is not None and not self.voice_task.done()
            busy = self.brain_busy > 0 or bool(self.brain_tasks) or self.thinking
            if active and not busy:
                end_reply = self.close_after_reply and now - self.last_activity > 3
                idle = (
                    not self.settings.always_listen
                    and self.live == "open"
                    and now - self.last_activity > self.settings.idle_close_seconds
                )
                if end_reply or idle:
                    if end_reply:
                        self.listen_paused = True
                        self.close_after_reply = False
                    await self.stop()
                    active = False
            if (
                self.settings.always_listen
                and self.peer
                and not active
                and not self.listen_paused
                and now - self.last_open >= self.settings.reconnect_seconds
            ):
                await self.start()
            if not self.peer:
                return  # Keep offline reminders pending until a phone reconnects.
            due = [c for c in self.store.desk()["checkins"] if c["dueAt"] <= self.store.clock()]
            for checkin in due:
                await self.store.mark_checkin_fired(checkin["id"])
                await self.send({"type": "checkin", "about": checkin["about"]})
                await self.send(self.store.desk())
                await self.start()
                self.last_activity = self.clock()
                if self.voice:
                    if self.brain:
                        self.spawn_brain(
                            self.ask_brain(
                                self.voice,
                                self.generation,
                                "[Desk event] Check-in due: "
                                + checkin["about"]
                                + ". Check in briefly. This event is not user consent to save memories.",
                                None,
                            )
                        )
                    else:
                        await self.voice.commentary("Quick check-in: " + checkin["about"])

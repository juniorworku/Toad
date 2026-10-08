"""
The engine. One desk phone at a time connects over a WebSocket. Mic audio flows to a GPT-Live
voice session and its speech flows back. When GPT-Live delegates work, the brain (the Toad agent
session) handles it with tools and the answer goes back to GPT-Live to be spoken. Check-ins come
due on a timer and Toad speaks first: the proactive part.

The voice session is opened on demand (wake word, Talk button, or a due check-in) and closed after
a quiet spell, since it's billed per minute. The brain session persists across them.
"""

import asyncio
import contextlib
import functools
import json
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Protocol

from anyio import BrokenResourceError, ClosedResourceError
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .apps import Apps
from .config import Settings
from .pages import Pages
from .phone import CallRequest, PhoneCaller, mask
from .prompt import live_instructions, local_hour, local_time
from .protocol import Camera, Forget, Photo, PhotoError, Presence, Say, device_message
from .providers import FakeVoice, Voice
from .store import Store
from .today import render_today
from .tools import Tools
from .transcript import Transcript

Json = dict[str, Any]
ToolRunner = Callable[[str, Json], Awaitable[Json]]
Progress = Callable[[str, list[str]], Awaitable[None]]
SOCKET_ERRORS = (
    RuntimeError,
    OSError,
    WebSocketDisconnect,
    BrokenResourceError,
    ClosedResourceError,
)

# Log lines go straight out, also when stdout is a file or a pipe (systemd, nohup, Docker).
log = functools.partial(print, flush=True)
KNOWN_MESSAGES = {
    "start",
    "stop",
    "mute",
    "unmute",
    "camera",
    "photo",
    "photo_error",
    "forget",
    "forget_all",
    "say",
    "presence",
}
SORRY = "Sorry, I couldn't get to that just now. Can you try again in a moment?"
# Back after this long away (per the camera) → Toad says welcome back and follows up.
WELCOME_AFTER_MS = 10 * 60_000
WELCOME_EVERY_MS = 30 * 60_000
# Not seen by the camera for this long when a check-in is due → phone them instead.
AWAY_BY_CAMERA_MS = 2 * 60_000
# No "phone offline → call" right after startup: the phone needs a moment to reconnect.
STARTUP_GRACE_MS = 2 * 60_000
CONTROL_REPLIES = {
    "camera_on": "Camera switched on.",
    "camera_off": "Camera switched off.",
    "close_camera": "Camera screen closed.",
    "mute_mic": "Mic muted. The user can unmute it on the screen; you won't hear them until then.",
    "show_memories": "Memories are on the screen.",
    "hide_memories": "Memories screen closed.",
    "end_conversation": "The conversation will end after your reply. Say a short goodbye.",
}


class Brain(Protocol):
    """Runs one turn and returns what Toad should say. AgentBrain in production."""

    async def ask(self, text: str, tools: ToolRunner, progress: Progress | None = None) -> str: ...


@dataclass
class AwayCalls:
    """Calling the user's phone when a check-in finds nobody at the desk."""

    caller: PhoneCaller
    # The user's own phone, E.164.
    to_number: str
    # How long Toad waits for a spoken reply to a check-in before calling.
    no_reply_seconds: float
    # Local hours when Toad never calls, e.g. (22, 8).
    quiet_hours: tuple[int, int] | None


@dataclass(eq=False)
class Peer:
    socket: WebSocket
    queue: asyncio.Queue[tuple[int | None, Json | bytes]]
    writer: asyncio.Task[None] | None = None
    closed: asyncio.Event = field(default_factory=asyncio.Event)


def in_quiet_hours(hour: int, hours: tuple[int, int]) -> bool:
    start, end = hours
    return start <= hour < end if start <= end else hour >= start or hour < end


def call_problem(error: Exception) -> str:
    """A phone failure in words Toad can say out loud."""
    if re.search(r"→ 402", str(error)):
        return (
            "I couldn't place the call: my phone line has no credit yet. "
            "Add funds on the AgentPhone billing page and I'll try again."
        )
    if re.search(r"→ 40[13]", str(error)):
        return "I couldn't place the call: my phone line's key isn't working."
    return "I couldn't get the call through just now. Want me to try again?"


class Desk:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        voice_factory: Callable[[str], Voice] = FakeVoice,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = log,
    ) -> None:
        self.settings, self.store = settings, store
        self.voice_factory, self.clock, self.log = voice_factory, clock, log
        self.peer: Peer | None = None
        self.voice: Voice | None = None
        self.voice_task: asyncio.Task[None] | None = None
        self.generation = 0
        self.live = "idle"
        self.muted, self.camera, self.thinking = False, True, False
        self.last_activity = self.clock()
        self.last_open = float("-inf")
        self.listen_paused = False
        self.scheduler_task: asyncio.Task[None] | None = None
        self.tick_lock = asyncio.Lock()
        self.last_voice = float("-inf")
        self.last_interrupt = float("-inf")
        self.photos: dict[str, asyncio.Future[str]] = {}
        self._connections = asyncio.Lock()
        self.pages = Pages(settings.data_dir, store.clock)
        self.brain: Brain | None = None
        self.brain_busy = 0
        self.transcripts = Transcript()
        self.brain_tasks: set[asyncio.Task[None]] = set()
        self.background: set[asyncio.Task[None]] = set()
        self.delegations: set[str] = set()
        self.close_after_reply = False
        self.apps: Apps | None = None
        self.away: AwayCalls | None = None
        self.calling = False
        # A check-in Toad asked out loud, waiting for any reply before calling (wall ms).
        self.awaiting_reply: tuple[Json, int] | None = None
        # From the phone's on-device face detection: (present, since wall ms); None until reported.
        self.presence: tuple[bool, int] | None = None
        self.last_welcome = -WELCOME_EVERY_MS
        self.last_today_shown = -10 * 60_000
        self.started_at = store.clock()
        store.on_change(lambda: self.post(self.store.desk()))

    # ------------------------------------------------------------------ status

    def state(self) -> Json:
        return {
            "type": "state",
            "live": self.live,
            "muted": self.muted,
            "camera": self.camera,
            "thinking": self.thinking or self.brain_busy > 0,
        }

    def status(self) -> Json:
        """What's live right now, for the agent page."""
        away = self.away
        return {
            "device": self.peer is not None,
            "voice": self.live,
            "muted": self.muted,
            "camera": self.camera,
            "thinking": self.thinking or self.brain_busy > 0,
            "calling": self.calling,
            "apps": self.apps is not None,
            "awayCalls": away
            and {
                "to": mask(away.to_number),
                "afterSeconds": away.no_reply_seconds,
                "quietHours": list(away.quiet_hours) if away.quiet_hours else None,
            },
        }

    def camera_available(self) -> bool:
        return self.camera and self.peer is not None

    def presence_text(self) -> str:
        if self.presence is None:
            return "unknown"
        present, since = self.presence
        minutes = (self.store.clock() - since) // 60_000
        return f"yes, for {minutes} min" if present else f"no, away for {minutes} min"

    # ------------------------------------------------------------------ to the phone

    def post(self, message: Json | bytes, generation: int | None = None) -> None:
        """Queues a frame for the phone without waiting (safe from sync callbacks)."""
        peer = self.peer
        if not peer or peer.closed.is_set():
            return
        try:
            peer.queue.put_nowait((generation, message))
        except asyncio.QueueFull:
            peer.closed.set()
            self.spawn(self._close_socket(peer.socket, 1013, "device output queue full"))

    async def send(self, message: Json | bytes, generation: int | None = None) -> None:
        peer = self.peer
        if not peer or peer.closed.is_set():
            return
        try:
            peer.queue.put_nowait((generation, message))
        except asyncio.QueueFull:
            peer.closed.set()
            await self._close_socket(peer.socket, 1013, "device output queue full")

    @staticmethod
    async def _close_socket(socket: WebSocket, code: int, reason: str) -> None:
        with contextlib.suppress(*SOCKET_ERRORS):
            await socket.close(code=code, reason=reason)

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
        except SOCKET_ERRORS:
            peer.closed.set()

    # ------------------------------------------------------------------ device

    async def attach(self, socket: WebSocket) -> Peer:
        async with self._connections:
            if self.peer:
                old = self.peer
                self.log("desk: a new device connected; dropping the old one")
                await self._detach(old)
                await self._close_socket(old.socket, 4000, "replaced by another device")
            peer = Peer(socket, asyncio.Queue(self.settings.outbound_queue_size))
            self.peer = peer
            peer.writer = asyncio.create_task(self._writer(peer))
            await self.send(self.state())
            await self.send(self.store.desk())
            if self.settings.provider_mode == "fake":
                await self.send(
                    {
                        "type": "error",
                        "message": "Diagnostic fake provider: text and test tones only; "
                        "AI is not connected.",
                    }
                )
            self.listen_paused = False
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
        pending = list(self.brain_tasks | self.background)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with self._connections:
            if self.peer:
                peer = self.peer
                await self._detach(peer)
                await self._close_socket(peer.socket, 1001, "engine shutdown")
            else:
                await self.stop()

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
            known = kind in KNOWN_MESSAGES
            text = f"invalid {kind} message" if known else f"unknown message type {kind}"
            await self.send({"type": "error", "message": text})
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
            self.spawn(self.on_presence(message.present))
        elif isinstance(message, Forget):
            await self.store.delete_memory(message.id)
        elif message.type == "forget_all":
            await self.store.clear_memories()
        elif isinstance(message, (Photo, PhotoError)):
            future = self.photos.pop(message.requestId, None)
            if future and not future.done():
                if isinstance(message, Photo):
                    future.set_result(message.image)
                else:
                    future.set_exception(
                        RuntimeError(message.reason or "the phone couldn't take a photo")
                    )
        elif isinstance(message, Say):
            text = message.text.strip()
            if text:
                await self.on_tapped(text)

    # ------------------------------------------------------------------ voice session

    async def start(self) -> None:
        if self.voice_task and not self.voice_task.done():
            return
        self.last_open = self.last_activity = self.clock()
        self.generation += 1
        self.transcripts = Transcript()
        self.delegations.clear()
        self.close_after_reply = False
        generation = self.generation
        voice = self.voice_factory(
            live_instructions(self.store, self.settings.time_zone, self.store.clock())
        )
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
                self.log(f"live: session {event.get('id') or '(fake)'} started")
                self.live = "open"
                if self.muted:
                    await voice.mute(True)
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
                self.log(f"live: error {event['message']}")
                await self.send({"type": "error", "message": f"voice: {event['message']}"})

        async def run() -> None:
            try:
                await voice.run(emit)
            except Exception as error:  # noqa: BLE001 - any provider failure ends this session
                self.log(f"live: failed: {error!r}")
                await self.send({"type": "error", "message": "voice provider failed"})
            finally:
                if generation == self.generation:
                    self.live, self.thinking = "idle", False
                    await self.send(self.state())

        self.voice_task = asyncio.create_task(run())

    async def stop(self) -> None:
        """Closes the voice session. Brain turns already running finish, but their reply for this
        session is dropped (cancelling one mid-turn would strand its tool calls in the session)."""
        self.generation += 1
        task, self.voice_task = self.voice_task, None
        voice, self.voice = self.voice, None
        if voice:
            try:
                await voice.close()
            except Exception as error:  # noqa: BLE001 - the task is cancelled below either way
                self.log(f"live: close failed: {error!r}")
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.live, self.thinking = "idle", False
        await self.send({"type": "interrupt"})
        await self.send(self.state())

    async def transcript(self, role: str, delta: str, start_ms: int = 0) -> None:
        self.last_activity = self.clock()
        if role == "user":
            self.awaiting_reply = None  # someone's at the desk
            # Barge-in: GPT-Live already stops generating when the user talks over it, but the
            # phone has a few seconds of Toad's speech queued. Tell it to drop that right away.
            now = self.clock()
            if delta.strip() and now - self.last_voice < 3 and now - self.last_interrupt > 1:
                self.last_interrupt = now
                await self.send({"type": "interrupt"})
        self.transcripts.add(role, delta, start_ms)
        await self.send({"type": "transcript", "role": role, "delta": delta})

    # ------------------------------------------------------------------ brain turns

    def spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    def spawn_brain(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self.brain_tasks.add(task)
        task.add_done_callback(self.brain_tasks.discard)

    def tools(self, user_words: str, previous_assistant: str | None) -> Tools:
        recent = self.transcripts.recent_user(4) if user_words else ""
        return Tools(self, user_words, previous_assistant, recent)

    def _progress(
        self, voice: Voice, generation: int, delegation: str | None, speak_all: bool
    ) -> Progress:
        async def progress(content: str, pending: list[str]) -> None:
            if generation != self.generation:
                return
            # Speak it only when the user has to do something (hold the page up); otherwise it's
            # a "saving that now" the voice already covers with its own filler.
            if "look_through_camera" in pending:
                await voice.commentary(content.strip(), delegation)
            elif speak_all:
                await voice.thinking(content.strip(), delegation)

        return progress

    async def _turn(
        self,
        voice: Voice,
        generation: int,
        delegation: str | None,
        message: str,
        tools: Tools,
        speak_progress: bool,
    ) -> None:
        """One user-facing brain turn; the answer (or an apology) is always spoken."""
        if not self.brain:
            await voice.commentary("The thinking service isn't configured.", delegation)
            return
        self.brain_busy += 1
        await self.send(self.state())
        try:
            answer = await self.brain.ask(
                message, tools, self._progress(voice, generation, delegation, speak_progress)
            )
            if generation == self.generation:
                await voice.commentary(answer.strip() or "Done.", delegation)
        except Exception as error:  # noqa: BLE001 - the user hears an apology either way
            self.log(f"desk: brain failed: {error}")
            await self.send({"type": "error", "message": f"brain: {error}"})
            if generation == self.generation:
                await voice.commentary(SORRY, delegation)
        finally:
            self.brain_busy -= 1
            self.last_activity = self.clock()
            await self.send(self.state())

    async def delegated(self, voice: Voice, generation: int, identifier: str) -> None:
        # The delegation event carries no text. Give the last transcript fragments a moment to
        # land, then take what the user said since the previous delegation.
        await asyncio.sleep(self.settings.delegation_settle_seconds)
        if generation != self.generation:
            return
        heard = self.transcripts.take_user_request()
        previous = self.transcripts.previous_assistant()
        context = self.transcripts.recent(8)
        self.log(f'desk: delegation {identifier}: "{heard}"')
        message = f"[Heard] {heard or '(nothing transcribed)'}" + (
            f"\n\nRecent voice conversation, for context:\n{context}" if context else ""
        )
        await self._turn(voice, generation, identifier, message, self.tools(heard, previous), True)

    async def on_tapped(self, text: str) -> None:
        """Screen taps don't go through GPT-Live's ears, so they go straight to the brain."""
        self.last_activity = self.clock()
        await self.start()
        voice, generation = self.voice, self.generation
        self.awaiting_reply = None
        if not voice:
            return
        self.transcripts.note("user", " " + text)
        if not self.brain:
            try:
                await voice.say(text)
            except asyncio.QueueFull:
                await self.send({"type": "error", "message": "voice turn queue full"})
            return
        tools = self.tools(text, self.transcripts.previous_assistant())
        self.spawn_brain(
            self._turn(voice, generation, None, f"[Tapped on the desk screen] {text}", tools, False)
        )

    async def _desk_event(self, text: str, tools: Tools) -> str:
        """A brain turn the app started (no user words), counted as thinking."""
        if not self.brain:
            raise RuntimeError("the thinking service isn't configured")
        self.brain_busy += 1
        await self.send(self.state())
        try:
            return await self.brain.ask(text, tools)
        finally:
            self.brain_busy -= 1
            self.last_activity = self.clock()

    # ------------------------------------------------------------------ camera, pages, links

    async def capture(self) -> str:
        if not self.peer:
            raise RuntimeError("the desk phone isn't connected")
        if not self.camera:
            raise RuntimeError("camera unavailable: it is switched off")
        identifier = f"p{secrets.token_hex(6)}"
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self.photos[identifier] = future
        try:
            # No countdown: the phone's always-on camera glances and the view closes by itself.
            await self.send({"type": "capture", "requestId": identifier, "countdownSeconds": 0})
            try:
                return await asyncio.wait_for(future, self.settings.camera_timeout_seconds)
            except TimeoutError:
                raise TimeoutError("the phone didn't send a photo in time") from None
        finally:
            self.photos.pop(identifier, None)

    async def announce_page(self, page: Json) -> None:
        self.log(f'desk: page {page["id"]} "{page["title"]}"')
        # ?v= changes on every update, so the phone reloads a page that kept its id.
        await self.send(
            {
                "type": "page",
                "id": page["id"],
                "title": page["title"],
                "url": f"/p/{page['id']}?v={page['updatedAt']}",
            }
        )

    async def show_today(self) -> None:
        """Puts the Today screen (to-dos, focus, memories) on the phone, replacing the last one."""
        if not self.peer:
            return
        now = self.store.clock()
        html = render_today(self.store, self.settings.time_zone, now)
        try:
            page = await self.pages.save("Today", html, self.store.today_page_id())
        except Exception as error:  # noqa: BLE001 - the Today screen must never break a tool
            # The saved page may have been deleted from the agent page: start a fresh one.
            if self.store.today_page_id():
                await self.store.set_today_page_id("")
                await self.show_today()
            else:
                self.log(f"desk: today page failed: {error}")
            return
        if page["id"] != self.store.today_page_id():
            await self.store.set_today_page_id(page["id"])
        self.last_today_shown = now
        await self.announce_page(page)

    def show_link(self, url: str) -> None:
        """An app Connect Link the user must open; shown on the desk screen."""
        self.log(f"desk: connect link: {url}")
        self.post({"type": "link", "url": url, "label": "Connect app"})

    async def control(self, action: str) -> str:
        """Desk controls the agent can use (the user can always undo them on the screen)."""
        if action in ("camera_on", "camera_off"):
            self.camera = action == "camera_on"
        elif action == "mute_mic":
            self.muted = True
            if self.voice:
                await self.voice.mute(True)
        elif action == "end_conversation":
            self.close_after_reply = True
        await self.send({"type": "control", "action": action})
        await self.send(self.state())
        return CONTROL_REPLIES[action]

    # ------------------------------------------------------------------ presence

    async def on_presence(self, present: bool) -> None:
        """
        Presence from the phone's camera. Coming back after a while is a moment to notice: Toad
        greets the user and follows up on what they were working on.
        """
        now = self.store.clock()
        before = self.presence
        if before and before[0] == present:
            return
        self.presence = (present, now)
        # Seen arriving (or first seen after connecting): put the day on the screen.
        arrived = present and (not before or now - before[1] > 60_000)
        if arrived and now - self.last_today_shown > 2 * 60_000:
            await self.show_today()
        if not present or not before:
            return
        self.awaiting_reply = None
        away_ms = now - before[1]
        focus = self.store.focus()
        hours = self.away.quiet_hours if self.away else None
        quiet = hours is not None and in_quiet_hours(
            local_hour(now, self.settings.time_zone), hours
        )
        live = self.voice_task is not None and not self.voice_task.done()
        if (
            away_ms < WELCOME_AFTER_MS
            or not focus
            or live
            or self.brain_busy > 0
            or now - self.last_welcome < WELCOME_EVERY_MS
            or quiet
            or not self.brain
        ):
            return
        self.last_welcome = now
        minutes = round(away_ms / 60_000)
        self.log(f"desk: user back after {minutes} min; following up")
        await self.start()
        voice, generation = self.voice, self.generation
        try:
            answer = await self._desk_event(
                f"[Desk event] The camera shows the user just came back to the desk after "
                f"{minutes} minutes away. Their focus was: {focus['task']}. Welcome them back in "
                "one short sentence and ask one question about that focus.",
                self.tools("", None),
            )
            if voice and generation == self.generation:
                await voice.commentary(answer.strip(), None)
        except Exception as error:  # noqa: BLE001 - a missed welcome is only logged
            self.log(f"desk: welcome back failed: {error}")

    # ------------------------------------------------------------------ check-ins and idle

    def start_scheduler(self) -> None:
        if self.scheduler_task is None or self.scheduler_task.done():
            self.scheduler_task = asyncio.create_task(self.scheduler())

    async def scheduler(self) -> None:
        while True:
            await asyncio.sleep(self.settings.scheduler_interval_seconds)
            try:
                await self.tick()
            except Exception as error:  # noqa: BLE001 - keep ticking
                self.log(f"desk: tick failed: {error!r}")
                await self.send({"type": "error", "message": "scheduled desk update failed"})

    async def tick(self) -> None:
        async with self.tick_lock:
            now = self.clock()
            wall = self.store.clock()
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
                        self.close_after_reply = False
                    else:
                        self.log("desk: voice session idle; closing it")
                    await self.stop()
                    active = False
            # Always listening: reopen a dropped or expired voice session (at most every 10 s).
            if (
                self.settings.always_listen
                and self.peer
                and not active
                and not self.listen_paused
                and not self.calling
                and now - self.last_open >= self.settings.reconnect_seconds
            ):
                await self.start()
            if self.awaiting_reply and self.away:
                checkin, since = self.awaiting_reply
                if wall - since > self.away.no_reply_seconds * 1000:
                    self.awaiting_reply = None
                    await self.stop()
                    self.spawn(
                        self.call_away(checkin, "Toad asked at the desk and nobody answered")
                    )
            due = [c for c in self.store.pending_checkins() if c["dueAt"] <= wall]
            if not self.peer:
                # With phone calls set up, an offline desk means call; otherwise wait for the phone.
                if not self.away or wall - self.started_at < STARTUP_GRACE_MS:
                    return
                for checkin in due:
                    await self.store.mark_checkin_fired(checkin["id"])
                    self.spawn(self.call_away(checkin, "the desk phone is offline"))
                return
            gone_for = 0
            if self.presence and not self.presence[0]:
                gone_for = wall - self.presence[1]
            for checkin in due:
                await self.store.mark_checkin_fired(checkin["id"])
                if self.away and gone_for > AWAY_BY_CAMERA_MS:
                    self.spawn(
                        self.call_away(checkin, "the desk camera hasn't seen them for a while")
                    )
                else:
                    await self.deliver_checkin(checkin)

    async def deliver_checkin(self, checkin: Json) -> None:
        self.log(f"desk: check-in due: {checkin['about']}")
        await self.send({"type": "checkin", "about": checkin["about"]})
        await self.start()
        self.last_activity = self.clock()
        voice, generation = self.voice, self.generation
        if voice:
            self.spawn_brain(self._checkin_turn(voice, generation, checkin))

    async def _checkin_turn(self, voice: Voice, generation: int, checkin: Json) -> None:
        try:
            late = round((self.store.clock() - checkin["dueAt"]) / 60_000)
            delay = f" ({late} minutes late; the phone was offline)" if late > 2 else ""
            answer = await self._desk_event(
                f"[Desk event] Check-in due{delay}: {checkin['about']}. "
                "Check in with the user now, in one or two sentences.",
                self.tools("", None),
            )
            # Not tied to a delegation: GPT-Live speaks it as a new turn.
            if generation == self.generation:
                await voice.commentary(answer.strip(), None)
            if self.away:
                self.awaiting_reply = (checkin, self.store.clock())
        except Exception as error:  # noqa: BLE001 - fall back to a plain spoken check-in
            self.log(f"desk: check-in failed: {error}")
            if generation == self.generation:
                about = str(checkin["about"]).removeprefix("Focus check-in: ")
                await voice.commentary(f"Quick check-in: {about}. How's it going?", None)
        finally:
            await self.send(self.state())

    # ------------------------------------------------------------------ phone calls

    def place_call(self, to: str | None, reason: str, caller_name: str | None) -> str | None:
        """Starts a phone call (to the user when `to` is None). Returns a problem, or None."""
        away = self.away
        if not away:
            return (
                "Phone calls aren't set up yet: the user's own number (OWNER_PHONE) and the "
                "AgentPhone key go in .env."
            )
        if self.calling:
            return "A call is already in progress."
        now = self.store.clock()
        self.calling = True  # claimed now: the call task starts on the next loop turn
        if not to or to == away.to_number:
            checkin = {"id": f"call{now}", "dueAt": now, "createdAt": now, "about": reason}
            self.spawn(self.call_away(checkin, "the user asked Toad to call them", True, True))
        else:
            self.spawn(self.call_for_user(to, reason, caller_name, True))
        return None

    async def call_away(
        self, checkin: Json, why: str, requested: bool = False, claimed: bool = False
    ) -> None:
        """
        The user isn't at the desk: call their phone from Toad's AgentPhone number. AgentPhone's
        hosted voice AI runs the call; afterwards the transcript goes to the brain so focus and
        check-ins reflect what was said.
        """
        away = self.away
        if not away or (self.calling and not claimed):
            return
        now = self.store.clock()
        hour = local_hour(now, self.settings.time_zone)
        if not requested and away.quiet_hours and in_quiet_hours(hour, away.quiet_hours):
            self.log(f"desk: {why}, but it's quiet hours; not calling")
            return
        self.calling = True
        about = str(checkin["about"])
        task = about.removeprefix("Focus check-in: ")
        self.log(f'desk: {why}; calling {mask(away.to_number)} about "{task}"')
        await self.send({"type": "calling", "about": about})
        try:
            memories = "\n".join(f"- {m['text']}" for m in self.store.memories())
            reason = (
                f"{why}. Topic: {about}"
                if requested
                else f"a check-in came due and {why}. Check-in: {about}"
            )
            greeting = (
                "Hi, it's Toad, your AI desk buddy, calling like you asked. What's up?"
                if requested
                else "Hi, it's Toad, your AI desk buddy. You're away from your desk, so I'm "
                f"calling for a quick check-in on {task}. How's it going?"
            )
            remembered = f"Things the user asked you to remember:\n{memories}\n" if memories else ""
            result = await away.caller.call(
                CallRequest(
                    to_number=away.to_number,
                    initial_greeting=greeting,
                    system_prompt=(
                        "You are Toad, the user's AI desk buddy, which normally lives in a phone "
                        f"on their desk. You are calling the user's own phone because {reason}. "
                        f"It is {local_time(now, self.settings.time_zone)}.\n{remembered}\n"
                        "Goal: a friendly check-in of under a minute. Ask how it's going and "
                        "whether they want to keep going, take a break or switch tasks, and when "
                        "they'll be back at the desk. If they ask you to remember something or "
                        "change their plan, say you'll update it when you hang up. If they're "
                        "busy or it's a bad time, apologise briefly and end the call. Speak in "
                        "short sentences. Never pretend to be human. Say goodbye and end the "
                        "call when done."
                    ),
                )
            )
            lines = "\n".join(
                f"{'User' if t.get('role') == 'user' else 'Toad'}: {t.get('content', '')}"
                for t in result.transcript
            )
            user_words = " ".join(
                str(t.get("content", "")) for t in result.transcript if t.get("role") == "user"
            )
            if not lines:
                self.log(f"desk: call {result.id} {result.status} with no conversation")
                return
            await self._desk_event(
                f'[Desk event] The user was away, so you phoned them about "{about}". Call '
                f"transcript:\n{lines}\n\nUpdate the focus or schedule a check-in if they asked; "
                "save a memory only if they explicitly asked you to remember something. Reply "
                "with one sentence summarising the call for the desk screen.",
                self.tools(user_words, None),
            )
        except Exception as error:  # noqa: BLE001 - reported on the screen and, if asked, aloud
            self.log(f"desk: phone call failed: {error}")
            await self.send({"type": "error", "message": f"phone call: {error}"})
            if str(checkin["id"]).startswith("call"):
                await self.report_to_user(call_problem(error))
        finally:
            self.calling = False

    async def call_for_user(
        self, to: str, reason: str, caller_name: str | None, claimed: bool = False
    ) -> None:
        """
        Calls someone else for the user (a friend, say), then tells the user how it went. The
        callee hears up front that it's an AI calling on the user's behalf.
        """
        away = self.away
        if not away or (self.calling and not claimed):
            return
        self.calling = True
        who = caller_name or "someone who knows you"
        self.log(f'desk: calling {mask(to)} for the user about "{reason}"')
        await self.send({"type": "calling", "about": f"Calling {to}: {reason}"})
        try:
            result = await away.caller.call(
                CallRequest(
                    to_number=to,
                    initial_greeting=f"Hi, this is Toad, an AI assistant calling on behalf of "
                    f"{who}. Is now an okay time for a quick message?",
                    system_prompt=(
                        f"You are Toad, an AI assistant calling on behalf of {who}, who asked you "
                        f"to make this call. Purpose, in their words: {reason}\nSay early on that "
                        "you're an AI assistant calling for them. Deliver the purpose briefly and "
                        "politely, and listen to the reply so you can report it back. If they "
                        "ask, you may take a short message or a call-back time. Don't share "
                        f"anything about {who} beyond the purpose. If it's a bad time or they "
                        "don't want to talk, apologise and end the call. Never pretend to be "
                        "human. Keep it under two minutes, then say goodbye and end the call."
                    ),
                )
            )
            lines = "\n".join(
                f"{'Them' if t.get('role') == 'user' else 'Toad'}: {t.get('content', '')}"
                for t in result.transcript
            )
            outcome = (
                f" Transcript:\n{lines}" if lines else " Nobody answered (or it went to voicemail)."
            )
            report = await self._desk_event(
                f'[Desk event] You phoned {to} for the user about "{reason}". Call status: '
                f"{result.status}.{outcome}\n\nTell the user in one or two sentences how it went "
                "and anything the person said back. Don't save memories from this call.",
                self.tools("", None),
            )
            await self.report_to_user(report)
        except Exception as error:  # noqa: BLE001 - reported on the screen and aloud
            self.log(f"desk: call to {mask(to)} failed: {error}")
            await self.send({"type": "error", "message": f"phone call: {error}"})
            await self.report_to_user(call_problem(error))
        finally:
            self.calling = False

    async def report_to_user(self, text: str) -> None:
        """Says it if a voice session is open; otherwise opens one when the phone is there."""
        if not text.strip() or not self.peer:
            return
        await self.start()
        if self.voice:
            await self.voice.commentary(text.strip(), None)
        self.last_activity = self.clock()

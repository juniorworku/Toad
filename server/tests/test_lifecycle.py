import asyncio
import json
from pathlib import Path
from typing import cast

from fastapi import WebSocket
from test_desk import Socket, flush

from toad_server.config import Settings
from toad_server.desk import Desk
from toad_server.store import Store


async def make(tmp_path: Path, always: bool = False) -> tuple[Desk, Socket, list[float]]:
    clock = [100.0]
    store = Store(tmp_path, clock=lambda: int(clock[0] * 1000))
    await store.load()
    desk = Desk(
        Settings(
            device_token="test", data_dir=tmp_path, always_listen=always, idle_close_seconds=20
        ),
        store,
        clock=lambda: clock[0],
    )
    socket = Socket()
    await desk.attach(cast(WebSocket, socket))
    return desk, socket, clock


async def test_idle_waits_for_brain_then_closes(tmp_path: Path) -> None:
    desk, _, clock = await make(tmp_path)
    try:
        await desk.start()
        await asyncio.sleep(0)
        clock[0] += 21
        desk.brain_busy = 1
        await desk.tick()
        assert desk.live == "open"
        desk.brain_busy = 0
        await desk.tick()
        assert desk.live == "idle"
    finally:
        await desk.close()


async def test_always_listen_recovers_but_stop_pauses(tmp_path: Path) -> None:
    desk, _, clock = await make(tmp_path, True)
    try:
        await asyncio.sleep(0)
        assert desk.voice_task
        desk.voice_task.cancel()
        await asyncio.gather(desk.voice_task, return_exceptions=True)
        original = desk.voice_task
        clock[0] += 9
        await desk.tick()
        assert desk.voice_task is original
        clock[0] += 2
        await desk.tick()
        await asyncio.sleep(0)
        assert desk.voice_task is not original and desk.live == "open"
        await desk.message(json.dumps({"type": "stop"}))
        clock[0] += 30
        await desk.tick()
        assert desk.voice_task is None
        await desk.message(json.dumps({"type": "start"}))
        await asyncio.sleep(0)
        assert desk.live == "open"
    finally:
        await desk.close()


async def test_end_after_reply_closes_then_always_listening_resumes(tmp_path: Path) -> None:
    desk, _, clock = await make(tmp_path, True)
    try:
        await asyncio.sleep(0)
        desk.close_after_reply = True
        clock[0] += 2
        await desk.tick()
        assert desk.live == "open"
        clock[0] += 2
        await desk.tick()
        assert desk.live == "idle" and not desk.listen_paused, "closed after the goodbye"
        clock[0] += 20
        await desk.tick()
        assert desk.voice_task is not None, "always-listening reopens later"
    finally:
        await desk.close()


async def test_checkin_once_and_offline_retention(tmp_path: Path) -> None:
    desk, socket, clock = await make(tmp_path)
    try:
        reminder = await desk.store.add_checkin(int(clock[0] * 1000), "Focus check-in: tests")
        assert desk.peer
        await desk.detach(desk.peer)
        await desk.tick()
        assert desk.store.desk()["checkins"][0]["id"] == reminder["id"]
        await desk.attach(cast(WebSocket, socket))
        await asyncio.gather(desk.tick(), desk.tick())
        await flush(desk)
        messages = [m for m in socket.messages if isinstance(m, dict) and m["type"] == "checkin"]
        assert len(messages) == 1
        assert not desk.store.desk()["checkins"]
        reloaded = Store(tmp_path)
        await reloaded.load()
        assert not reloaded.desk()["checkins"]
    finally:
        await desk.close()


async def test_scheduler_is_closed_with_application(tmp_path: Path) -> None:
    desk, _, _ = await make(tmp_path)
    desk.start_scheduler()
    task = desk.scheduler_task
    desk.start_scheduler()
    assert desk.scheduler_task is task
    await desk.close()
    assert task and task.done() and desk.scheduler_task is None

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import WebSocket

from toad_server.config import Settings
from toad_server.desk import Desk
from toad_server.providers import FakeVoice
from toad_server.store import Store


class Socket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any] | bytes] = []
        self.closed = False

    async def send_json(self, value: dict[str, Any]) -> None:
        self.messages.append(value)

    async def send_bytes(self, value: bytes) -> None:
        self.messages.append(value)

    async def close(self, **kwargs: Any) -> None:
        self.closed = True


async def setup(tmp_path: Path, **kwargs: Any) -> tuple[Desk, Socket]:
    store = Store(tmp_path)
    await store.load()
    desk = Desk(
        Settings(device_token="test", data_dir=tmp_path, always_listen=False, **kwargs), store
    )
    socket = Socket()
    await desk.attach(cast(WebSocket, socket))
    return desk, socket


async def flush(desk: Desk) -> None:
    assert desk.peer
    await asyncio.wait_for(desk.peer.queue.join(), 1)


@pytest.mark.asyncio
async def test_muted_pcm_is_not_passed_to_provider(tmp_path: Path) -> None:
    desk, socket = await setup(tmp_path)
    try:
        await desk.start()
        await asyncio.sleep(0)  # let the provider's started event run
        voice = cast(FakeVoice, desk.voice)
        await desk.microphone(bytes(4800))
        await desk.message(json.dumps({"type": "mute"}))
        await desk.microphone(bytes(4800))
        assert voice.received_audio_bytes == 4800
        await desk.message(json.dumps({"type": "unmute"}))
        await desk.microphone(bytes(4800))
        assert voice.received_audio_bytes == 9600
    finally:
        await desk.close()


@pytest.mark.asyncio
async def test_stop_invalidates_queued_audio(tmp_path: Path) -> None:
    desk, socket = await setup(tmp_path)
    try:
        await flush(desk)
        socket.messages.clear()
        await desk.send(b"old audio", desk.generation)
        await desk.stop()
        await flush(desk)
        assert b"old audio" not in socket.messages
        assert any(isinstance(m, dict) and m["type"] == "interrupt" for m in socket.messages)
    finally:
        await desk.close()


@pytest.mark.asyncio
async def test_barge_in_is_throttled_and_time_limited(tmp_path: Path) -> None:
    desk, socket = await setup(tmp_path)
    now = [100.0]
    desk.clock = lambda: now[0]
    try:
        desk.last_voice = 99
        await desk.transcript("user", "stop")
        await desk.transcript("user", "please")
        now[0] = 101.1
        await desk.transcript("user", "hello")
        now[0] = 110
        await desk.transcript("user", "later")
        await flush(desk)
        interrupts = [
            m for m in socket.messages if isinstance(m, dict) and m["type"] == "interrupt"
        ]
        assert len(interrupts) == 2
    finally:
        await desk.close()


@pytest.mark.asyncio
async def test_photo_correlation_and_timeout(tmp_path: Path) -> None:
    desk, socket = await setup(tmp_path, camera_timeout_seconds=0.02)
    try:
        pending = asyncio.create_task(desk.capture())
        await asyncio.sleep(0)
        await flush(desk)
        capture = next(m for m in socket.messages if isinstance(m, dict) and m["type"] == "capture")
        await desk.message(json.dumps({"type": "photo", "requestId": "wrong", "image": "wrong"}))
        assert not pending.done()
        await desk.message(
            json.dumps({"type": "photo", "requestId": capture["requestId"], "image": "jpeg-base64"})
        )
        assert await pending == "jpeg-base64"
        with pytest.raises(TimeoutError):
            await desk.capture()
        assert not desk.photos
    finally:
        await desk.close()


@pytest.mark.asyncio
async def test_disconnect_rejects_pending_photo(tmp_path: Path) -> None:
    desk, socket = await setup(tmp_path)
    pending = asyncio.create_task(desk.capture())
    await asyncio.sleep(0)
    await desk.close()
    with pytest.raises(ConnectionError):
        await pending
    assert desk.voice_task is None
    assert desk.peer is None


@pytest.mark.asyncio
async def test_device_forget_persists_and_pushes_snapshot(tmp_path: Path) -> None:
    desk, socket = await setup(tmp_path)
    try:
        memory = await desk.store.add_memory("tea after lunch")
        await desk.message(json.dumps({"type": "forget", "id": memory["id"]}))
        await flush(desk)
        reloaded = Store(tmp_path)
        await reloaded.load()
        assert reloaded.snapshot()["memories"] == []
        assert socket.messages[-1] == reloaded.desk()
    finally:
        await desk.close()


@pytest.mark.asyncio
async def test_slow_device_queue_is_bounded_and_closed(tmp_path: Path) -> None:
    desk, socket = await setup(tmp_path, outbound_queue_size=4)
    try:
        await flush(desk)
        for _ in range(5):
            await desk.send(b"pcm", desk.generation)
        assert socket.closed
        assert desk.peer and desk.peer.closed.is_set()
        assert desk.peer.queue.qsize() <= 4
    finally:
        await desk.close()


@pytest.mark.asyncio
async def test_disabled_camera_and_photo_error_fail_cleanly(tmp_path: Path) -> None:
    desk, socket = await setup(tmp_path)
    try:
        await desk.message(json.dumps({"type": "camera", "enabled": False}))
        with pytest.raises(RuntimeError, match="camera unavailable"):
            await desk.capture()
        await desk.message(json.dumps({"type": "camera", "enabled": True}))
        pending = asyncio.create_task(desk.capture())
        await asyncio.sleep(0)
        identifier = next(iter(desk.photos))
        await desk.message(
            json.dumps(
                {"type": "photo_error", "requestId": identifier, "reason": "permission denied"}
            )
        )
        with pytest.raises(RuntimeError, match="permission denied"):
            await pending
        assert not desk.photos
    finally:
        await desk.close()

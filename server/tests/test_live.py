import asyncio
import base64
import json
from typing import Any

import pytest
from pydantic import SecretStr
from websockets.asyncio.server import ServerConnection, serve

from toad_server.config import Settings
from toad_server.live import LiveVoice
from toad_server.transcript import Transcript


@pytest.mark.asyncio
async def test_live_handshake_audio_delegation_commands_and_graceful_close() -> None:
    commands: list[dict[str, Any]] = []
    emitted: list[dict[str, Any] | bytes] = []
    ready = asyncio.Event()
    audio = asyncio.Event()
    delegated = asyncio.Event()

    async def provider(socket: ServerConnection) -> None:
        commands.append(json.loads(await socket.recv()))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(socket.recv(), 0.02)
        await socket.send(json.dumps({"type": "session.started", "session": {"id": "fake-live"}}))
        await socket.send(
            json.dumps(
                {"type": "session.input_transcript.delta", "delta": "remember tea", "start_ms": 1}
            )
        )
        await socket.send(
            json.dumps(
                {
                    "type": "session.delegation.created",
                    "delegation": {"id": "d1", "target": "client"},
                }
            )
        )
        await socket.send(
            json.dumps(
                {
                    "type": "session.output_audio.delta",
                    "delta": base64.b64encode(bytes(4800)).decode(),
                }
            )
        )
        async for message in socket:
            command = json.loads(message)
            commands.append(command)
            if command["type"] == "session.close":
                await socket.send(
                    json.dumps({"type": "session.closed", "reason": "client_requested"})
                )
                break

    async def emit(event: dict[str, Any] | bytes) -> None:
        emitted.append(event)
        if isinstance(event, bytes):
            audio.set()
        elif event["event"] == "started":
            ready.set()
        elif event["event"] == "delegation":
            delegated.set()

    async with serve(provider, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        voice = LiveVoice(
            Settings(
                device_token="test",
                live_url=f"ws://127.0.0.1:{port}",
                openai_api_key=SecretStr("synthetic"),
            ),
            "You are Toad.",
        )
        await voice.mute(True)  # queued until session.started
        await voice.append_audio(bytes(4800))  # discarded before startup
        running = asyncio.create_task(voice.run(emit))
        try:
            async with asyncio.timeout(3):
                await ready.wait()
                await audio.wait()
                await delegated.wait()
                await voice.append_audio(bytes(4800))
                await voice.commentary("x" * 3000, "d1")
                await voice.close()
                await running
        finally:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
    assert commands[0]["session"]["delegation"] == {"type": "client"}
    assert commands[0]["session"]["audio"]["format"]["rate"] == 24000
    assert commands[1]["type"] == "session.input_audio.mute"
    assert sum(c["type"] == "session.input_audio.append" for c in commands) == 1
    commentary = next(c for c in commands if c["type"] == "session.commentary.append")
    assert len(commentary["content"]) == 1800 and commentary["delegation_id"] == "d1"
    assert any(isinstance(e, dict) and e.get("id") == "d1" for e in emitted)
    assert bytes(4800) in emitted


def test_transcript_interleaving_and_consumed_user_request() -> None:
    transcript = Transcript()
    transcript.add("user", "Remember ")
    transcript.add("assistant", "One second.")
    transcript.add("user", "tea please.")
    assert transcript.take_user_request() == "Remember tea please."
    assert transcript.take_user_request() == ""
    transcript.note("user", "button press")
    assert transcript.take_user_request() == ""
    assert transcript.previous_assistant() == "One second."

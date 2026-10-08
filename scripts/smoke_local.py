"""Start a temporary fake engine and prove the real HTTP/WebSocket audio path."""

import asyncio
import secrets
import socket
import tempfile
from pathlib import Path

import httpx
import uvicorn
from toad_server.config import Settings
from toad_server.main import create_app
from websockets.asyncio.client import connect


async def smoke() -> None:
    token = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(prefix="toad-smoke-") as data:
        app = create_app(Settings(device_token=token, data_dir=Path(data)))
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", access_log=False)
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if serving.done():
                        await serving
                        raise RuntimeError("server exited before startup")
                    await asyncio.sleep(0.01)
                async with httpx.AsyncClient() as http:
                    response = await http.get(f"http://127.0.0.1:{port}/healthz")
                    assert response.status_code == 200 and response.text == "ok"
                async with connect(
                    f"ws://127.0.0.1:{port}/device?token={token}", proxy=None
                ) as device:
                    await device.send('{"type":"say","text":"hello Toad"}')
                    received_text = False
                    async for frame in device:
                        if isinstance(frame, bytes):
                            assert len(frame) == 4800 and received_text
                            break
                        if "[Fake provider] Received: hello Toad" in frame:
                            received_text = True
                print(
                    "PASS: HTTP health, authenticated WebSocket, transcript and 24 kHz PCM tone."
                )
                print("Diagnostic fake only; no AI API calls were made.")
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, 5)
            listener.close()


if __name__ == "__main__":
    asyncio.run(smoke())

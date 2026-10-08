"""For a desk phone with no internet of its own: forwards it over USB to a remote engine.

The phone keeps using ws://localhost:8787 (via `adb reverse tcp:8787 tcp:8787`); this relays the
device WebSocket and page/API requests to ENGINE (e.g. https://toad-engine.fly.dev).
Usage (repo root): .venv/bin/python server/scripts/usb_bridge.py https://your-engine
"""

import asyncio
import contextlib
import functools
import os
import re
import sys

import httpx
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

print = functools.partial(print, flush=True)  # noqa: A001 - visible when piped to a log file


def bridge(engine: str) -> FastAPI:
    engine = engine.rstrip("/")
    ws_engine = re.sub(r"^http", "ws", engine)
    app = FastAPI(docs_url=None, redoc_url=None)

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "DELETE", "PUT"])
    async def relay(path: str, request: Request) -> Response:
        headers = {
            k: v for k, v in request.headers.items() if k in ("authorization", "content-type")
        }
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                up = await http.request(
                    request.method,
                    f"{engine}/{path}",
                    params=request.query_params,
                    headers=headers,
                    content=await request.body(),
                )
        except httpx.HTTPError as error:
            return Response(f"bridge: {error}", status_code=502)
        keep = ("content-type", "content-security-policy", "location", "cache-control")
        passed = {k: v for k, v in up.headers.items() if k in keep}
        return Response(up.content, status_code=up.status_code, headers=passed)

    @app.websocket("/device")
    async def device(phone: WebSocket) -> None:
        query = phone.url.query
        print(f"phone connected → {ws_engine}/device?{re.sub(r'token=[^&]+', 'token=…', query)}")
        try:
            upstream = await connect(
                f"{ws_engine}/device?{query}", max_size=8 * 1024 * 1024, proxy=None
            )
        except InvalidStatus as error:
            code = error.response.status_code
            print(f"engine refused: {code}")
            await phone.close(code=4001, reason=f"engine {code}")
            return
        await phone.accept()

        async def up() -> None:
            while True:
                frame = await phone.receive()
                if frame["type"] == "websocket.disconnect":
                    return
                if frame.get("bytes") is not None:
                    await upstream.send(frame["bytes"])
                elif frame.get("text") is not None:
                    await upstream.send(frame["text"])

        async def down() -> None:
            async for message in upstream:
                if isinstance(message, bytes):
                    await phone.send_bytes(message)
                else:
                    await phone.send_text(message)

        tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except (WebSocketDisconnect, ConnectionClosed):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await upstream.close()
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await phone.close()
            print(f"engine closed {upstream.close_code}")

    return app


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ENGINE", "")
    if not target:
        sys.exit("Usage: usb_bridge.py https://your-engine   (or set ENGINE)")
    port = int(os.environ.get("PORT", "8787"))
    print(f"USB bridge on :{port} → {target}")
    uvicorn.run(bridge(target), host="127.0.0.1", port=port, log_level="warning", access_log=False)

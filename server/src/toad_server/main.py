"""HTTP/device entrypoint with opt-in live providers and a diagnostic default."""

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from anyio import CancelScope
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from openai import AsyncOpenAI

from .brain import AgentBrain, SDKGateway
from .config import Settings
from .desk import Desk
from .live import LiveVoice
from .pages import PAGE_HEADERS, with_kit
from .store import Store


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    store = Store(config.data_dir)
    desk = Desk(config, store)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not config.device_token:
            raise RuntimeError("Set DEVICE_TOKEN to a new random secret before starting Toad")
        await store.load()
        await desk.pages.load()
        client = None
        if config.provider_mode == "openai":
            if not config.openai_api_key.get_secret_value():
                raise RuntimeError("OPENAI_API_KEY is required for PROVIDER_MODE=openai")
            client = AsyncOpenAI(
                api_key=config.openai_api_key.get_secret_value(),
                project=config.openai_project or None,
            )
            try:
                definition = json.loads(await asyncio.to_thread(config.agent_definition.read_text))
                desk.brain = AgentBrain(
                    SDKGateway(client), definition, store, config.brain_timeout_seconds
                )
                await desk.brain.init(config.toad_agent_id or None)
            except BaseException:
                await client.close()
                raise
            desk.voice_factory = lambda: LiveVoice(
                config,
                "You are Toad, a calm desk companion. Be concise. Delegate tools, camera, memory, "
                "tasks and web requests to the client. Do not claim actions succeeded without results.",
            )
        desk.start_scheduler()
        try:
            yield
        finally:
            try:
                await desk.close()
            finally:
                if client:
                    await client.close()

    app = FastAPI(title="Toad", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.desk, app.state.store = desk, store

    @app.get("/healthz", response_class=PlainTextResponse)
    async def health() -> str:
        return "ok"

    @app.get("/p/{identifier}", response_class=HTMLResponse)
    async def page(identifier: str) -> HTMLResponse:
        body = await desk.pages.html(identifier)
        if body is None:
            raise HTTPException(404, "page not found")
        return HTMLResponse(await asyncio.to_thread(with_kit, body), headers=PAGE_HEADERS)

    @app.delete("/api/pages/{identifier}")
    async def delete_page(identifier: str, request: Request) -> dict[str, bool]:
        bearer = request.headers.get("authorization", "")
        if not secrets.compare_digest(bearer.encode(), ("Bearer " + config.device_token).encode()):
            raise HTTPException(401, "unauthorized")
        return {"deleted": await desk.pages.delete(identifier)}

    @app.websocket("/device")
    async def device(socket: WebSocket) -> None:
        token = socket.query_params.get("token", "")
        if not secrets.compare_digest(token.encode(), config.device_token.encode()):
            if "websocket.http.response" in socket.scope.get("extensions", {}):
                await socket.send_denial_response(
                    PlainTextResponse("unauthorized", status_code=401)
                )
            else:
                await socket.close(code=1008)
            return
        await socket.accept()
        peer = await desk.attach(socket)

        async def receive() -> None:
            while not peer.closed.is_set() and desk.peer is peer:
                frame = await socket.receive()
                if frame["type"] == "websocket.disconnect":
                    return
                if frame.get("bytes") is not None:
                    await desk.microphone(frame["bytes"])
                elif frame.get("text") is not None:
                    await desk.message(frame["text"])

        reader = asyncio.create_task(receive())
        closed = asyncio.create_task(peer.closed.wait())
        try:
            done, _ = await asyncio.wait((reader, closed), return_when=asyncio.FIRST_COMPLETED)
            if reader in done:
                await reader
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            # Starlette may cancel the connection scope immediately on disconnect.
            with CancelScope(shield=True):
                for task in (reader, closed):
                    task.cancel()
                await asyncio.gather(reader, closed, return_exceptions=True)
                await desk.detach(peer)

    return app


app = create_app()

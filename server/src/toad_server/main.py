"""HTTP/device entrypoint: the phone socket, the agent page, pages Toad made and app connections."""

import asyncio
import json
import logging
import re
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from anyio import CancelScope
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from openai import AsyncOpenAI

from .apps import Apps
from .brain import AgentBrain, SDKGateway
from .config import Settings
from .desk import AwayCalls, Desk, log
from .live import LiveVoice
from .pages import PAGE_HEADERS, PAGE_ID, with_kit
from .phone import AgentPhone
from .store import Store

PUBLIC = Path(__file__).parent / "public"
NO_STORE = {"Cache-Control": "no-store"}
# Composio connections are cached briefly since the agent page polls every 5 s.
APPS_CACHE_SECONDS = 30


def is_local(request: Request) -> bool:
    """Opened on this computer (not through a tunnel or another host name)."""
    ip = request.client.host if request.client else ""
    host = re.sub(r":\d+$", "", request.headers.get("host", ""))
    return ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1") and host in (
        "localhost",
        "127.0.0.1",
        "[::1]",
    )


class RedactToken(logging.Filter):
    """Uvicorn logs the WebSocket handshake path, which carries the device token: hide it."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "token=" in message:
            record.msg, record.args = re.sub(r"token=[^&\s\"']+", "token=…", message), ()
        return True


for _name in ("uvicorn.error", "uvicorn.access"):
    logging.getLogger(_name).addFilter(RedactToken())


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    store = Store(config.data_dir)
    desk = Desk(config, store)
    definition: dict[str, Any] = {}
    apps_cache: dict[str, Any] = {}

    def authorized(given: str) -> bool:
        return bool(config.device_token) and secrets.compare_digest(
            given.encode(), config.device_token.encode()
        )

    def bearer(request: Request) -> bool:
        return authorized(request.headers.get("authorization", "").removeprefix("Bearer "))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not config.device_token:
            raise RuntimeError("Set DEVICE_TOKEN to a new random secret before starting Toad")
        await store.load()
        await desk.pages.load()
        definition.update(json.loads(await asyncio.to_thread(config.agent_definition.read_text)))
        # The user's apps: Composio's meta tools join the agent's function tools; this server
        # runs them.
        composio_key = config.composio_api_key.get_secret_value()
        if composio_key:
            from composio import Composio  # imported only when apps are switched on

            desk.apps = Apps(Composio(api_key=composio_key), store, config.composio_user_id)
            definition["tools"] = [*definition.get("tools", []), *await desk.apps.init()]
        else:
            log("apps off (set COMPOSIO_API_KEY to enable)")
        phone_key = config.agentphone_api_key.get_secret_value()
        if phone_key and config.owner_phone and config.agentphone_number:
            desk.away = AwayCalls(
                caller=AgentPhone(phone_key, config.agentphone_number),
                to_number=config.owner_phone,
                no_reply_seconds=config.away_call_after_seconds,
                quiet_hours=config.quiet_hours,
            )
            log(
                f"away calls on: from {config.agentphone_number} after "
                f"{config.away_call_after_seconds:g}s without a reply"
            )
        else:
            log(
                "away calls off (set AGENTPHONE_API_KEY, AGENTPHONE_NUMBER and OWNER_PHONE "
                "to enable)"
            )
        client = None
        if config.provider_mode == "openai":
            if not config.openai_api_key.get_secret_value():
                raise RuntimeError("OPENAI_API_KEY is required for PROVIDER_MODE=openai")
            client = AsyncOpenAI(
                api_key=config.openai_api_key.get_secret_value(),
                project=config.openai_project or None,
            )
            try:
                brain = AgentBrain(
                    SDKGateway(client), definition, store, config.brain_timeout_seconds
                )
                await brain.init(config.toad_agent_id or None)
                desk.brain = brain
            except BaseException:
                await client.close()
                raise
            desk.voice_factory = lambda instructions: LiveVoice(config, instructions)
        else:
            log("PROVIDER_MODE=fake: diagnostic text and tones only (set openai for the AI)")
        desk.start_scheduler()
        log("Toad engine ready. Device socket: /device?token=…  Agent page: /agent.html")
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

    async def app_connections() -> dict[str, Any]:
        apps = desk.apps
        if not apps:
            return {"enabled": False, "connections": []}
        cached = apps_cache.get("value")
        if cached is not None and time.monotonic() - apps_cache["at"] < APPS_CACHE_SECONDS:
            return dict(cached)
        value: dict[str, Any] = {"enabled": True, "user": config.composio_user_id}
        try:
            value["connections"] = await apps.connections()
        except Exception as error:  # noqa: BLE001 - shown on the agent page
            value |= {"connections": [], "error": str(error)}
        # Don't cache while a connection is still being approved, so "connecting" flips to
        # connected as soon as Composio marks it ACTIVE.
        pending = any(c["status"] in ("INITIATED", "INITIALIZING") for c in value["connections"])
        apps_cache.clear()
        if not pending:
            apps_cache.update(at=time.monotonic(), value=value)
        return value

    async def overview() -> dict[str, Any]:
        """Everything the agent page shows: who Toad is, what it's connected to, what it keeps."""
        link = store.agent_link()
        tools = []
        for tool in definition.get("tools", []):
            if tool.get("type") == "function":
                kind = "apps" if desk.apps and desk.apps.has(tool["name"]) else "desk"
                tools.append(
                    {"name": tool["name"], "kind": kind, "description": tool.get("description", "")}
                )
            else:
                description = (
                    "Searches the web for current facts."
                    if tool.get("type") == "web_search"
                    else ""
                )
                tools.append(
                    {"name": tool.get("type"), "kind": "hosted", "description": description}
                )
        return {
            "now": store.clock(),
            "timeZone": config.time_zone,
            "agent": {
                "name": definition.get("name"),
                "model": definition.get("model"),
                "reasoning": (definition.get("reasoning") or {}).get("effort"),
                "agentId": link["agentId"],
                "sessionId": link["sessionId"],
                "project": config.openai_project or None,
                "instructions": definition.get("instructions"),
            },
            "voice": {
                "model": config.live_model,
                "voice": config.live_voice,
                "idleCloseSeconds": config.idle_close_seconds,
            },
            "phone": {"number": config.agentphone_number or None},
            "provider": config.provider_mode,
            "status": desk.status(),
            "tools": tools,
            "apps": await app_connections(),
            "focus": store.focus(),
            "focusHistory": list(reversed(store.recent_focus(10))),
            "checkins": store.pending_checkins(),
            "memories": store.memories(),
            "pages": desk.pages.listing(),
        }

    @app.get("/healthz", response_class=PlainTextResponse)
    async def health() -> str:
        return "ok"

    @app.get("/agent")
    async def agent_redirect() -> RedirectResponse:
        return RedirectResponse("/agent.html", status_code=302)

    @app.get("/api/overview")
    async def api_overview(request: Request) -> JSONResponse:
        # Memories and focus are personal: same shared secret as the desk phone.
        if not bearer(request):
            return JSONResponse({"error": "wrong or missing token"}, 401)
        return JSONResponse(await overview(), headers=NO_STORE)

    @app.post("/api/apps/connect")
    async def connect_app(request: Request) -> JSONResponse:
        """Start connecting an app (Gmail, Google Calendar, Slack…): returns a Connect Link."""
        if not bearer(request):
            return JSONResponse({"error": "wrong or missing token"}, 401, headers=NO_STORE)
        if not desk.apps:
            return JSONResponse(
                {"error": "Composio isn't set up: add COMPOSIO_API_KEY to .env"},
                503,
                headers=NO_STORE,
            )
        try:
            body = json.loads((await request.body()) or b"{}")
            url = await desk.apps.connect(
                str(body.get("app") or "") if isinstance(body, dict) else ""
            )
        except Exception as error:  # noqa: BLE001 - reported to the page
            return JSONResponse({"error": str(error)}, 400, headers=NO_STORE)
        apps_cache.clear()  # the new connection shows up as pending on the next overview
        return JSONResponse({"url": url}, headers=NO_STORE)

    @app.get("/p/{identifier}", response_class=HTMLResponse)
    async def page(identifier: str) -> HTMLResponse:
        # The 128-bit ID is the key: the desk screen opens these without the token.
        body = await desk.pages.html(identifier) if PAGE_ID.fullmatch(identifier) else None
        if body is None:
            raise HTTPException(404, "not found")
        return HTMLResponse(await asyncio.to_thread(with_kit, body), headers=PAGE_HEADERS)

    @app.delete("/api/pages/{identifier}")
    async def delete_page(identifier: str, request: Request) -> PlainTextResponse:
        if not bearer(request):
            raise HTTPException(401, "unauthorized")
        deleted = await desk.pages.delete(identifier)
        return PlainTextResponse("", status_code=204 if deleted else 404)

    async def static(name: str, request: Request) -> HTMLResponse:
        try:
            body = await asyncio.to_thread((PUBLIC / name).read_text)
        except OSError:
            raise HTTPException(404, "not found") from None
        # Opened on this computer (localhost): fill in the desk token so the page opens straight
        # away. Requests from any other host, or through a tunnel with another Host name, still
        # need it.
        if is_local(request):
            token = json.dumps(config.device_token).replace("<", "\\u003c")
            body = body.replace(
                "<head>",
                f'<head><script>try{{localStorage.setItem("toad.token",{token})}}catch(e){{}}'
                "</script>",
                1,
            )
        return HTMLResponse(body, headers=NO_STORE)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return await static("index.html", request)

    @app.get("/{name}.html", response_class=HTMLResponse)
    async def public_page(name: str, request: Request) -> HTMLResponse:
        if name not in ("index", "agent"):
            raise HTTPException(404, "not found")
        return await static(f"{name}.html", request)

    @app.websocket("/device")
    async def device(socket: WebSocket) -> None:
        if not authorized(socket.query_params.get("token", "")):
            if "websocket.http.response" in socket.scope.get("extensions", {}):
                await socket.send_denial_response(
                    PlainTextResponse("unauthorized", status_code=401)
                )
            else:
                await socket.close(code=1008)
            return
        await socket.accept()
        client = socket.client.host if socket.client else "?"
        log(f"device connected from {client}")
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

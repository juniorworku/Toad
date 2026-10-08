"""
The user's apps (Calendar, Gmail, Slack, … 500+) through one Composio session. Its meta tools
(search, schemas, execute, connect) become function tools on the Toad agent; when the agent calls
one, this server executes it, so the Composio key never leaves the server. Toad has one owner,
so one stable Composio user ID; the session ID is kept in the store.

The Composio Python SDK is synchronous, so every call runs in a worker thread.
"""

import asyncio
import json
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import Store

Json = dict[str, Any]

# A desk buddy reads and acts on apps; it doesn't need Composio's remote sandbox tools.
SKIP = {"COMPOSIO_REMOTE_BASH_TOOL", "COMPOSIO_REMOTE_WORKBENCH"}
# Big app payloads (full email bodies) slow every following model round; keep results lean.
MAX_OUTPUT_CHARS = 12_000


def field(value: Any, name: str, default: Any = None) -> Any:
    """Reads a field from a dict (TypedDict tools) or an object (SDK models)."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


class Apps:
    def __init__(
        self,
        composio: Any,
        store: "Store",
        user_id: str,
        log: Callable[[str], None] = print,
    ) -> None:
        self.composio, self.store, self.user_id, self.log = composio, store, user_id, log
        self.session: Any = None
        self.names: set[str] = set()

    async def init(self) -> list[Json]:
        """Opens (or reuses) the owner's session and returns its meta tools as function tools."""
        saved = self.store.agent_link()["appsSessionId"]
        if saved:
            try:
                self.session = await asyncio.to_thread(self.composio.sessions.use, saved)
            except Exception as error:  # noqa: BLE001 - any SDK failure means "make a new one"
                self.log(f"apps: saved session {saved} unusable ({error}); creating a new one")
        if self.session is None:
            self.session = await asyncio.to_thread(
                lambda: self.composio.sessions.create(user_id=self.user_id)
            )
            await self.store.set_agent_link({"appsSessionId": self.session.session_id})
        tools = await asyncio.to_thread(self.session.tools)
        definitions: list[Json] = []
        for tool in tools:
            function = field(tool, "function", {})
            name = str(field(function, "name", ""))
            if not name or name in SKIP:
                continue
            definitions.append(
                {
                    "type": "function",
                    "name": name,
                    "description": str(field(function, "description", "") or "").strip(),
                    "parameters": field(function, "parameters")
                    or {"type": "object", "properties": {}},
                }
            )
        self.names = {d["name"] for d in definitions}
        self.log(
            f"apps: session {self.session.session_id} for user {self.user_id} "
            f"({len(definitions)} tools)"
        )
        return definitions

    async def connect(self, toolkit: str) -> str:
        """Starts connecting an app and returns the Connect Link to open."""
        if self.session is None:
            raise RuntimeError("apps aren't set up on the server")
        if not re.fullmatch(r"[a-z0-9_]{2,64}", toolkit):
            raise ValueError("toolkit slugs are lowercase letters, digits and _")
        request = await asyncio.to_thread(self.session.authorize, toolkit)
        url = field(request, "redirect_url")
        if not url:
            raise RuntimeError(f"{toolkit} returned no link to open")
        self.log(f"apps: connect link for {toolkit}")
        return str(url)

    def has(self, name: str) -> bool:
        return name in self.names

    async def connections(self) -> list[Json]:
        """The apps the owner has connected (or started connecting), for the agent page."""
        result = await asyncio.to_thread(
            lambda: self.composio.connected_accounts.list(user_ids=[self.user_id], limit=100)
        )
        return [
            {
                "app": field(field(item, "toolkit"), "slug"),
                "status": "DISABLED" if field(item, "is_disabled") else field(item, "status"),
                "alias": field(item, "alias"),
                "since": field(item, "created_at"),
            }
            for item in field(result, "items", [])
        ]

    async def run(
        self, name: str, args: Json, on_link: Callable[[str], None] | None = None
    ) -> Json:
        """Runs one meta tool. `on_link` gets any Connect Link so the phone can show it."""
        if self.session is None:
            return {"ok": False, "error": "apps aren't set up on the server"}
        try:
            result = await asyncio.to_thread(lambda: self.session.execute(name, arguments=args))
        except Exception as error:  # noqa: BLE001 - reported to the model, which can recover
            return {"ok": False, "error": f"Composio {name} failed: {error}"}
        failure, log_id = field(result, "error"), field(result, "log_id")
        self.log(f"apps: {name} → {f'error: {failure}' if failure else 'ok'} (log {log_id})")
        if failure:
            return {"ok": False, "error": f"{failure} (Composio log {log_id})"}
        text = json.dumps(field(result, "data"), separators=(",", ":"), default=str)
        for url in connect_links(text):
            if on_link:
                on_link(url)
        output = text[:MAX_OUTPUT_CHARS] + "… [truncated]" if len(text) > MAX_OUTPUT_CHARS else text
        return {"ok": True, "output": output}


def connect_links(text: str) -> list[str]:
    """Connect Links in a tool result: the URLs the user must open to authorize an app."""
    # Stop at quotes, whitespace, escapes and closing brackets; drop trailing punctuation
    # (links often arrive inside markdown like "[Connect](https://…).").
    urls = [re.sub(r"[.,;:!?]+$", "", u) for u in re.findall(r"https://[^\"'\s\\)\]>]+", text)]
    found = [
        u
        for u in urls
        if re.search(r"connect|auth|oauth|link", u, re.I) and re.search(r"composio|/link/", u, re.I)
    ]
    return list(dict.fromkeys(found))

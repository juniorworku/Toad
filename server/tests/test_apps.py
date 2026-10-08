"""Composio apps, against a fake of the Python SDK."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fakes import FakeDevice, settle
from fastapi import WebSocket

from toad_server.apps import Apps, connect_links
from toad_server.config import Settings
from toad_server.desk import Desk
from toad_server.store import Store
from toad_server.tools import Tools


def test_connect_links_are_found_and_cleaned() -> None:
    text = json.dumps(
        {
            "results": {
                "googlecalendar": {
                    "redirect_url": "https://connect.composio.dev/link/lk_ABC",
                    "note": "Open [Connect](https://connect.composio.dev/link/lk_ABC).",
                }
            },
            "other": "https://example.com/page",
        }
    )
    assert connect_links(text) == ["https://connect.composio.dev/link/lk_ABC"]


class FakeSession:
    session_id = "trs_1"

    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []

    def tools(self) -> list[dict[str, Any]]:
        def tool(name: str) -> dict[str, Any]:
            return {
                "type": "function",
                "function": {"name": name, "description": name, "parameters": {"type": "object"}},
            }

        return [
            tool("COMPOSIO_SEARCH_TOOLS"),
            tool("COMPOSIO_MANAGE_CONNECTIONS"),
            tool("COMPOSIO_REMOTE_BASH_TOOL"),
        ]

    def execute(self, name: str, *, arguments: Any) -> SimpleNamespace:
        self.executed.append((name, arguments))
        if name == "COMPOSIO_MANAGE_CONNECTIONS":
            data = {"link": "https://connect.composio.dev/link/lk_X"}
            return SimpleNamespace(data=data, error=None, log_id="log_1")
        return SimpleNamespace(data={}, error="rate limited", log_id="log_2")

    def authorize(self, toolkit: str) -> SimpleNamespace:
        return SimpleNamespace(redirect_url=f"https://connect.composio.dev/link/{toolkit}")


class FakeComposio:
    """The shapes the Composio Python SDK (0.25) exposes: sessions.create/use, accounts.list."""

    def __init__(self) -> None:
        self.session = FakeSession()
        self.sessions = SimpleNamespace(create=self.create, use=self.use)
        self.connected_accounts = SimpleNamespace(list=self.accounts)

    def create(self, *, user_id: str) -> FakeSession:
        assert user_id == "toad-owner"
        return self.session

    def use(self, session_id: str) -> FakeSession:
        raise RuntimeError("gone")

    def accounts(self, *, user_ids: list[str], limit: int) -> SimpleNamespace:
        item = SimpleNamespace(
            toolkit=SimpleNamespace(slug="gmail"),
            status="ACTIVE",
            is_disabled=False,
            alias=None,
            created_at="2026-10-05T00:00:00Z",
        )
        return SimpleNamespace(items=[item])


async def test_meta_tools_run_through_the_session_and_links_reach_the_screen(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    await store.load()
    await store.set_agent_link({"appsSessionId": "trs_old"})
    composio = FakeComposio()
    apps = Apps(composio, store, "toad-owner", lambda m: None)
    definitions = await apps.init()
    names = [d["name"] for d in definitions]
    assert names == ["COMPOSIO_SEARCH_TOOLS", "COMPOSIO_MANAGE_CONNECTIONS"], "sandbox skipped"
    assert definitions[0]["type"] == "function" and definitions[0]["parameters"]
    assert store.agent_link()["appsSessionId"] == "trs_1", "unusable saved session replaced"

    desk = Desk(Settings(device_token="t", data_dir=tmp_path, always_listen=False), store)
    desk.log = lambda m: None
    desk.apps = apps
    device = FakeDevice(desk)
    await desk.attach(cast(WebSocket, device))
    tools = Tools(desk, "", None)
    connect = await tools("COMPOSIO_MANAGE_CONNECTIONS", {"toolkits": ["googlecalendar"]})
    assert connect["ok"] is True
    await settle(desk)
    assert device.last("link") == {
        "type": "link",
        "url": "https://connect.composio.dev/link/lk_X",
        "label": "Connect app",
    }
    failed = await tools("COMPOSIO_SEARCH_TOOLS", {})
    assert failed["ok"] is False and "rate limited (Composio log log_2)" in failed["error"]
    assert (await tools("COMPOSIO_REMOTE_BASH_TOOL", {}))["ok"] is False, "skipped isn't runnable"
    assert (await tools("get_desk_status", {}))["ok"] is True
    assert composio.session.executed[0] == (
        "COMPOSIO_MANAGE_CONNECTIONS",
        {"toolkits": ["googlecalendar"]},
    )

    assert await apps.connect("gmail") == "https://connect.composio.dev/link/gmail"
    assert (await apps.connections())[0] == {
        "app": "gmail",
        "status": "ACTIVE",
        "alias": None,
        "since": "2026-10-05T00:00:00Z",
    }
    await desk.close()


async def test_large_results_are_truncated(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    composio = FakeComposio()
    composio.session.execute = lambda name, *, arguments: SimpleNamespace(  # type: ignore[method-assign]
        data={"body": "x" * 20_000}, error=None, log_id="l"
    )
    apps = Apps(composio, store, "toad-owner", lambda m: None)
    await apps.init()
    result = await apps.run("COMPOSIO_SEARCH_TOOLS", {})
    assert result["ok"] and result["output"].endswith("… [truncated]")
    assert len(result["output"]) < 12_100

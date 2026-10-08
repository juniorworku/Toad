from pathlib import Path
from typing import cast

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient
from test_desk import Socket

from toad_server.config import Settings
from toad_server.desk import Desk
from toad_server.main import create_app
from toad_server.pages import PAGE_HEADERS, Pages, with_kit
from toad_server.store import Store
from toad_server.tools import Tools


@pytest.mark.asyncio
async def test_memory_tool_gate_and_state_snapshot(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    desk = Desk(Settings(device_token="test", data_dir=tmp_path, always_listen=False), store)
    socket = Socket()
    await desk.attach(cast(WebSocket, socket))
    try:
        refused = await Tools(desk, "I like tea", None)("save_memory", {"text": "likes tea"})
        assert not refused["ok"] and not store.snapshot()["memories"]
        saved = await Tools(desk, "Remember that I like tea", None)(
            "save_memory", {"text": "likes tea"}
        )
        assert saved["ok"] and store.snapshot()["memories"][0]["text"] == "likes tea"
        assert desk.peer
        await desk.peer.queue.join()
        assert socket.messages[-1] == store.desk()
    finally:
        await desk.close()


@pytest.mark.asyncio
async def test_tasks_update_stable_today_page_and_escape_html(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    desk = Desk(Settings(device_token="test", data_dir=tmp_path), store)
    await desk.pages.load()
    tool = Tools(desk, "", None)
    assert (await tool("add_todo", {"text": "<script>bad</script>"}))["ok"]
    identifier = store.snapshot()["todayPageId"]
    assert (await tool("complete_todo", {"todo": "t1"}))["ok"]
    assert store.snapshot()["todayPageId"] == identifier
    html = await desk.pages.html(identifier)
    assert html and "&lt;script&gt;" in html and "<script>bad</script>" not in html
    assert len(desk.pages.listing()) == 1


@pytest.mark.asyncio
async def test_pages_survive_reload_and_reject_limits_or_traversal(tmp_path: Path) -> None:
    pages = Pages(tmp_path)
    await pages.load()
    page = await pages.save("test", "<body>hello</body>")
    reloaded = Pages(tmp_path)
    await reloaded.load()
    assert await reloaded.html(page["id"]) == "<body>hello</body>"
    assert await reloaded.html("../../etc/passwd") is None
    with pytest.raises(ValueError, match="512 KB"):
        await pages.save("large", "x" * (512 * 1024 + 1))
    assert "data-toad-kit" in with_kit("<body>hello</body>")
    assert "connect-src 'none'" in PAGE_HEADERS["Content-Security-Policy"]


def test_page_http_csp_and_delete_auth(tmp_path: Path) -> None:
    app = create_app(Settings(device_token="test", data_dir=tmp_path))
    with TestClient(app) as client:
        # Use the running application's event loop for atomic page writes.
        page = client.portal.call(app.state.desk.pages.save, "title", "<body>hello</body>")
        response = client.get("/p/" + page["id"])
        assert response.status_code == 200
        assert "sandbox" in response.headers["Content-Security-Policy"]
        assert client.delete("/api/pages/" + page["id"]).status_code == 401
        assert client.delete(
            "/api/pages/" + page["id"], headers={"Authorization": "Bearer test"}
        ).json() == {"deleted": True}
        assert client.get("/p/" + page["id"]).status_code == 404

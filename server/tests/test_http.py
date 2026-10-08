"""The HTTP side: agent page, overview, app connections and the browser test client."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from toad_server.config import Settings
from toad_server.main import create_app
from toad_server.prompt import local_time
from toad_server.store import Store
from toad_server.today import render_today

AUTH = {"Authorization": "Bearer secret"}


def client(tmp_path: Path, **settings: Any) -> TestClient:
    return TestClient(create_app(Settings(device_token="secret", data_dir=tmp_path, **settings)))


def test_agent_redirect_and_static_pages(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        redirect = http.get("/agent", follow_redirects=False)
        assert redirect.status_code == 302 and redirect.headers["location"] == "/agent.html"
        for path in ("/", "/index.html", "/agent.html"):
            page = http.get(path)
            assert page.status_code == 200 and "Toad" in page.text
            assert page.headers["cache-control"] == "no-store"
        assert http.get("/secret.html").status_code == 404


def test_token_is_filled_in_only_for_localhost(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        # TestClient's peer isn't loopback, so a remote browser still has to paste the token.
        assert "secret" not in http.get("/agent.html").text
    from toad_server import main

    local = main.is_local
    try:
        main.is_local = lambda request: True
        with client(tmp_path) as http:
            assert 'localStorage.setItem("toad.token","secret")' in http.get("/agent.html").text
    finally:
        main.is_local = local


def test_overview_needs_the_token_and_reports_the_desk(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        assert http.get("/api/overview").status_code == 401
        assert (
            http.get("/api/overview", headers={"Authorization": "Bearer nope"}).status_code == 401
        )
        store: Store = http.app.state.store  # type: ignore[attr-defined]
        http.portal.call(store.set_focus, "grant intro")
        http.portal.call(store.add_memory, "Grant is due Friday.")
        response = http.get("/api/overview", headers=AUTH)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["agent"]["name"] == "Toad"
        assert data["status"]["device"] is False and data["status"]["voice"] == "idle"
        assert data["status"]["awayCalls"] is None
        assert data["apps"] == {"enabled": False, "connections": []}
        assert data["focus"]["task"] == "grant intro"
        assert [m["text"] for m in data["memories"]] == ["Grant is due Friday."]
        kinds = {t["name"]: t["kind"] for t in data["tools"]}
        assert kinds["web_search"] == "hosted" and kinds["call_phone"] == "desk"
        assert len([k for k in kinds.values() if k == "desk"]) == 12, "all 12 desk tools"
        with http.websocket_connect("/device?token=secret"):
            assert http.get("/api/overview", headers=AUTH).json()["status"]["device"] is True


def test_apps_connect_needs_token_and_composio(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        assert http.post("/api/apps/connect", json={"app": "gmail"}).status_code == 401
        response = http.post("/api/apps/connect", json={"app": "gmail"}, headers=AUTH)
        assert response.status_code == 503 and "COMPOSIO_API_KEY" in response.json()["error"]


def test_away_calls_show_on_the_overview_when_configured(tmp_path: Path) -> None:
    settings = {
        "agentphone_api_key": "k",
        "agentphone_number": "+16282841240",
        "owner_phone": "+15555550123",
        "quiet_hours": "22-8",
    }
    with client(tmp_path, **settings) as http:
        away = http.get("/api/overview", headers=AUTH).json()["status"]["awayCalls"]
        assert away == {"to": "+•••••••0123", "afterSeconds": 60, "quietHours": [22, 8]}


def test_local_time_matches_the_spoken_format() -> None:
    at = 1_759_687_200_000  # 2025-10-05T18:00:00Z
    assert local_time(at, "America/New_York") == "Sunday, October 5 at 2:00 PM EDT"
    assert local_time(at, "Africa/Addis_Ababa") == "Sunday, October 5 at 9:00 PM EAT"


async def test_today_page_escapes_and_counts_down(tmp_path: Path) -> None:
    now = 1_759_687_200_000
    store = Store(tmp_path, clock=lambda: now)
    await store.load()
    html = render_today(store, "UTC", now)
    assert "0 to-dos open" in html and "Nothing on the list" in html
    await store.add_todo("<b>ship</b>")
    await store.set_focus("demo & video")
    await store.add_checkin(now + 25 * 60_000, "Focus check-in: demo")
    html = render_today(store, "UTC", now)
    assert "1 to-do open · focused on demo &amp; video" in html
    assert "&lt;b&gt;ship&lt;/b&gt;" in html
    assert 'data-to="2025-10-05T18:25:00.000Z"' in html
    assert '<div class="eyebrow">Sunday, October 5</div>' in html


def test_device_token_is_redacted_from_uvicorn_logs() -> None:
    import logging

    from toad_server.main import RedactToken

    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "",
        0,
        '%s - "WebSocket %s" %s',
        ("127.0.0.1:5", "/device?token=s3cret&x=1", "[accepted]"),
        None,
    )
    assert RedactToken().filter(record)
    assert record.getMessage() == '127.0.0.1:5 - "WebSocket /device?token=…&x=1" [accepted]'
    assert any(isinstance(f, RedactToken) for f in logging.getLogger("uvicorn.error").filters)

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from toad_server.config import Settings
from toad_server.main import create_app


def app_for(tmp_path: Path, **kwargs: Any) -> Any:
    return create_app(Settings(device_token="test-secret", data_dir=tmp_path, **kwargs))


def until(socket: Any, kind: str, **fields: Any) -> dict[str, Any]:
    for _ in range(100):
        message = socket.receive_json()
        if message.get("type") == kind and all(message.get(k) == v for k, v in fields.items()):
            return message
    raise AssertionError(f"Never received {kind} {fields}")


def test_health_and_bad_token(tmp_path: Path) -> None:
    with TestClient(app_for(tmp_path)) as client:
        assert client.get("/healthz").text == "ok"
        with pytest.raises(WebSocketDenialResponse) as error:
            with client.websocket_connect("/device?token=bad"):
                pass
        assert error.value.status_code == 401


def test_controls_stop_and_restart(tmp_path: Path) -> None:
    with TestClient(app_for(tmp_path)) as client:
        with client.websocket_connect("/device?token=test-secret") as socket:
            assert socket.receive_json()["type"] == "state"
            assert socket.receive_json() == {
                "type": "desk",
                "memories": [],
                "focus": None,
                "checkins": [],
            }
            assert "fake provider" in socket.receive_json()["message"]
            until(socket, "state", live="open")
            socket.send_json({"type": "mute"})
            until(socket, "state", muted=True)
            socket.send_json({"type": "camera", "enabled": False})
            until(socket, "state", camera=False)
            socket.send_json({"type": "stop"})
            until(socket, "interrupt")
            until(socket, "state", live="idle")
            socket.send_json({"type": "start"})
            until(socket, "state", live="open", muted=True, camera=False)


def test_typed_turn_produces_transcripts_and_pcm(tmp_path: Path) -> None:
    with TestClient(app_for(tmp_path, always_listen=False)) as client:
        with client.websocket_connect("/device?token=test-secret") as socket:
            socket.receive_json()
            socket.receive_json()
            socket.receive_json()
            socket.send_json({"type": "say", "text": " hello "})
            until(socket, "transcript", role="user", delta="hello")
            until(socket, "transcript", role="assistant", delta="[Fake provider] Received: hello")
            until(socket, "state", thinking=False)
            assert len(socket.receive_bytes()) == 4800


def test_bad_json_and_invalid_boolean_do_not_change_state(tmp_path: Path) -> None:
    with TestClient(app_for(tmp_path, always_listen=False)) as client:
        with client.websocket_connect("/device?token=test-secret") as socket:
            socket.receive_json()
            socket.receive_json()
            socket.receive_json()
            socket.send_text("not json")
            assert until(socket, "error")["message"] == "messages must be JSON"
            socket.send_json({"type": "camera", "enabled": "false"})
            assert "invalid" in until(socket, "error")["message"]
            socket.send_json({"type": "unmute"})
            until(socket, "state", camera=True)
            socket.send_bytes(b"x")
            assert "even byte length" in until(socket, "error")["message"]


def test_new_device_replaces_old_without_old_detach_stopping_new(tmp_path: Path) -> None:
    with TestClient(app_for(tmp_path)) as client:
        with client.websocket_connect("/device?token=test-secret") as first:
            until(first, "state", live="open")
            with client.websocket_connect("/device?token=test-secret") as second:
                assert first.receive()["type"] == "websocket.close"
                until(second, "state", live="open")
                second.send_json({"type": "camera", "enabled": False})
                until(second, "state", live="open", camera=False)

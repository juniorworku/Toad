"""The device protocol, checked against the Kotlin client's own source and the shared fixtures."""

import json
import re
from pathlib import Path

from toad_server.protocol import device_message

ROOT = Path(__file__).resolve().parents[2]
KOTLIN = ROOT / "android/app/src/main/java/com/toad/companion"
SERVER = ROOT / "server/src/toad_server"
FIXTURES = json.loads((ROOT / "docs/protocol/device-fixtures.json").read_text())


def kotlin_handled() -> set[str]:
    """Message types EngineLink.kt's `when (m.optString("type"))` reacts to."""
    source = (KOTLIN / "engine/EngineLink.kt").read_text()
    return set(re.findall(r'^\s*"(\w+)" -> listener\.', source, re.M))


def kotlin_sent() -> set[str]:
    """Message types the app sends with link.send(...)."""
    source = (KOTLIN / "CompanionViewModel.kt").read_text()
    calls = re.findall(r"link\.send\((.*)", source)
    # Quoted words not followed by `to` are types ("say", or "mute"/"unmute" in an if); the
    # others are field names ("text" to words).
    return {t for call in calls for t in re.findall(r'"(\w+)"(?!\s+to\b)', call)}


def engine_sent() -> set[str]:
    """Message types the Python engine puts on the device socket."""
    sources = "".join((SERVER / name).read_text() for name in ("desk.py", "store.py"))
    return set(re.findall(r'"type": "(\w+)"', sources))


def test_every_message_the_engine_sends_is_handled_by_the_phone() -> None:
    assert engine_sent() == kotlin_handled()


def test_every_message_the_phone_sends_is_accepted_by_the_engine() -> None:
    fixtures = {m["type"]: m for m in FIXTURES["device_to_engine"]}
    assert kotlin_sent() <= set(fixtures), "a fixture for every message the phone sends"
    for message in FIXTURES["device_to_engine"]:
        assert device_message.validate_python(message).type == message["type"]


def test_fixtures_cover_both_directions() -> None:
    assert {m["type"] for m in FIXTURES["engine_to_device"]} == kotlin_handled()
    assert FIXTURES["audio"] == {
        "format": "pcm_s16le",
        "channels": 1,
        "sample_rate": 24000,
        "nominal_frame_bytes": 4800,
    }

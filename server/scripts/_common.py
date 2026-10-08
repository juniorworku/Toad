"""Shared setup for the live-check scripts: real settings and providers, a throwaway desk."""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from toad_server.apps import Apps
from toad_server.brain import AgentBrain, SDKGateway
from toad_server.config import Settings
from toad_server.desk import Desk
from toad_server.store import Store

ROOT = Path(__file__).resolve().parents[2]
DEMO_PHOTO = ROOT / "demo" / "handwritten-todo.jpg"


def settings(**overrides: Any) -> Settings:
    """Reads the repo-root .env, like the engine does when started from the repo root."""
    return Settings(_env_file=ROOT / ".env", **overrides)  # type: ignore[call-arg]


def need(value: str, name: str) -> None:
    if not value:
        sys.exit(f"Set {name} in .env first (see server/.env.example).")


class ScriptDesk(Desk):
    """A desk with no phone: the camera is a file (or off) and pages are printed."""

    def __init__(self, config: Settings, store: Store, photo: Path | None) -> None:
        super().__init__(config, store, log=lambda message: None)
        self.photo = photo
        self.shown: list[dict[str, Any]] = []

    def camera_available(self) -> bool:
        return self.photo is not None

    async def capture(self) -> str:
        import base64

        if not self.photo:
            raise RuntimeError("no camera in this script")
        print(f"  (camera: sending {self.photo.name})")
        return base64.b64encode(self.photo.read_bytes()).decode()

    async def announce_page(self, page: dict[str, Any]) -> None:
        self.shown.append(page)
        print(f'  (page "{page["title"]}" {page["id"]})')

    def show_link(self, url: str) -> None:
        print(f"\n>>> CONNECT LINK (open to authorize): {url}\n")


async def make_desk(
    config: Settings, *, photo: Path | None = None, with_apps: bool = False, temp: bool = True
) -> tuple[ScriptDesk, AsyncOpenAI]:
    """A desk with the real brain (and apps if asked), on a throwaway data folder by default."""
    need(config.openai_api_key.get_secret_value(), "OPENAI_API_KEY")
    data = Path(tempfile.mkdtemp(prefix="toad-smoke-")) if temp else config.data_dir
    store = Store(data)
    await store.load()
    desk = ScriptDesk(config.model_copy(update={"data_dir": data}), store, photo)
    await desk.pages.load()
    definition = json.loads(config.agent_definition.read_text())
    if with_apps:
        need(config.composio_api_key.get_secret_value(), "COMPOSIO_API_KEY")
        from composio import Composio

        desk.apps = Apps(
            Composio(api_key=config.composio_api_key.get_secret_value()),
            store,
            config.composio_user_id,
        )
        definition["tools"] = [*definition["tools"], *await desk.apps.init()]
    client = AsyncOpenAI(
        api_key=config.openai_api_key.get_secret_value(), project=config.openai_project or None
    )
    brain = AgentBrain(SDKGateway(client), definition, store, config.brain_timeout_seconds)
    await brain.init(config.toad_agent_id or None)
    desk.brain = brain
    return desk, client

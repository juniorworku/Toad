from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    device_token: str = ""
    data_dir: Path = Path("./data")
    always_listen: bool = True
    provider_mode: Literal["fake", "openai"] = "fake"
    outbound_queue_size: int = Field(default=128, ge=4)
    camera_timeout_seconds: float = Field(default=20, gt=0)

    openai_api_key: SecretStr = SecretStr("")
    openai_project: str = ""
    live_url: str = "wss://api.openai.com/v1/live/sessions"
    live_model: str = "gpt-live-1"
    live_voice: str = "marin"
    toad_agent_id: str = ""
    agent_definition: Path = Path(__file__).resolve().parents[3] / "agent/toad-agent.json"
    time_zone: str = "Africa/Addis_Ababa"
    brain_timeout_seconds: float = Field(default=150, gt=0)
    delegation_settle_seconds: float = Field(default=0.4, ge=0)

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    port: int = 8787
    device_token: str = ""
    data_dir: Path = Path("./data")
    always_listen: bool = True
    provider_mode: Literal["fake", "openai"] = "fake"
    idle_close_seconds: float = Field(default=120, gt=0)
    reconnect_seconds: float = Field(default=10, gt=0)
    scheduler_interval_seconds: float = Field(default=1, gt=0)
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

    # AgentPhone: with the key and OWNER_PHONE set, Toad phones the user when they're away.
    agentphone_api_key: SecretStr = SecretStr("")
    agentphone_number: str = ""
    owner_phone: str = ""
    away_call_after_seconds: float = Field(default=60, gt=0)
    quiet_hours: Annotated[tuple[int, int] | None, NoDecode] = (22, 8)

    # Companion habits. A break nudge after this many minutes seen at the desk without leaving
    # (0 turns it off), and a short briefing the first time the camera sees you each day.
    break_after_minutes: int = Field(default=50, ge=0)
    morning_briefing: bool = True

    # Composio (the user's apps). Off when the key is empty.
    composio_api_key: SecretStr = SecretStr("")
    composio_user_id: str = "toad-owner"

    @field_validator("quiet_hours", mode="before")
    @classmethod
    def parse_hours(cls, value: object) -> object:
        """`22-8` (start-end, 24h local); anything else turns quiet hours off."""
        if isinstance(value, str):
            match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", value.strip())
            return (int(match[1]), int(match[2])) if match else None
        return value

"""
Minimal AgentPhone REST client (https://agentphone.ai/skills.md): outbound AI calls from Toad's
own number. With a systemPrompt the call runs on AgentPhone's hosted voice AI, so no webhook is
needed; we poll for the transcript afterwards.
"""

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

BASE = "https://api.agentphone.ai"


@dataclass
class CallRequest:
    to_number: str
    system_prompt: str
    initial_greeting: str


@dataclass
class CallResult:
    id: str
    status: str
    # [{"role": "user" | "agent", "content": str}]
    transcript: list[dict[str, str]] = field(default_factory=list)


class PhoneCaller(Protocol):
    async def call(self, request: CallRequest) -> CallResult: ...


class AgentPhone:
    def __init__(
        self,
        api_key: str,
        from_number: str,
        log: Callable[[str], None] = print,
        transport: httpx.AsyncBaseTransport | None = None,
        poll_seconds: float = 5,
        max_call_seconds: float = 20 * 60,
    ) -> None:
        self.api_key, self.from_number, self.log = api_key, from_number, log
        self.transport, self.poll_seconds = transport, poll_seconds
        self.max_call_seconds = max_call_seconds
        self._sender: tuple[str, str] | None = None
        self._sender_lock = asyncio.Lock()

    async def call(self, request: CallRequest) -> CallResult:
        """Places the call and returns once it has ended, with the transcript."""
        async with httpx.AsyncClient(base_url=BASE, transport=self.transport, timeout=30) as http:
            agent_id, number_id = await self._resolve_sender(http)
            started = await self._request(
                http,
                "POST",
                "/v1/calls",
                {
                    "agentId": agent_id,
                    "fromNumberId": number_id,
                    "toNumber": request.to_number,
                    "systemPrompt": request.system_prompt,
                    "initialGreeting": request.initial_greeting,
                },
            )
            call_id = str(started["id"])
            self.log(f"phone: calling {mask(request.to_number)} (call {call_id})")
            deadline = time.monotonic() + self.max_call_seconds
            while True:
                await asyncio.sleep(self.poll_seconds)
                status = str((await self._request(http, "GET", f"/v1/calls/{call_id}"))["status"])
                if status in ("completed", "failed"):
                    t = await self._request(http, "GET", f"/v1/calls/{call_id}/transcript")
                    self.log(f"phone: call {call_id} {status}")
                    return CallResult(call_id, status, list(t.get("transcript") or []))
                if time.monotonic() > deadline:
                    try:
                        await self._request(http, "POST", f"/v1/calls/{call_id}/end")
                    except (RuntimeError, httpx.HTTPError):
                        pass
                    minutes = round(self.max_call_seconds / 60)
                    raise RuntimeError(f"call {call_id} still {status} after {minutes} minutes")

    async def _resolve_sender(self, http: httpx.AsyncClient) -> tuple[str, str]:
        """Finds the agent and number id that own Toad's number (cached once found)."""
        async with self._sender_lock:
            if self._sender is None:
                numbers = await self._request(http, "GET", "/v1/numbers?limit=100")
                mine = next(
                    (
                        n
                        for n in numbers.get("data", [])
                        if n.get("phoneNumber") == self.from_number
                    ),
                    None,
                )
                if not mine:
                    raise RuntimeError(
                        f"{self.from_number} isn't a number on this AgentPhone account"
                    )
                if not mine.get("agentId"):
                    raise RuntimeError(f"{self.from_number} isn't attached to an AgentPhone agent")
                self._sender = (str(mine["agentId"]), str(mine["id"]))
            return self._sender

    async def _request(
        self, http: httpx.AsyncClient, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await http.request(
            method,
            path,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            content=json.dumps(body, separators=(",", ":")) if body is not None else None,
        )
        text = response.text
        if response.is_error:
            hint = (
                " (outbound calls need a payment method on the AgentPhone account)"
                if response.status_code == 402
                else ""
            )
            raise RuntimeError(
                f"AgentPhone {method} {path} → {response.status_code}{hint}: {text[:300]}"
            )
        parsed = json.loads(text) if text else {}
        return parsed if isinstance(parsed, dict) else {}


def mask(number: str) -> str:
    """For logs: keep the last 4 digits only."""
    return re.sub(r"\d(?=\d{4})", "•", number)

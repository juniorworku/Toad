"""Port of Desku's away-call tests (server/test/away.test.ts) and the AgentPhone client tests."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes import FakeBrain, Rig, ms, settle

from toad_server.desk import AwayCalls, Progress, ToolRunner
from toad_server.phone import AgentPhone, CallRequest, CallResult


class FakeCaller:
    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[CallRequest] = []
        self.fail = fail

    async def call(self, request: CallRequest) -> CallResult:
        self.calls.append(request)
        if self.fail:
            raise self.fail
        return CallResult(
            "call_1",
            "completed",
            [
                {"role": "agent", "content": request.initial_greeting},
                {"role": "user", "content": "Going fine. Remember that I owe Sam a reply."},
            ],
        )


async def setup(
    tmp_path: Path, start: str = "2026-10-05T18:00:00Z", **settings: Any
) -> tuple[Rig, FakeCaller]:  # 18:00Z is 2 PM in New York
    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        return "How's the grant intro going?"

    r = await Rig(tmp_path, FakeBrain(script), start, **settings).load()
    caller = FakeCaller()
    r.desk.away = AwayCalls(caller, "+15555550123", 60, (22, 8))
    await r.store.add_checkin(r.wall + 25 * 60_000, "Focus check-in: grant intro")
    return r, caller


async def test_offline_desk_due_checkin_becomes_a_call_and_brain_hears_it(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path)
    r.advance(25 * 60_000)
    await r.tick()
    assert len(caller.calls) == 1
    assert caller.calls[0].to_number == "+15555550123"
    assert "it's Toad, your AI desk buddy" in caller.calls[0].initial_greeting
    assert "grant intro" in caller.calls[0].initial_greeting
    assert "desk phone is offline" in caller.calls[0].system_prompt
    assert r.brain.asked[0].startswith("[Desk event] The user was away, so you phoned them")
    assert "User: Going fine" in r.brain.asked[0]
    assert r.store.pending_checkins() == []
    await r.desk.close()


async def test_the_users_words_on_the_call_count_for_the_memory_rule(tmp_path: Path) -> None:
    r, _ = await setup(tmp_path)
    r.advance(25 * 60_000)
    await r.tick()
    result = await r.brain.tools[0]("save_memory", {"text": "User owes Sam a reply."})
    assert result["ok"] is True
    assert len(r.store.memories()) == 1
    await r.desk.close()


async def test_at_the_desk_no_reply_calls_after_the_wait(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path)
    device = await r.attach()
    r.advance(25 * 60_000)
    await r.tick()
    assert r.lives[0].sent[-1] == ("commentary", "How's the grant intro going?", None)
    r.advance(30_000)
    await r.tick()
    assert caller.calls == [], "still waiting"
    r.advance(31_000)
    await r.tick()
    assert len(caller.calls) == 1
    assert "nobody answered" in caller.calls[0].system_prompt
    assert len(device.of("calling")) == 1
    await r.desk.close()


async def test_a_reply_at_the_desk_cancels_the_call(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path)
    await r.attach()
    r.advance(25 * 60_000)
    await r.tick()
    await r.lives[0].started()
    await r.lives[0].user("Pretty good!", 1000)
    r.advance(120_000)
    await r.tick()
    assert caller.calls == []
    await r.desk.close()


async def test_quiet_hours_no_call(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path, "2026-10-06T02:00:00Z")  # 10 PM in New York
    r.advance(25 * 60_000)
    await r.tick()
    assert caller.calls == []
    await r.desk.close()


async def test_agentphone_client_finds_sender_places_call_polls_and_returns_transcript() -> None:
    requests: list[str] = []
    polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        path = request.url.raw_path.decode()
        body = request.content.decode()
        requests.append(f"{request.method} {path}{' ' + body if body else ''}")
        assert request.headers["authorization"] == "Bearer sk_live_test"
        if path.startswith("/v1/numbers"):
            data = [{"id": "num_9", "phoneNumber": "+16282841240", "agentId": "agt_1"}]
            return httpx.Response(200, json={"data": data})
        if path == "/v1/calls":
            return httpx.Response(200, json={"id": "call_7", "status": "in-progress"})
        if path == "/v1/calls/call_7":
            polls += 1
            return httpx.Response(200, json={"status": "in-progress" if polls < 2 else "completed"})
        if path == "/v1/calls/call_7/transcript":
            return httpx.Response(200, json={"transcript": [{"role": "user", "content": "hi"}]})
        return httpx.Response(404, text="nope")

    phone = AgentPhone(
        "sk_live_test", "+16282841240", lambda m: None, httpx.MockTransport(handler), 0.001
    )
    result = await phone.call(CallRequest("+15555550123", "p", "g"))
    assert result == CallResult("call_7", "completed", [{"role": "user", "content": "hi"}])
    assert requests[1] == "POST /v1/calls " + json.dumps(
        {
            "agentId": "agt_1",
            "fromNumberId": "num_9",
            "toNumber": "+15555550123",
            "systemPrompt": "p",
            "initialGreeting": "g",
        },
        separators=(",", ":"),
    )


async def test_agentphone_payment_errors_are_explained() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/v1/numbers" in str(request.url):
            data = [{"id": "n", "phoneNumber": "+16282841240", "agentId": "a"}]
            return httpx.Response(200, json={"data": data})
        return httpx.Response(402, text='{"detail":"payment required"}')

    phone = AgentPhone("k", "+16282841240", lambda m: None, httpx.MockTransport(handler), 0.001)
    with pytest.raises(RuntimeError, match=r"402 \(outbound calls need a payment method"):
        await phone.call(CallRequest("+1", "", ""))


async def test_agentphone_unknown_number_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    phone = AgentPhone("k", "+16282841240", lambda m: None, httpx.MockTransport(handler), 0.001)
    with pytest.raises(RuntimeError, match="isn't a number on this AgentPhone account"):
        await phone.call(CallRequest("+15555550123", "", ""))


async def test_call_me_calls_right_away_even_in_quiet_hours(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path, "2026-10-06T03:00:00Z")  # 11 PM in New York
    await r.attach()
    await r.store.cancel_checkins()
    # A screen tap gives the brain a tool runner, like a voice turn would.
    await r.device.say({"type": "say", "text": "Call me please"})
    result = await r.brain.tools[0](
        "call_phone", {"to": None, "reason": "chat about the hackathon", "caller_name": None}
    )
    assert result["ok"] is True
    await settle(r.desk)
    assert len(caller.calls) == 1
    assert "calling like you asked" in caller.calls[0].initial_greeting
    assert (
        "the user asked Toad to call them. Topic: chat about the hackathon"
        in caller.calls[0].system_prompt
    )
    await r.desk.close()


async def test_call_a_friend_only_when_asked_validated_and_reported(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path)
    await r.store.cancel_checkins()
    await r.attach()
    await r.device.say(
        {"type": "say", "text": "Call my friend at +1 555 010 0199 and tell her I'm running late"}
    )
    tools = r.brain.tools[0]
    bad = await tools("call_phone", {"to": "911", "reason": "x", "caller_name": None})
    assert bad["ok"] is False and "isn't a US or Canada number" in bad["error"]
    result = await tools(
        "call_phone", {"to": "+1 (555) 010-0199", "reason": "running late", "caller_name": "Sam"}
    )
    assert result["ok"] is True
    await settle(r.desk)
    assert len(caller.calls) == 1
    assert caller.calls[0].to_number == "+15550100199"
    assert "AI assistant calling on behalf of Sam" in caller.calls[0].initial_greeting
    assert "Purpose, in their words: running late" in caller.calls[0].system_prompt
    assert r.brain.asked[-1].startswith("[Desk event] You phoned +15550100199 for the user")
    spoken = [m for m in r.lives[-1].sent if m[0] == "commentary" and m[2] is None]
    assert spoken, "outcome spoken at the desk"
    await r.desk.close()


async def test_call_someone_else_refused_when_the_user_never_asked(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path)
    await r.store.cancel_checkins()
    await r.attach()
    await r.device.say({"type": "say", "text": "What's on my list today?"})
    result = await r.brain.tools[0](
        "call_phone", {"to": "+15550100199", "reason": "hi", "caller_name": None}
    )
    assert result["ok"] is False and "didn't ask for this call" in result["error"]
    assert caller.calls == []
    await r.desk.close()


async def test_camera_says_nobody_is_there_so_a_due_checkin_calls(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path)
    device = await r.attach()
    await device.say({"type": "presence", "present": True})
    await device.say({"type": "presence", "present": False})
    r.advance(25 * 60_000)
    await r.tick()
    assert len(caller.calls) == 1
    assert "desk camera hasn't seen them" in caller.calls[0].system_prompt
    await r.desk.close()


async def test_call_consent_can_span_the_exchange(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path)
    await r.store.cancel_checkins()
    await r.attach()
    live = await r.open()
    lines = [
        "Can you call my friend",
        "two four zero, five five five, zero one nine nine",
        "Yeah, that's correct",
        "Tell them I'm running late for the soccer game",
    ]
    for i, words in enumerate(lines):
        await live.user(words, i * 1000)
        await live.assistant("Okay?", i * 1000 + 500)
    await live.user(" ", 9000)
    await live.delegate("d1")
    await settle(r.desk)
    result = await r.brain.tools[-1](
        "call_phone",
        {"to": "+12405550199", "reason": "running late for the soccer game", "caller_name": None},
    )
    assert result["ok"] is True, result.get("error")
    await settle(r.desk)
    assert len(caller.calls) == 1
    await r.desk.close()


async def test_no_credit_on_the_phone_line_is_said_plainly(tmp_path: Path) -> None:
    r, _ = await setup(tmp_path)
    await r.store.cancel_checkins()
    r.desk.away = AwayCalls(
        FakeCaller(RuntimeError("AgentPhone POST /v1/calls → 402 (outbound calls need a payment)")),
        "+15555550123",
        60,
        None,
    )
    await r.attach()
    await r.desk.call_for_user("+15550100199", "hi", None)
    await settle(r.desk)
    said = str(r.lives[-1].spoken()[-1][1])
    assert "no credit yet. Add funds on the AgentPhone billing page" in said
    await r.desk.close()


async def test_right_after_startup_an_offline_phone_is_not_away_yet(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path)
    await r.store.cancel_checkins()
    # Due a minute before the engine started.
    await r.store.add_checkin(ms("2026-10-05T17:59:00Z"), "Focus check-in: stale")
    await r.tick()
    assert caller.calls == [], "grace period after boot"
    r.advance(3 * 60_000)
    await r.tick()
    assert len(caller.calls) == 1
    await r.desk.close()


async def test_call_phone_explains_when_calls_are_not_set_up(tmp_path: Path) -> None:
    r, _ = await setup(tmp_path)
    r.desk.away = None
    await r.attach()
    await r.device.say({"type": "say", "text": "Call me"})
    result = await r.brain.tools[0]("call_phone", {"to": None, "reason": "x", "caller_name": None})
    assert result["ok"] is False and "OWNER_PHONE" in result["error"]
    await r.desk.close()


async def test_a_second_call_in_the_same_turn_is_refused(tmp_path: Path) -> None:
    r, caller = await setup(tmp_path)
    await r.store.cancel_checkins()
    await r.attach()
    await r.device.say({"type": "say", "text": "Call me"})
    tools = r.brain.tools[0]
    first = await tools("call_phone", {"to": None, "reason": "x", "caller_name": None})
    second = await tools("call_phone", {"to": None, "reason": "x", "caller_name": None})
    assert first["ok"] is True
    assert second == {"ok": False, "error": "A call is already in progress."}
    await settle(r.desk)
    assert len(caller.calls) == 1 and r.desk.calling is False
    await r.desk.close()

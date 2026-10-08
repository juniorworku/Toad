"""Port of Desku's engine tests (server/test/desk.test.ts): the desk with a fake voice and brain."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from fakes import FakeBrain, FakeDevice, Rig, answer, ms, settle

from toad_server.desk import Progress, ToolRunner
from toad_server.pages import PAGE_ID

START = "2026-10-05T14:00:00Z"


async def rig(tmp_path: Path, brain: FakeBrain, **settings: Any) -> Rig:
    r = await Rig(tmp_path, brain, START, **settings).load()
    await r.attach()
    return r


async def test_voice_turn_audio_delegation_and_spoken_answer(tmp_path: Path) -> None:
    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        result = await tools("set_focus", {"task": "grant intro", "checkin_minutes": 25})
        assert result["ok"]
        return "You're set on the grant intro. I'll check in in 25 minutes."

    r = await rig(tmp_path, FakeBrain(script))
    await r.device.say({"type": "start"})
    live = r.lives[0]
    assert "Delegate to the backend when" in live.instructions
    await live.running.wait()
    await r.device.mic(4800)  # before started: dropped
    await live.started()
    await r.device.mic(4800)
    assert live.sent == [("connect",), ("audio", 4800)]
    await settle(r.desk)
    assert r.device.last("state") == {
        "type": "state",
        "live": "open",
        "muted": False,
        "camera": True,
        "thinking": False,
    }

    await live.user("I'll work on the grant intro, ", 0)
    await live.user("check in after 25.", 900)
    await live.delegate("del_1")
    await settle(r.desk)
    assert r.brain.asked[0].startswith("[Heard] I'll work on the grant intro, check in after 25.")
    assert "Recent voice conversation, for context:" in r.brain.asked[0]
    assert live.sent[-1] == (
        "commentary",
        "You're set on the grant intro. I'll check in in 25 minutes.",
        "del_1",
    )
    focus = r.store.focus()
    assert focus and focus["task"] == "grant intro"
    assert len(r.store.pending_checkins()) == 1
    desk_message = r.device.last("desk")
    assert desk_message and desk_message["focus"]["task"] == "grant intro"
    assert r.device.last("transcript") == {
        "type": "transcript",
        "role": "user",
        "delta": "check in after 25.",
    }
    await r.desk.close()


async def test_memory_is_refused_unless_the_user_asked(tmp_path: Path) -> None:
    results: list[dict[str, Any]] = []

    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        results.append(await tools("save_memory", {"text": "Grant due Friday."}))
        return "ok"

    r = await rig(tmp_path, FakeBrain(script))
    live = await r.open()
    await live.user("The grant is due Friday.", 0)
    await live.delegate("d1")
    await settle(r.desk)
    await live.user("Remember that the grant is due Friday.", 5000)
    await live.delegate("d2")
    await settle(r.desk)
    assert results[0]["ok"] is False
    assert "didn't ask you to remember" in results[0]["error"]
    assert results[1]["ok"] is True
    assert [m["text"] for m in r.store.memories()] == ["Grant due Friday."]
    await r.desk.close()


async def test_camera_progress_spoken_photo_taken_and_image_returned(tmp_path: Path) -> None:
    tool_result: dict[str, Any] = {}

    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        assert progress
        await progress("Hold it up, counting down.", ["look_through_camera"])
        tool_result.update(await tools("look_through_camera", {}))
        return "It's a to-do list with five items."

    r = await rig(tmp_path, FakeBrain(script))
    live = await r.open()
    await live.user("Read this", 0)
    await live.delegate("d1")
    for _ in range(50):
        await settle(r.desk, 1)
        if r.device.last("capture"):
            break
    assert live.sent[-1] == ("commentary", "Hold it up, counting down.", "d1")
    capture = r.device.last("capture")
    assert capture and capture["countdownSeconds"] == 0
    await r.device.say({"type": "photo", "requestId": capture["requestId"], "image": "SlBFRw=="})
    await settle(r.desk)
    assert tool_result["ok"] is True
    assert tool_result["output"][1]["image_url"] == "data:image/jpeg;base64,SlBFRw=="
    assert tool_result["output"][0]["text"].startswith("Photo from the desk camera, taken Monday")
    assert live.sent[-1] == ("commentary", "It's a to-do list with five items.", "d1")
    await r.desk.close()


async def test_camera_switched_off_fails_without_asking_the_phone(tmp_path: Path) -> None:
    tool_result: dict[str, Any] = {}

    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        tool_result.update(await tools("look_through_camera", {}))
        return "Camera's off."

    r = await rig(tmp_path, FakeBrain(script))
    await r.device.say({"type": "camera", "enabled": False})
    live = await r.open()
    await live.delegate("d1")
    await settle(r.desk)
    assert tool_result["ok"] is False
    assert "switched off" in tool_result["error"]
    assert r.device.last("capture") is None
    await r.desk.close()


async def test_proactive_checkin_opens_voice_and_toad_speaks_first(tmp_path: Path) -> None:
    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        if text.startswith("[Desk event]"):
            return "Hey, 25 minutes are up. How did the grant intro go?"
        return "ok"

    r = await rig(tmp_path, FakeBrain(script))
    due = await r.store.add_checkin(ms("2026-10-05T14:25:00Z"), "Focus check-in: grant intro")
    await r.tick()
    assert len(r.lives) == 0, "not due yet"
    r.advance(25 * 60_000)
    await r.tick()
    assert len(r.lives) == 1
    assert r.brain.asked[0].startswith("[Desk event] Check-in due: Focus check-in: grant intro")
    assert r.lives[0].sent[-1] == (
        "commentary",
        "Hey, 25 minutes are up. How did the grant intro go?",
        None,
    )
    checkin = r.device.last("checkin")
    assert checkin and checkin["about"] == "Focus check-in: grant intro"
    assert all(c["id"] != due["id"] for c in r.store.pending_checkins()), "fired once"
    await r.desk.close()


async def test_late_checkin_says_how_late(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("Back to it?")))
    await r.store.add_checkin(ms("2026-10-05T14:01:00Z"), "Focus check-in: x")
    r.advance(10 * 60_000)
    await r.tick()
    assert "(9 minutes late; the phone was offline)" in r.brain.asked[0]
    await r.desk.close()


async def test_checkins_wait_while_the_phone_is_offline(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("How's it going?")))
    await r.store.add_checkin(ms("2026-10-05T14:01:00Z"), "Focus check-in: x")
    assert r.desk.peer
    await r.desk.detach(r.desk.peer)
    r.advance(5 * 60_000)
    await r.tick()
    assert len(r.lives) == 0
    assert len(r.store.pending_checkins()) == 1
    phone = await r.attach(FakeDevice(r.desk))
    await r.tick()
    assert len(r.lives) == 1
    assert phone.last("checkin")
    await r.desk.close()


async def test_mute_stops_audio_and_tells_live_then_idle_session_closes(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("ok")))
    live = await r.open()
    await r.device.say({"type": "mute"})
    await r.device.mic(4800)
    assert live.sent[1:] == [("mute",)]
    state = r.device.last("state")
    assert state and state["muted"] is True
    r.advance(61_000)
    await r.tick()
    assert live.sent[-1] == ("close",)
    state = r.device.last("state")
    assert state and state["live"] == "idle"
    await r.desk.close()


async def test_brain_failure_says_sorry_and_reports_the_error(tmp_path: Path) -> None:
    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        raise RuntimeError("server_overloaded")

    r = await rig(tmp_path, FakeBrain(script))
    live = await r.open()
    await live.delegate("d1")
    await settle(r.desk)
    assert live.sent[-1][0] == "commentary" and str(live.sent[-1][1]).startswith("Sorry")
    assert live.sent[-1][2] == "d1", "the delegation is always answered"
    error = r.device.last("error")
    assert error and "server_overloaded" in error["message"]
    await r.desk.close()


async def test_empty_delegation_is_still_answered(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("Could you say that again?")))
    live = await r.open()
    await live.delegate("d1")
    await settle(r.desk)
    assert r.brain.asked[0] == "[Heard] (nothing transcribed)"
    assert live.sent[-1] == ("commentary", "Could you say that again?", "d1")
    await r.desk.close()


async def test_a_tap_on_the_screen_is_handled_like_speech_and_spoken_back(tmp_path: Path) -> None:
    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        await tools("set_focus", {"task": "invoices", "checkin_minutes": 10})
        return "Okay, ten more minutes on invoices."

    r = await rig(tmp_path, FakeBrain(script))
    await r.device.say({"type": "say", "text": "10 more minutes, please."})
    await r.lives[0].started()
    await settle(r.desk)
    assert r.brain.asked[0] == "[Tapped on the desk screen] 10 more minutes, please."
    assert r.lives[0].sent[-1] == ("commentary", "Okay, ten more minutes on invoices.", None)
    focus = r.store.focus()
    assert focus and focus["task"] == "invoices"
    await r.desk.close()


async def test_a_screen_tap_is_not_repeated_in_the_next_spoken_request(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("ok")))
    await r.device.say({"type": "say", "text": "Say hello."})
    live = r.lives[0]
    await live.started()
    await settle(r.desk)
    await live.user("Any email I should look at?", 900)
    await live.delegate("d1")
    await settle(r.desk)
    assert r.brain.asked[1].startswith("[Heard] Any email I should look at?")
    await r.desk.close()


async def test_control_desk_reaches_the_phone_and_end_closes_after_goodbye(tmp_path: Path) -> None:
    results: list[dict[str, Any]] = []

    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        for action in ("camera_off", "mute_mic", "show_memories", "fly_away", "end_conversation"):
            results.append(await tools("control_desk", {"action": action}))
        return "Okay, bye!"

    r = await rig(tmp_path, FakeBrain(script))
    live = await r.open()
    await live.delegate("d1")
    await settle(r.desk)
    assert [m["action"] for m in r.device.of("control")] == [
        "camera_off",
        "mute_mic",
        "show_memories",
        "end_conversation",
    ]
    assert results[3]["ok"] is False and "Unknown action" in results[3]["error"]
    assert results[1]["output"].startswith("Mic muted.")
    state = r.device.last("state")
    assert state and state["camera"] is False and state["muted"] is True
    assert ("mute",) in live.sent
    r.advance(4_000)
    await r.tick()
    assert live.sent[-1] == ("close",)
    await r.desk.close()


async def test_show_page_saves_the_page_and_tells_the_phone_where(tmp_path: Path) -> None:
    result: dict[str, Any] = {}

    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        result.update(
            await tools(
                "show_page",
                {
                    "title": "Tickets",
                    "html": "<!doctype html><html><body><h1>3 open</h1></body></html>",
                    "page_id": None,
                },
            )
        )
        return "Your tickets are on the screen."

    r = await rig(tmp_path, FakeBrain(script))
    live = await r.open()
    await live.delegate("d1")
    await settle(r.desk)
    assert result["ok"] is True
    page = r.device.last("page")
    assert page and page["title"] == "Tickets" and PAGE_ID.fullmatch(page["id"])
    assert re.fullmatch(rf"/p/{re.escape(page['id'])}\?v=\d+", page["url"]), "versioned"
    assert f'page_id "{page["id"]}"' in result["output"]
    await r.desk.close()


async def test_presence_welcome_back_after_a_long_absence(tmp_path: Path) -> None:
    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        if text.startswith("[Desk event] The camera"):
            return "Welcome back! How's the grant intro?"
        return "ok"

    r = await rig(tmp_path, FakeBrain(script))
    await r.store.set_focus("grant intro")
    await r.device.say({"type": "presence", "present": True})
    await r.device.say({"type": "presence", "present": False})
    r.advance(12 * 60_000)
    await r.device.say({"type": "presence", "present": True})
    await r.lives[-1].started()
    await settle(r.desk)
    assert (
        "came back to the desk after 12 minutes away. Their focus was: grant intro"
        in (r.brain.asked[-1])
    )
    # Spoken as soon as the session starts (queued like any command sent before session.started).
    assert ("commentary", "Welcome back! How's the grant intro?", None) in r.lives[-1].sent
    # Not again right away.
    await r.lives[-1].close()
    await settle(r.desk)
    await r.device.say({"type": "presence", "present": False})
    r.advance(11 * 60_000)
    await r.device.say({"type": "presence", "present": True})
    assert len([t for t in r.brain.asked if "came back" in t]) == 1
    await r.desk.close()


async def test_presence_shows_in_desk_status_and_capture_has_no_countdown(tmp_path: Path) -> None:
    status: dict[str, Any] = {}

    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        status.update(json.loads((await tools("get_desk_status", {}))["output"]))
        return "ok"

    r = await rig(tmp_path, FakeBrain(script))
    await r.device.say({"type": "presence", "present": True})
    live = await r.open()
    await live.delegate("d1")
    await settle(r.desk)
    assert status["user_at_desk"] == "yes, for 0 min"
    assert status["camera"] == "on"
    assert status["local_time"] == "Monday, October 5 at 10:00 AM EDT"
    capture = asyncio.create_task(r.desk.capture())
    await settle(r.desk, 1)
    message = r.device.last("capture")
    assert message and message["countdownSeconds"] == 0
    await r.device.say({"type": "photo", "requestId": message["requestId"], "image": "x"})
    assert await capture == "x"
    await r.desk.close()


async def test_always_listening_opens_reopens_and_stop_pauses_until_talk(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("ok")), always_listen=True)
    assert len(r.lives) == 1, "opened on connect"
    await r.lives[0].started()
    r.advance(10 * 60_000)
    await r.tick()
    assert r.lives[0].is_open, "no idle close while always listening"
    await r.lives[0].close()  # the provider dropped the session
    await settle(r.desk)
    r.advance(11_000)
    await r.tick()
    assert len(r.lives) == 2, "reopened"
    await r.device.say({"type": "stop"})
    r.advance(60_000)
    await r.tick()
    assert len(r.lives) == 2, "paused after Stop"
    await r.device.say({"type": "start"})
    assert len(r.lives) == 3
    await r.desk.close()


async def test_barge_in_tells_the_phone_to_drop_queued_speech(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("ok")))
    live = await r.open()
    await live.emit(bytes(4800))
    await live.user("wait, stop", 100)
    await settle(r.desk)
    assert len(r.device.of("interrupt")) == 1
    r.advance(10_000)
    await live.user(" and another thing", 200)
    await settle(r.desk)
    assert len(r.device.of("interrupt")) == 1, "no interrupt when Toad isn't talking"
    await r.desk.close()


async def test_todos_add_check_off_and_the_today_screen_refreshes(tmp_path: Path) -> None:
    results: list[dict[str, Any]] = []

    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        results.append(await tools("add_todo", {"text": "Finish the hackathon demo video"}))
        results.append(await tools("add_todo", {"text": "Email Felipe"}))
        results.append(await tools("complete_todo", {"todo": "demo video"}))
        results.append(await tools("complete_todo", {"todo": "nonexistent thing"}))
        return "Added."

    r = await rig(tmp_path, FakeBrain(script))
    live = await r.open()
    await live.user("add finish the hackathon demo video to my to-dos", 0)
    await live.delegate("d1")
    await settle(r.desk)
    assert [x["ok"] for x in results] == [True, True, True, False]
    assert results[0]["output"].startswith('Added "Finish the hackathon demo video" as t1.')
    assert "Open to-dos: t2 Email Felipe" in results[3]["error"]
    assert [(t["text"], t["done"]) for t in r.store.todos()] == [
        ("Finish the hackathon demo video", True),
        ("Email Felipe", False),
    ]
    shown = r.device.of("page")
    assert len(shown) == 3, "Today screen shown after every change"
    assert len({m["id"] for m in shown}) == 1, "same page, updated in place"
    html = await r.desk.pages.html(shown[0]["id"])
    assert html and "Email Felipe" in html
    assert "<s>Finish the hackathon demo video</s>" in html
    assert '<section class="hero">' in html and "1 to-do open" in html
    await r.desk.close()


async def test_today_screen_appears_when_the_camera_sees_the_user_arrive(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("ok")))
    await r.device.say({"type": "presence", "present": True})
    assert len(r.device.of("page")) == 1
    await r.device.say({"type": "presence", "present": False})
    r.advance(30_000)
    await r.device.say({"type": "presence", "present": True})
    assert len(r.device.of("page")) == 1, "not for a short glance away"
    await r.desk.close()


async def test_desk_status_reports_focus_todos_and_checkins(tmp_path: Path) -> None:
    status: dict[str, Any] = {}

    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        status.update(json.loads((await tools("get_desk_status", {}))["output"]))
        return "ok"

    r = await rig(tmp_path, FakeBrain(script))
    await r.store.set_focus("grant intro")
    await r.store.add_checkin(r.wall + 25 * 60_000, "Focus check-in: grant intro")
    await r.store.add_todo("Email Felipe")
    r.advance(5 * 60_000)
    live = await r.open()
    await live.delegate("d1")
    await settle(r.desk)
    assert status["focus"] == {"task": "grant intro", "minutes_ago": 5}
    assert status["upcoming_checkins"] == [
        {"about": "Focus check-in: grant intro", "in_minutes": 20}
    ]
    assert status["todos"] == [{"id": "t1", "text": "Email Felipe"}]
    assert status["user_at_desk"] == "unknown"
    await r.desk.close()


async def test_a_tap_after_stop_does_not_undo_the_pause(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("Ten more minutes.")), always_listen=True)
    await r.device.say({"type": "stop"})
    await r.device.say({"type": "say", "text": "10 more minutes"})
    assert r.desk.listen_paused, "Stop holds until Talk, as in Desku"
    await r.desk.stop()
    r.advance(60_000)
    await r.tick()
    assert r.desk.voice_task is None
    await r.desk.close()


async def test_unknown_and_invalid_messages_are_reported(tmp_path: Path) -> None:
    r = await rig(tmp_path, FakeBrain(answer("ok")))
    await r.device.say({"type": "fly"})
    await r.device.say({"type": "camera", "enabled": "yes"})
    assert [m["message"] for m in r.device.of("error")][-2:] == [
        "unknown message type fly",
        "invalid camera message",
    ]
    await r.desk.close()

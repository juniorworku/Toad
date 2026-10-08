"""Companion habits: reminders, focus time, briefings, breaks, app-change consent, and
welcome-back while always listening."""

import json
from pathlib import Path
from typing import Any

from fakes import FakeBrain, Rig, answer, ms, settle
from test_apps import FakeComposio
from test_away import FakeCaller

from toad_server.apps import Apps
from toad_server.desk import AwayCalls, Progress, ToolRunner
from toad_server.tools import allows_app_write, app_writes

MONDAY_10AM = "2026-10-05T14:00:00Z"  # 10:00 in New York


async def rig(tmp_path: Path, reply: str = "ok", start: str = MONDAY_10AM, **settings: Any) -> Rig:
    r = await Rig(tmp_path, FakeBrain(answer(reply)), start, **settings).load()
    await r.attach()
    return r


async def tool(r: Rig, name: str, args: dict[str, Any], heard: str = "") -> dict[str, Any]:
    """Runs one tool the way a brain turn would, after the user said `heard`."""
    return await r.desk.tools(heard, r.desk.transcripts.previous_assistant())(name, args)


# ---------------------------------------------------------------- welcome back (bug fix)


async def test_welcome_back_works_while_always_listening(tmp_path: Path) -> None:
    """Skipping it whenever a voice session exists would, with always-listening (the default),
    skip it every time."""
    r = await rig(tmp_path, "Welcome back!", always_listen=True)
    await r.lives[0].started()
    await r.store.set_focus("grant intro")
    await r.device.say({"type": "presence", "present": True})
    await r.device.say({"type": "presence", "present": False})
    r.advance(12 * 60_000)
    await r.device.say({"type": "presence", "present": True})
    assert any("came back to the desk after 12 minutes" in t for t in r.brain.asked)
    assert ("commentary", "Welcome back!", None) in r.lives[0].sent, "on the open session"
    await r.desk.close()


async def test_no_welcome_on_top_of_a_conversation(tmp_path: Path) -> None:
    r = await rig(tmp_path, always_listen=True)
    live = r.lives[0]
    await live.started()
    await r.store.set_focus("grant intro")
    await r.device.say({"type": "presence", "present": True})
    await r.device.say({"type": "presence", "present": False})
    r.advance(12 * 60_000)
    await live.user("hey Toad, quick question", 0)
    await r.device.say({"type": "presence", "present": True})
    assert not any("came back" in t for t in r.brain.asked)
    await r.desk.close()


# ---------------------------------------------------------------- morning briefing


async def test_morning_briefing_once_a_day_on_first_sighting(tmp_path: Path) -> None:
    r = await rig(tmp_path, "Morning! Two to-dos today.", morning_briefing=True)
    await r.device.say({"type": "presence", "present": True})
    assert len(r.brain.asked) == 1 and "first time today" in r.brain.asked[0]
    assert ("commentary", "Morning! Two to-dos today.", None) in r.lives[-1].sent
    assert r.store.briefed_on() == "2026-10-05"
    await r.device.say({"type": "presence", "present": False})
    r.advance(3 * 3600_000)
    await r.device.say({"type": "presence", "present": True})
    assert len([t for t in r.brain.asked if "first time today" in t]) == 1, "once a day"
    r.advance(21 * 3600_000)  # 10:00 the next day
    await r.device.say({"type": "presence", "present": False})
    r.advance(5 * 60_000)
    await r.device.say({"type": "presence", "present": True})
    assert len([t for t in r.brain.asked if "first time today" in t]) == 2
    await r.desk.close()


async def test_no_briefing_before_five_or_in_quiet_hours(tmp_path: Path) -> None:
    early = await rig(tmp_path / "a", start="2026-10-05T07:30:00Z", morning_briefing=True)  # 3:30
    await early.device.say({"type": "presence", "present": True})
    assert early.brain.asked == []
    await early.desk.close()
    quiet = await rig(
        tmp_path / "b", start="2026-10-05T14:00:00Z", morning_briefing=True, quiet_hours="9-12"
    )
    await quiet.device.say({"type": "presence", "present": True})
    assert quiet.brain.asked == []
    await quiet.desk.close()


# ---------------------------------------------------------------- break nudges


async def test_break_nudge_after_a_long_stretch_and_not_again_right_away(tmp_path: Path) -> None:
    r = await rig(tmp_path, "Time to stretch?", break_after_minutes=50)
    await r.device.say({"type": "presence", "present": True})
    r.advance(30 * 60_000)
    await r.tick()
    assert r.brain.asked == []
    # A 30-second glance away is not a break.
    await r.device.say({"type": "presence", "present": False})
    r.advance(30_000)
    await r.device.say({"type": "presence", "present": True})
    r.advance(21 * 60_000)
    await r.tick()
    assert len(r.brain.asked) == 1 and "at the desk for 52 minutes" in r.brain.asked[0]
    assert ("commentary", "Time to stretch?", None) in r.lives[-1].sent
    r.advance(10 * 60_000)
    await r.tick()
    assert len(r.brain.asked) == 1, "at most once per stretch"
    r.advance(41 * 60_000)
    await r.tick()
    assert len(r.brain.asked) == 2
    await r.desk.close()


async def test_a_real_break_resets_the_clock_and_zero_turns_it_off(tmp_path: Path) -> None:
    r = await rig(tmp_path, break_after_minutes=50)
    await r.device.say({"type": "presence", "present": True})
    r.advance(40 * 60_000)
    await r.device.say({"type": "presence", "present": False})
    r.advance(5 * 60_000)
    await r.device.say({"type": "presence", "present": True})
    r.advance(20 * 60_000)
    await r.tick()
    assert r.brain.asked == [], "20 minutes since the break"
    await r.desk.close()
    off = await rig(tmp_path / "off", break_after_minutes=0)
    await off.device.say({"type": "presence", "present": True})
    off.advance(5 * 3600_000)
    await off.tick()
    assert off.brain.asked == []
    await off.desk.close()


# ---------------------------------------------------------------- reminders


async def test_reminders_in_minutes_at_a_time_and_bad_input(tmp_path: Path) -> None:
    r = await rig(tmp_path)
    soon = await tool(r, "set_reminder", {"text": "stretch", "in_minutes": 20, "at": None})
    assert soon["ok"] and "10:20 AM" in soon["output"]
    later = await tool(r, "set_reminder", {"text": "call Mom", "in_minutes": None, "at": "15:00"})
    assert later["ok"] and "3:00 PM" in later["output"]
    bad = [
        {"text": "x", "in_minutes": None, "at": None},
        {"text": "x", "in_minutes": 5, "at": "15:00"},
        {"text": "x", "in_minutes": None, "at": "25:00"},
        {"text": "x", "in_minutes": None, "at": "2026-10-01T09:00:00Z"},
        {"text": "x", "in_minutes": 5, "at": None, "repeat": "hourly"},
        {"text": "", "in_minutes": 5, "at": None},
    ]
    for args in bad:
        assert (await tool(r, "set_reminder", args))["ok"] is False, args
    status = json.loads((await tool(r, "get_desk_status", {}))["output"])
    assert [(x["about"], x["at"]) for x in status["reminders"]] == [
        ("stretch", "10:20 AM"),
        ("call Mom", "3:00 PM"),
    ]
    await settle(r.desk)
    page = r.device.last("page")
    html = await r.desk.pages.html(page["id"]) if page else None
    assert html and "Reminders" in html and "call Mom" in html
    await r.desk.close()


async def test_a_due_reminder_is_spoken_as_a_reminder(tmp_path: Path) -> None:
    r = await rig(tmp_path, "Don't forget to call Mom!")
    await tool(r, "set_reminder", {"text": "call Mom", "in_minutes": 5, "at": None})
    r.advance(5 * 60_000)
    await r.tick()
    assert r.brain.asked[-1].startswith("[Desk event] Reminder due: call Mom.")
    assert r.device.last("checkin") == {"type": "checkin", "about": "Reminder: call Mom"}
    assert ("commentary", "Don't forget to call Mom!", None) in r.lives[-1].sent
    await r.desk.close()


async def test_repeating_reminders_come_back_and_weekdays_skip_the_weekend(tmp_path: Path) -> None:
    friday = "2026-10-09T12:00:00Z"  # Friday 8:00 in New York
    r = await rig(tmp_path, start=friday)
    for text, repeat in (("standup", "weekdays"), ("water the plants", "daily")):
        args = {"text": text, "in_minutes": None, "at": "09:00", "repeat": repeat}
        assert (await tool(r, "set_reminder", args))["ok"]
    r.advance(61 * 60_000)  # 9:01
    await r.tick()
    upcoming = {c["about"]: c for c in r.store.pending_checkins()}
    assert upcoming["Reminder: standup"]["dueAt"] == ms("2026-10-12T13:00:00Z"), "Monday 9:00"
    assert upcoming["Reminder: water the plants"]["dueAt"] == ms("2026-10-10T13:00:00Z")
    assert upcoming["Reminder: standup"]["repeat"] == "weekdays"
    await r.desk.close()


async def test_cancel_a_reminder_or_a_focus_checkin_by_words_or_id(tmp_path: Path) -> None:
    r = await rig(tmp_path)
    await tool(r, "set_focus", {"task": "grant intro", "checkin_minutes": 25})
    made = await tool(r, "set_reminder", {"text": "call Mom", "in_minutes": 60, "at": None})
    identifier = made["output"].split()[1]
    assert (await tool(r, "cancel_reminder", {"reminder": "grant"}))["ok"]
    missing = await tool(r, "cancel_reminder", {"reminder": "dentist"})
    assert missing["ok"] is False and "Reminder: call Mom" in missing["error"]
    assert (await tool(r, "cancel_reminder", {"reminder": identifier}))["ok"]
    assert r.store.pending_checkins() == []
    await r.desk.close()


async def test_away_call_for_a_reminder_says_its_a_reminder(tmp_path: Path) -> None:
    r = await Rig(tmp_path, FakeBrain(answer("ok")), MONDAY_10AM).load()
    caller = FakeCaller()
    r.desk.away = AwayCalls(caller, "+15555550123", 60, None)
    await r.store.add_checkin(r.wall, "Reminder: call Mom")
    r.advance(3 * 60_000)
    await r.tick()
    assert caller.calls[0].initial_greeting == (
        "Hi, it's Toad, your AI desk buddy, with your reminder: call Mom."
    )
    await r.desk.close()


# ---------------------------------------------------------------- focus time


async def test_finishing_a_focus_records_it_and_counts_focus_time(tmp_path: Path) -> None:
    r = await rig(tmp_path)
    assert (await tool(r, "finish_focus", {"outcome": "x"}))["ok"] is False, "nothing to finish"
    await tool(r, "set_focus", {"task": "inbox", "checkin_minutes": None})
    r.advance(20 * 60_000)
    await tool(r, "set_focus", {"task": "grant intro", "checkin_minutes": 25})  # switched
    r.advance(30 * 60_000)
    done = await tool(r, "finish_focus", {"outcome": "first draft written"})
    assert done["ok"] and "after 30 min" in done["output"] and "50 min" in done["output"]
    assert r.store.pending_checkins() == [], "its check-in is cancelled"
    status = json.loads((await tool(r, "get_desk_status", {}))["output"])
    assert status["focus"] is None
    assert status["focused_today"] == "50 min"
    assert status["finished_today"] == [
        {"task": "grant intro", "outcome": "first draft written", "minutes": 30}
    ]
    assert status["recently_finished"] == [
        {"task": "grant intro", "outcome": "first draft written"}
    ]
    await settle(r.desk)
    page = r.device.last("page")
    html = await r.desk.pages.html(page["id"]) if page else None
    assert html and "Focused today · 50 min" in html and "first draft written" in html
    await r.desk.close()


async def test_finished_todos_are_dropped_after_a_week(tmp_path: Path) -> None:
    r = await rig(tmp_path)
    await tool(r, "add_todo", {"text": "old thing"})
    await tool(r, "complete_todo", {"todo": "old thing"})
    r.advance(8 * 86_400_000)
    await tool(r, "add_todo", {"text": "new thing"})
    assert [t["text"] for t in r.store.todos()] == ["new thing"]
    await r.desk.close()


# ---------------------------------------------------------------- app changes need a yes


def test_app_writes_are_recognised_and_reads_are_not() -> None:
    send = {"tools": [{"tool_slug": "GMAIL_SEND_EMAIL", "arguments": {"to": "sam@x.com"}}]}
    read = {"tools": [{"tool_slug": "GMAIL_FETCH_EMAILS", "arguments": {"max_results": 10}}]}
    both = {"tools": [read["tools"][0], {"tool_slug": "GOOGLECALENDAR_CREATE_EVENT"}]}
    assert app_writes("COMPOSIO_MULTI_EXECUTE_TOOL", send) == ["GMAIL_SEND_EMAIL"]
    assert app_writes("COMPOSIO_MULTI_EXECUTE_TOOL", read) == []
    assert app_writes("COMPOSIO_MULTI_EXECUTE_TOOL", both) == ["GOOGLECALENDAR_CREATE_EVENT"]
    assert app_writes("COMPOSIO_SEARCH_TOOLS", {"queries": ["send email"]}) == []
    assert allows_app_write("Yes, send it", "I'll email Sam: running late. Send it?")
    assert not allows_app_write("Send Sam an email saying I'm late", None)
    assert not allows_app_write("yes", "I sent it.")
    assert not allows_app_write("", "Send it?")


async def test_app_changes_are_refused_without_a_yes_and_run_after_one(tmp_path: Path) -> None:
    async def script(text: str, tools: ToolRunner, progress: Progress | None) -> str:
        return "ok"

    r = await Rig(tmp_path, FakeBrain(script), MONDAY_10AM).load()
    composio = FakeComposio()
    r.desk.apps = Apps(composio, r.store, "toad-owner", lambda m: None)
    await r.desk.apps.init()
    r.desk.apps.names.add("COMPOSIO_MULTI_EXECUTE_TOOL")
    await r.attach()
    send = {"tools": [{"tool_slug": "GMAIL_SEND_EMAIL", "arguments": {"to": "sam@x.com"}}]}
    refused = await tool(r, "COMPOSIO_MULTI_EXECUTE_TOOL", send, "Email Sam that I'm late")
    assert refused["ok"] is False and "GMAIL_SEND_EMAIL would change" in refused["error"]
    assert composio.session.executed == []
    live = await r.open()
    await live.assistant("I'll email Sam: running late. Should I send it?", 0)
    await live.user("Yes, send it.", 1000)
    allowed = await tool(r, "COMPOSIO_MULTI_EXECUTE_TOOL", send, "Yes, send it.")
    assert allowed["ok"] is False and "rate limited" in allowed["error"], "reached Composio"
    assert composio.session.executed == [("COMPOSIO_MULTI_EXECUTE_TOOL", send)]
    await settle(r.desk)
    await r.desk.close()

"""Desk tools invoked by the saved agent; optional calls/apps stay explicitly unavailable."""

import json
import math
import time
from datetime import datetime
from html import escape
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .memory_policy import allows_save

if TYPE_CHECKING:
    from .desk import Desk

Json = dict[str, Any]
ACTIONS = {
    "camera_on",
    "camera_off",
    "close_camera",
    "mute_mic",
    "show_memories",
    "hide_memories",
    "end_conversation",
}


def text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


class Tools:
    def __init__(self, desk: "Desk", user_words: str, previous_assistant: str | None) -> None:
        self.desk, self.user_words, self.previous_assistant = desk, user_words, previous_assistant

    async def __call__(self, name: str, args: Json) -> Json:
        try:
            return {"ok": True, "output": await self.run(name, args)}
        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as error:
            return {"ok": False, "error": str(error)}

    async def run(self, name: str, args: Json) -> str | list[Json]:
        desk, store = self.desk, self.desk.store
        state = store.snapshot()
        now = int(time.time() * 1000)
        match name:
            case "get_desk_status":
                return json.dumps(
                    {
                        "local_time": datetime.now(ZoneInfo(desk.settings.time_zone)).isoformat(),
                        "focus": state["focus"],
                        "recently_finished": state["focusHistory"][-3:],
                        "memories": state["memories"],
                        "todos": [t for t in state["todos"] if not t["done"]],
                        "due_checkins": [
                            c["about"] for c in store.desk()["checkins"] if c["dueAt"] <= now
                        ],
                        "upcoming_checkins": [
                            {
                                "about": c["about"],
                                "in_minutes": math.ceil((c["dueAt"] - now) / 60000),
                            }
                            for c in store.desk()["checkins"]
                            if c["dueAt"] > now
                        ],
                        "camera": "on" if desk.camera else "off",
                        "user_at_desk": desk.present,
                    }
                )
            case "save_memory":
                if not allows_save(self.user_words, self.previous_assistant):
                    raise ValueError("Not saved: the user didn't ask you to remember this.")
                memory = await store.add_memory(text(args.get("text")))
                await desk.send(store.desk())
                return f"Saved as {memory['id']}."
            case "delete_memory":
                identifier = text(args.get("id"))
                if not await store.delete_memory(identifier):
                    raise ValueError("No memory with that id.")
                await desk.send(store.desk())
                return "Deleted " + identifier
            case "set_focus":
                task = text(args.get("task"))
                await store.set_focus(task)
                await store.cancel_checkins(lambda c: c["about"].startswith("Focus check-in: "))
                minutes = args.get("checkin_minutes")
                if (
                    isinstance(minutes, (int, float))
                    and not isinstance(minutes, bool)
                    and minutes > 0
                ):
                    await store.add_checkin(int(now + minutes * 60000), "Focus check-in: " + task)
                await desk.send(store.desk())
                return "Focus set."
            case "look_through_camera":
                jpeg = await desk.capture()
                return [
                    {"type": "input_text", "text": "Photo from the desk camera."},
                    {"type": "input_image", "image_url": "data:image/jpeg;base64," + jpeg},
                ]
            case "control_desk":
                action = text(args.get("action"))
                if action not in ACTIONS:
                    raise ValueError("Unknown desk control.")
                if action in ("camera_on", "camera_off"):
                    desk.camera = action == "camera_on"
                if action == "mute_mic":
                    desk.muted = True
                    if desk.voice:
                        await desk.voice.mute(True)
                if action == "end_conversation":
                    desk.close_after_reply = True
                await desk.send({"type": "control", "action": action})
                await desk.send(desk.state())
                return "Desk control applied: " + action
            case "add_todo":
                todo = await store.add_todo(text(args.get("text")))
                await self.today()
                return f"Added {todo['text']} as {todo['id']}."
            case "complete_todo" | "remove_todo":
                found = store.find_todo(text(args.get("todo")))
                if not found:
                    raise ValueError("No to-do matches that request.")
                if name == "complete_todo":
                    await store.set_todo_done(found["id"], True)
                else:
                    await store.remove_todo(found["id"])
                await self.today()
                return "Updated " + str(found["text"])
            case "show_today":
                await self.today()
                return "The Today screen is on the desk."
            case "show_page":
                page = await desk.pages.save(
                    text(args.get("title")) or "Toad",
                    text(args.get("html")),
                    text(args.get("page_id")) or None,
                )
                await desk.show_page(page)
                return "Shown as page " + str(page["id"])
            case "call_phone":
                raise ValueError("Phone calls are not configured on this server yet.")
            case _:
                raise ValueError("Unknown function " + name)

    async def today(self) -> None:
        desk = self.desk
        state = desk.store.snapshot()
        focus = state["focus"]["task"] if state["focus"] else "Choose one thing to work on."
        rows = "".join(
            "<li>" + ("✓ " if t["done"] else "○ ") + escape(t["text"]) + "</li>"
            for t in state["todos"]
        )
        memories = "".join("<li>" + escape(m["text"]) + "</li>" for m in state["memories"])
        html = "<html><head><title>Today</title></head><body><main><h1>Today</h1>"
        html += "<section><h2>Focus</h2><p>" + escape(focus) + "</p></section>"
        html += "<section><h2>Tasks</h2><ul>" + rows + "</ul></section>"
        html += "<section><h2>Memories</h2><ul>" + memories + "</ul></section></main></body></html>"
        identifier = state["todayPageId"]
        if identifier and not any(p["id"] == identifier for p in desk.pages.listing()):
            identifier = None
        page = await desk.pages.save("Today", html, identifier)
        if page["id"] != state["todayPageId"]:
            await desk.store.set_today_page_id(page["id"])
        await desk.show_page(page)

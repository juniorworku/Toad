"""Toad's function tools, run on this server when the saved agent's session asks for them."""

import json
import math
import re
from typing import TYPE_CHECKING, Any

from .memory_policy import allows_save
from .prompt import local_time

if TYPE_CHECKING:
    from .desk import Desk

Json = dict[str, Any]
DESK_ACTIONS = (
    "camera_on",
    "camera_off",
    "close_camera",
    "mute_mic",
    "show_memories",
    "hide_memories",
    "end_conversation",
)
FOCUS_CHECKIN = "Focus check-in: "
YES = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|please do|correct|that's right|right)\b"
)  # noqa: E501
CALL_WORDS = re.compile(r"\b(call|ring|phone|dial)\b")


def allows_call(user_words: str, previous_assistant: str | None) -> bool:
    """
    Calling someone other than the user is an outward action, so like memories it needs the
    user's own words: they asked for a call, or said yes right after Toad offered/read it back.
    """
    said = user_words.lower()
    if CALL_WORDS.search(said):
        return True
    offered = re.search(r"\b(call|ring|phone|dial)\b[^?]*\?", (previous_assistant or "").lower())
    return bool(offered and YES.search(said))


def text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def ok(output: str | list[Json]) -> Json:
    return {"ok": True, "output": output}


def err(error: str) -> Json:
    return {"ok": False, "error": error}


class Tools:
    """
    One brain turn's tool runner. `user_words` is what the user said that led to this turn (empty
    for app-initiated turns), used by the memory and call consent rules together with
    `recent_user_words` (the last few user turns) and what Toad said just before.
    """

    def __init__(
        self,
        desk: "Desk",
        user_words: str,
        previous_assistant: str | None,
        recent_user_words: str = "",
    ) -> None:
        self.desk, self.user_words = desk, user_words
        self.previous_assistant, self.recent_user_words = previous_assistant, recent_user_words

    async def __call__(self, name: str, args: Json) -> Json:
        try:
            return await self.run(name, args)
        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as error:
            return err(str(error))

    async def run(self, name: str, args: Json) -> Json:
        desk, store = self.desk, self.desk.store
        now = store.clock()
        match name:
            case "get_desk_status":
                focus = store.focus()
                pending = store.pending_checkins()
                todos = store.todos()
                return ok(
                    json.dumps(
                        {
                            "local_time": local_time(now, desk.settings.time_zone),
                            "focus": focus
                            and {
                                "task": focus["task"],
                                "minutes_ago": (now - focus["startedAt"]) // 60_000,
                            },
                            "recently_finished": [
                                {"task": f["task"], "outcome": f.get("outcome")}
                                for f in store.recent_focus(3)
                                if f.get("doneAt")
                            ],
                            "memories": [
                                {"id": m["id"], "text": m["text"]} for m in store.memories()
                            ],
                            "todos": [
                                {"id": t["id"], "text": t["text"]} for t in todos if not t["done"]
                            ],
                            "done_today": [
                                t["text"]
                                for t in todos
                                if t["done"] and t.get("doneAt") and now - t["doneAt"] < 86_400_000
                            ],
                            "due_checkins": [c["about"] for c in pending if c["dueAt"] <= now],
                            "upcoming_checkins": [
                                {
                                    "about": c["about"],
                                    "in_minutes": math.ceil((c["dueAt"] - now) / 60_000),
                                }
                                for c in pending
                                if c["dueAt"] > now
                            ],
                            "camera": "on" if desk.camera_available() else "off",
                            "user_at_desk": desk.presence_text(),
                        },
                        separators=(",", ":"),
                    )
                )
            case "set_focus":
                task = text(args.get("task"))
                if not task:
                    return err("task is required")
                minutes = args.get("checkin_minutes")
                await store.set_focus(task)
                await store.cancel_checkins(lambda c: str(c["about"]).startswith(FOCUS_CHECKIN))
                if (
                    isinstance(minutes, (int, float))
                    and not isinstance(minutes, bool)
                    and minutes > 0
                ):
                    await store.add_checkin(int(now + minutes * 60_000), FOCUS_CHECKIN + task)
                    shown = int(minutes) if float(minutes).is_integer() else minutes
                    return ok(f"Focus set. Check-in scheduled in {shown} minutes.")
                return ok("Focus set. No check-in scheduled.")
            case "save_memory":
                memory_text = text(args.get("text"))
                if not memory_text:
                    return err("text is required")
                # Enforced here, not just in the prompt: only the user's own request can save.
                if not allows_save(self.user_words, self.previous_assistant):
                    return err(
                        "Not saved: the user didn't ask you to remember this. "
                        "You can offer to remember it instead."
                    )
                memory = await store.add_memory(memory_text)
                return ok(f"Saved as {memory['id']}.")
            case "delete_memory":
                identifier = text(args.get("id"))
                if await store.delete_memory(identifier):
                    return ok(f"Deleted {identifier}.")
                return err(f"No memory with id {identifier}.")
            case "look_through_camera":
                if not desk.camera_available():
                    return err(
                        "The camera is switched off on the desk phone. "
                        "Tell the user they can turn it on."
                    )
                try:
                    jpeg = await desk.capture()
                except (RuntimeError, ConnectionError, TimeoutError) as error:
                    return err(f"No photo: {error or 'the phone did not send a photo in time'}")
                taken = local_time(store.clock(), desk.settings.time_zone)
                return ok(
                    [
                        {
                            "type": "input_text",
                            "text": f"Photo from the desk camera, taken {taken}.",
                        },
                        {"type": "input_image", "image_url": "data:image/jpeg;base64," + jpeg},
                    ]
                )
            case "call_phone":
                raw = text(args.get("to"))
                to = re.sub(r"[^\d+]", "", raw) if raw else None
                if to and not re.fullmatch(r"\+1\d{10}", to):
                    return err(
                        f'"{raw}" isn\'t a US or Canada number in +1XXXXXXXXXX form. '
                        "Ask the user to repeat it."
                    )
                consent = f"{self.recent_user_words} {self.user_words}"
                if to and not allows_call(consent, self.previous_assistant):
                    return err(
                        "Not called: the user's own words didn't ask for this call. "
                        "Read the number back and ask if you should call it."
                    )
                problem = desk.place_call(
                    to,
                    text(args.get("reason")) or "a quick chat",
                    text(args.get("caller_name")) or None,
                )
                if problem:
                    return err(problem)
                if to:
                    return ok(f"Calling {to} now. You'll hear back how it went when the call ends.")
                return ok("Calling the user's phone now. It should ring in a few seconds.")
            case "add_todo":
                todo_text = text(args.get("text"))
                if not todo_text:
                    return err("text is required")
                todo = await store.add_todo(todo_text)
                await desk.show_today()
                still_open = "; ".join(t["text"] for t in store.todos() if not t["done"])
                return ok(
                    f'Added "{todo["text"]}" as {todo["id"]}. It\'s on the Today screen now. '
                    f"Open to-dos: {still_open}"
                )
            case "complete_todo" | "remove_todo":
                query = text(args.get("todo"))
                found = store.find_todo(query)
                if not found:
                    listing = "; ".join(
                        f"{t['id']} {t['text']}" for t in store.todos() if not t["done"]
                    )
                    return err(f'No to-do matches "{query}". Open to-dos: {listing or "none"}')
                if name == "complete_todo":
                    await store.set_todo_done(found["id"], True)
                else:
                    await store.remove_todo(found["id"])
                await desk.show_today()
                verb = "Checked off" if name == "complete_todo" else "Removed"
                return ok(f'{verb} "{found["text"]}". The Today screen is updated.')
            case "show_today":
                await desk.show_today()
                return ok("The Today screen (to-dos, focus, memories) is on the desk screen.")
            case "show_page":
                html = args.get("html") if isinstance(args.get("html"), str) else ""
                page = await desk.pages.save(
                    text(args.get("title")) or "Toad", str(html), text(args.get("page_id")) or None
                )
                await desk.announce_page(page)
                return ok(
                    f"Shown on the desk screen as page {page['id']}. "
                    f'To update it later, pass page_id "{page["id"]}".'
                )
            case "control_desk":
                action = text(args.get("action"))
                if action not in DESK_ACTIONS:
                    return err(f"Unknown action. Use one of: {', '.join(DESK_ACTIONS)}.")
                return ok(await desk.control(action))
            case _:
                if desk.apps and desk.apps.has(name):
                    return await desk.apps.run(name, args, desk.show_link)
                return err(f"Unknown function {name}")

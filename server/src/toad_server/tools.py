"""Toad's function tools, run on this server when the saved agent's session asks for them."""

import json
import math
import re
from typing import TYPE_CHECKING, Any

from .memory_policy import allows_save
from .prompt import local_time, parse_at, when
from .today import duration, focus_today

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
REMINDER = "Reminder: "
REPEATS = ("daily", "weekdays")
# Composio tool slugs (GMAIL_SEND_EMAIL, GOOGLECALENDAR_CREATE_EVENT…) that change something.
APP_WRITE = re.compile(
    r"_(SEND|CREATE|DELETE|UPDATE|POST|REPLY|ADD|REMOVE|MOVE|PATCH|INSERT|ARCHIVE|TRASH|INVITE|"
    r"ACCEPT|DECLINE|CANCEL|FORWARD|UPLOAD|EDIT|SET|STAR|MARK|MODIFY|SHARE|PUBLISH|WRITE|COMMENT|"
    r"MERGE|CLOSE|ASSIGN|SCHEDULE|BOOK|PAY|TRANSFER|RESPOND|RSVP|APPEND|REPLACE|RENAME|COPY|PIN|"
    r"LABEL|SUBMIT|APPROVE|REJECT|ENABLE|DISABLE|RESTORE|CLEAR|EMPTY|REACT)(_|$)"
)
SLUG = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")
YES_TO_QUESTION = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|send it|please do|confirm(ed)?|"
    r"correct|that's right|sounds good|absolutely|definitely)\b"
)


def app_writes(name: str, args: Json) -> list[str]:
    """The app actions in a Composio call that would change something (empty for reads)."""
    if name != "COMPOSIO_MULTI_EXECUTE_TOOL":
        return []
    slugs = SLUG.findall(json.dumps(args))
    return sorted({s for s in slugs if not s.startswith("COMPOSIO_") and APP_WRITE.search(s)})


def allows_app_write(user_words: str, previous_assistant: str | None) -> bool:
    """
    Changing something in the user's apps needs a clear yes in their latest words, right after
    Toad asked (having said exactly what it would do). App-initiated turns never qualify.
    """
    asked = (previous_assistant or "").strip().endswith("?")
    return asked and bool(YES_TO_QUESTION.search(user_words.lower()))


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
                focused, finished = focus_today(store, desk.settings.time_zone, now)
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
                            "focused_today": duration(focused),
                            "finished_today": finished,
                            "reminders": [
                                {
                                    "id": c["id"],
                                    "about": str(c["about"]).removeprefix(REMINDER),
                                    "at": when(c["dueAt"], now, desk.settings.time_zone),
                                    "repeat": c.get("repeat"),
                                }
                                for c in pending
                                if str(c["about"]).startswith(REMINDER)
                            ],
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
            case "finish_focus":
                current = store.focus()
                if not current:
                    return err("There's no focus to finish. Ask what they're working on.")
                outcome = text(args.get("outcome"))
                done = await store.finish_focus(outcome)
                if not done:
                    return err("There's no focus to finish.")
                await store.cancel_checkins(lambda c: str(c["about"]).startswith(FOCUS_CHECKIN))
                await desk.show_today()
                minutes = round((done["doneAt"] - done["startedAt"]) / 60_000)
                focused, _ = focus_today(store, desk.settings.time_zone, store.clock())
                return ok(
                    f'Marked "{current["task"]}" done after {duration(minutes)}. '
                    f"Focused today: {duration(focused)}. Its check-in is cancelled."
                )
            case "set_reminder":
                about = text(args.get("text"))
                if not about:
                    return err("text is required")
                repeat = text(args.get("repeat")) or None
                if repeat and repeat not in REPEATS:
                    return err('repeat must be "daily", "weekdays" or null')
                minutes, at = args.get("in_minutes"), text(args.get("at"))
                zone = desk.settings.time_zone
                if isinstance(minutes, (int, float)) and not isinstance(minutes, bool):
                    if minutes <= 0 or at:
                        return err("Give either in_minutes (above 0) or at, not both.")
                    due = int(now + minutes * 60_000)
                elif at:
                    due = parse_at(at, now, zone)
                    if due <= now:
                        return err(f"{at} is in the past. Ask when they want it.")
                else:
                    return err("Say when: in_minutes, or at (local HH:MM).")
                reminder = await store.add_checkin(due, REMINDER + about, repeat)
                await desk.show_today()
                again = (
                    f", then every {'weekday' if repeat == 'weekdays' else 'day'}" if repeat else ""
                )
                return ok(
                    f"Reminder {reminder['id']} set for {when(due, now, zone)}{again}. "
                    "It's on the Today screen."
                )
            case "cancel_reminder":
                query = text(args.get("reminder")).lower()
                pending = store.pending_checkins()
                found = next((c for c in pending if c["id"] == query), None) or next(
                    (c for c in pending if query and query in str(c["about"]).lower()), None
                )
                if not found:
                    listing = "; ".join(f"{c['id']} {c['about']}" for c in pending) or "none"
                    return err(f'No reminder or check-in matches "{query}". Pending: {listing}')
                await store.cancel_checkins(lambda c: c["id"] == found["id"])
                await desk.show_today()
                return ok(f'Cancelled "{found["about"]}".')
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
                    # Enforced here, not just in the prompt: no change to the user's apps
                    # without their yes to exactly what Toad said it would do.
                    writes = app_writes(name, args)
                    if writes and not allows_app_write(self.user_words, self.previous_assistant):
                        return err(
                            f"Not done: {', '.join(writes)} would change the user's apps. Say "
                            "exactly what you'll do and ask; run it only after they say yes."
                        )
                    return await desk.apps.run(name, args, desk.show_link)
                return err(f"Unknown function {name}")

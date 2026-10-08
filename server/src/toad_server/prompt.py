"""Front-end voice instructions and the spoken local-time format."""

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from .store import Store


def local_time(ms: int, time_zone: str) -> str:
    """Like Intl's en-US long format: "Monday, October 5 at 2:00 PM EDT"."""
    at = datetime.fromtimestamp(ms / 1000, ZoneInfo(time_zone))
    hour = at.hour % 12 or 12
    return (
        f"{at:%A}, {at:%B} {at.day} at {hour}:{at:%M} {'AM' if at.hour < 12 else 'PM'} "
        f"{at.tzname()}"
    )


def local_hour(ms: int, time_zone: str) -> int:
    return datetime.fromtimestamp(ms / 1000, ZoneInfo(time_zone)).hour


def local_day(ms: int, time_zone: str) -> str:
    """The local calendar date, YYYY-MM-DD."""
    return datetime.fromtimestamp(ms / 1000, ZoneInfo(time_zone)).date().isoformat()


def start_of_day(ms: int, time_zone: str) -> int:
    at = datetime.fromtimestamp(ms / 1000, ZoneInfo(time_zone))
    return int(at.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def clock_time(ms: int, time_zone: str) -> str:
    """The local clock time, e.g. "3:05 PM"."""
    return local_time(ms, time_zone).split(" at ")[-1].rsplit(" ", 1)[0]


def when(ms: int, now_ms: int, time_zone: str) -> str:
    """ "3:05 PM" today, "Tue 3:05 PM" on another day."""
    at = datetime.fromtimestamp(ms / 1000, ZoneInfo(time_zone))
    prefix = "" if local_day(ms, time_zone) == local_day(now_ms, time_zone) else f"{at:%a} "
    return prefix + clock_time(ms, time_zone)


def parse_at(text: str, now_ms: int, time_zone: str) -> int:
    """A local "HH:MM" (24h, or "3:30 pm") → its next occurrence; an ISO time with an offset
    → that moment. Raises ValueError otherwise."""
    zone = ZoneInfo(time_zone)
    now = datetime.fromtimestamp(now_ms / 1000, zone)
    clean = text.strip().lower()
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", clean)
    if match:
        hour, minute, half = int(match[1]), int(match[2] or 0), match[3]
        if half:
            if not 1 <= hour <= 12:
                raise ValueError(f'"{text}" is not a time of day')
            hour = hour % 12 + (12 if half == "pm" else 0)
        if hour > 23 or minute > 59:
            raise ValueError(f'"{text}" is not a time of day')
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
        return int(at.timestamp() * 1000)
    try:
        moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f'"{text}" isn\'t a time. Use HH:MM (24h) or an ISO time.') from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return int(moment.timestamp() * 1000)


def next_occurrence(due_ms: int, repeat: str, time_zone: str) -> int:
    """The same local clock time on the next day ("daily") or next weekday ("weekdays")."""
    zone = ZoneInfo(time_zone)
    at = datetime.fromtimestamp(due_ms / 1000, zone)
    day = at.date()
    while True:
        day += timedelta(days=1)
        if repeat != "weekdays" or day.weekday() < 5:
            break
    local = datetime.combine(day, at.time().replace(tzinfo=None), zone)
    return int(local.timestamp() * 1000)


def live_instructions(store: "Store", time_zone: str, now_ms: int) -> str:
    """
    Instructions for gpt-live-1, following OpenAI's Live prompting template: role, backchannel,
    interruptions, then a delegation policy. Business rules and tools live in the backend agent
    (agent/toad-agent.json), not here. Fixed for the life of one voice session.
    """
    focus = store.focus()
    context = (
        f"The user's current focus is: {focus['task']}."
        if focus
        else "You don't know yet what the user is working on; if it fits, ask."
    )
    return f"""# Role
You are Toad, the voice of a desk buddy that lives in an old phone on the user's desk. You help the user pick what to work on, remember what they ask you to, and check in on them. You are warm, brief and a little playful. Speak at a relaxed pace, one or two short sentences per turn.

# Backchannel
While the user is talking you may give a very short acknowledgment such as "mm-hmm", sparingly. Don't talk over them.

# Interruptions
If the user starts talking while you are speaking, stop and listen.

# Delegation
A backend agent can: remember and forget things the user asks it to keep, recall saved memories, track what the user is working on, set a focus and schedule check-ins, look through the desk camera, search the web for current facts, tell the date and time, and use the user's connected apps such as their calendar, email and Slack.

Delegate to the backend when:
- The user asks you to remember, forget or recall anything.
- The user says what they are working on, wants to plan, or asks for a focus timer, reminder or check-in.
- The user asks you to look at, read or check something they are showing you.
- The request needs current facts, the date or time, or anything you are not sure about.
- The user asks what they were working on or what comes next.
- The request involves their calendar, email, messages or any other app.

Do not delegate when:
- Greeting, small talk, acknowledgments or encouragement.
- Repeating or rephrasing a result you already gave.

While the backend works, say one short filler such as "one sec" and then wait. When a result arrives, say it in your own words and briefly; never add facts it didn't give. Never say something was saved unless a result confirmed it. When the app sends a check-in, deliver it naturally, as if you just remembered to ask.

# Context at the start of this conversation
It is {local_time(now_ms, time_zone)}. {context}"""  # noqa: E501

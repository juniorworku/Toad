"""The Today screen, built straight from the store (no model call, so it's instant)."""

import re
from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING, Any

from .prompt import local_time, start_of_day, when

Json = dict[str, Any]

if TYPE_CHECKING:
    from .store import Store


def esc(text: str) -> str:
    return escape(text, quote=True).replace("&#x27;", "'")


def iso(ms: int) -> str:
    """Like JavaScript's toISOString(): UTC with milliseconds and a Z."""
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{ms % 1000:03d}Z"
    )


def focus_today(store: "Store", time_zone: str, now_ms: int) -> tuple[int, list[Json]]:
    """Minutes focused since local midnight, and the sessions finished today (with outcomes)."""
    midnight = start_of_day(now_ms, time_zone)
    sessions = store.recent_focus(50)
    focus = store.focus()
    if focus:
        sessions.append(focus | {"endedAt": now_ms})
    total = 0
    finished: list[Json] = []
    for f in sessions:
        end = f.get("doneAt") or f.get("endedAt")
        if not end or end <= midnight:
            continue
        total += max(0, end - max(f["startedAt"], midnight))
        if f.get("doneAt"):
            minutes = round((f["doneAt"] - f["startedAt"]) / 60_000)
            finished.append(
                {"task": f["task"], "outcome": f.get("outcome") or "", "minutes": minutes}
            )
    return total // 60_000, finished


def duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if hours else f"{rest} min"


def render_today(store: "Store", time_zone: str, now_ms: int) -> str:
    """To-dos, focus with its check-in countdown, and saved memories, in the page kit's classes."""
    todos = store.todos()
    open_todos = [t for t in todos if not t["done"]]
    done = [t for t in todos if t["done"]][-5:]
    focus = store.focus()
    upcoming = next(
        (
            c
            for c in store.pending_checkins()
            if c["dueAt"] > now_ms and str(c["about"]).startswith("Focus check-in: ")
        ),
        None,
    )
    memories = store.memories()
    day = re.sub(r" at .*$", "", local_time(now_ms, time_zone))
    focused, finished = focus_today(store, time_zone, now_ms)
    reminders = [c for c in store.pending_checkins() if str(c["about"]).startswith("Reminder: ")]

    todo_items = (
        "".join(f"<li><b>{esc(t['text'])}</b></li>" for t in open_todos)
        if open_todos
        else '<li class="muted">Nothing on the list. Say "add … to my to-dos".</li>'
    )
    done_items = "".join(
        f'<li class="muted"><s>{esc(t["text"])}</s> <span class="badge ok">done</span></li>'
        for t in done
    )
    count = len(open_todos)
    focused_on = f" · focused on {esc(focus['task'])}" if focus else ""
    countdown = (
        f'<div class="countdown" data-to="{iso(upcoming["dueAt"])}">'
        '<span class="dk-label">Check-in in</span></div>'
        if upcoming
        else ""
    )
    focus_card = (
        f"""<div class="card accent">
  <div class="eyebrow">Working on</div>
  <h2>{esc(focus["task"])}</h2>
  {countdown}
</div>"""
        if focus
        else ""
    )
    reminder_items = "".join(
        f"<li><b>{esc(str(c['about']).removeprefix('Reminder: '))}</b>"
        f"<span>{esc(when(c['dueAt'], now_ms, time_zone))}"
        f"{' · ' + esc(c['repeat']) if c.get('repeat') else ''}</span></li>"
        for c in reminders[:5]
    )
    reminder_card = (
        f"""<div class="card">
  <h3>Reminders</h3>
  <ul class="list">{reminder_items}</ul>
</div>"""
        if reminders
        else ""
    )
    finished_items = "".join(
        f"<li><b>{esc(f['task'])}</b><span>{duration(f['minutes'])}"
        f"{' · ' + esc(f['outcome']) if f['outcome'] else ''}</span></li>"
        for f in finished[-5:]
    )
    progress_card = (
        f"""<div class="card">
  <h3>Focused today · {duration(focused)}</h3>
  {f'<ul class="list">{finished_items}</ul>' if finished_items else ""}
</div>"""
        if focused or finished
        else ""
    )
    memory_card = (
        f"""<div class="card">
  <h3>Remembering</h3>
  <ul class="list">{"".join(f"<li>{esc(m['text'])}</li>" for m in memories[-5:])}</ul>
</div>"""
        if memories
        else ""
    )
    return f"""<section class="hero">
  <div class="eyebrow">{esc(day)}</div>
  <h1>Today</h1>
  <p class="sub">{count} to-do{"" if count == 1 else "s"} open{focused_on}</p>
</section>
{focus_card}
<div class="card">
  <h3>To-dos</h3>
  <ul class="list">{todo_items}{done_items}</ul>
</div>
{reminder_card}
{progress_card}
{memory_card}"""

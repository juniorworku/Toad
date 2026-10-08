"""The Today screen, built straight from the store (no model call, so it's instant)."""

import re
from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING

from .prompt import local_time

if TYPE_CHECKING:
    from .store import Store


def esc(text: str) -> str:
    return escape(text, quote=True).replace("&#x27;", "'")


def iso(ms: int) -> str:
    """Like JavaScript's toISOString(): UTC with milliseconds and a Z."""
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{ms % 1000:03d}Z"
    )


def render_today(store: "Store", time_zone: str, now_ms: int) -> str:
    """To-dos, focus with its check-in countdown, and saved memories, in the page kit's classes."""
    todos = store.todos()
    open_todos = [t for t in todos if not t["done"]]
    done = [t for t in todos if t["done"]][-5:]
    focus = store.focus()
    upcoming = next((c for c in store.pending_checkins() if c["dueAt"] > now_ms), None)
    memories = store.memories()
    day = re.sub(r" at .*$", "", local_time(now_ms, time_zone))

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
    focused = f" · focused on {esc(focus['task'])}" if focus else ""
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
  <p class="sub">{count} to-do{"" if count == 1 else "s"} open{focused}</p>
</section>
{focus_card}
<div class="card">
  <h3>To-dos</h3>
  <ul class="list">{todo_items}{done_items}</ul>
</div>
{memory_card}"""

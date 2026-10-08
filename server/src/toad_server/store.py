"""Atomic single-writer state with baseline fields and millisecond timestamps."""

import asyncio
import copy
import json
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

Json = dict[str, Any]
T = TypeVar("T")
DONE_TODO_KEEP_MS = 7 * 86_400_000


def empty_state() -> Json:
    return {
        "memories": [],
        "focus": None,
        "focusHistory": [],
        "checkins": [],
        "todos": [],
        "todayPageId": None,
        # Local date (YYYY-MM-DD) of the last morning briefing, so it happens once a day.
        "briefedOn": None,
        "agent": dict.fromkeys(
            ("agentId", "definitionHash", "sessionId", "sessionHash", "appsSessionId")
        ),
    }


class Store:
    def __init__(self, data_dir: Path, clock: Callable[[], int] | None = None) -> None:
        self.file = data_dir / "toad.json"
        self.clock = clock or (lambda: int(time.time() * 1000))
        self._state = empty_state()
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []

    def on_change(self, listener: Callable[[], None]) -> None:
        """Called after every saved change (the desk pushes its snapshot to the phone)."""
        self._listeners.append(listener)

    async def load(self) -> None:
        def read() -> Json:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            incoming = self.file.with_name("toad.incoming.json")
            if incoming.exists():
                incoming.replace(self.file)
            try:
                saved = json.loads(self.file.read_text())
                state = empty_state()
                state.update(saved)
                state["agent"] = empty_state()["agent"] | saved.get("agent", {})
                return state
            except (OSError, ValueError, TypeError):
                return empty_state()

        self._state = await asyncio.to_thread(read)

    def snapshot(self) -> Json:
        return copy.deepcopy(self._state)

    def desk(self) -> Json:
        return {
            "type": "desk",
            "memories": self.memories(),
            "focus": self.focus(),
            "checkins": self.pending_checkins(),
        }

    async def _change(self, mutate: Callable[[Json], T]) -> T:
        async with self._lock:
            state = self.snapshot()
            result = mutate(state)
            payload = json.dumps(state, indent=2)

            def write() -> None:
                temporary = self.file.with_suffix(".json.tmp")
                with temporary.open("w") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(self.file)

            task = asyncio.create_task(asyncio.to_thread(write))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task  # finish the transaction before releasing its lock
                self._state = state
                self._changed()
                raise
            self._state = state
            self._changed()
            return copy.deepcopy(result)

    def _changed(self) -> None:
        for listener in self._listeners:
            listener()

    # Read helpers, newest state; all return copies.

    def memories(self) -> list[Json]:
        return copy.deepcopy(self._state["memories"])

    def focus(self) -> Json | None:
        focus: Json | None = copy.deepcopy(self._state["focus"])
        return focus

    def recent_focus(self, count: int = 5) -> list[Json]:
        return copy.deepcopy(self._state["focusHistory"][-count:]) if count > 0 else []

    def todos(self) -> list[Json]:
        return copy.deepcopy(self._state["todos"])

    def pending_checkins(self) -> list[Json]:
        return sorted(
            (copy.deepcopy(c) for c in self._state["checkins"] if not c.get("firedAt")),
            key=lambda c: c["dueAt"],
        )

    def agent_link(self) -> Json:
        return copy.deepcopy(self._state["agent"])

    def today_page_id(self) -> str | None:
        value = self._state["todayPageId"]
        return str(value) if value else None

    async def add_memory(self, text: str) -> Json:
        clean = text.strip()[:500]
        if not clean:
            raise ValueError("empty memory")

        def mutate(state: Json) -> Json:
            ids = [int(m["id"][1:]) for m in state["memories"] if m["id"][1:].isdigit()]
            memory = {"id": f"m{max(ids, default=0) + 1}", "text": clean, "createdAt": self.clock()}
            state["memories"].append(memory)
            return memory

        return await self._change(mutate)

    async def delete_memory(self, identifier: str) -> bool:
        def mutate(state: Json) -> bool:
            before = len(state["memories"])
            state["memories"] = [m for m in state["memories"] if m["id"] != identifier]
            return before != len(state["memories"])

        return await self._change(mutate)

    async def clear_memories(self) -> None:
        await self._change(lambda state: state.update(memories=[]))

    async def set_focus(self, task: str) -> Json:
        clean = task.strip()[:300]
        if not clean:
            raise ValueError("empty focus")

        def mutate(state: Json) -> Json:
            if state["focus"]:
                # Switched, not finished: keep when it ended so focus time can be added up.
                state["focusHistory"].append(state["focus"] | {"endedAt": self.clock()})
            state["focusHistory"] = state["focusHistory"][-50:]
            focus = {"task": clean, "startedAt": self.clock()}
            state["focus"] = focus
            return focus

        return await self._change(mutate)

    async def finish_focus(self, outcome: str) -> Json | None:
        def mutate(state: Json) -> Json | None:
            if not state["focus"]:
                return None
            done: Json = state["focus"] | {"doneAt": self.clock(), "outcome": outcome.strip()[:300]}
            state["focus"] = None
            state["focusHistory"] = (state["focusHistory"] + [done])[-50:]
            return done

        return await self._change(mutate)

    async def add_todo(self, text: str) -> Json:
        clean = text.strip()[:200]
        if not clean:
            raise ValueError("empty to-do")

        def mutate(state: Json) -> Json:
            self._prune_done(state)
            ids = [int(t["id"][1:]) for t in state["todos"] if t["id"][1:].isdigit()]
            todo = {
                "id": f"t{max(ids, default=0) + 1}",
                "text": clean,
                "done": False,
                "createdAt": self.clock(),
            }
            state["todos"].append(todo)
            return todo

        return await self._change(mutate)

    def _prune_done(self, state: Json) -> None:
        """Finished to-dos are kept a week (for "what did I get done?"), then dropped."""
        cutoff = self.clock() - DONE_TODO_KEEP_MS
        state["todos"] = [
            t for t in state["todos"] if not (t["done"] and t.get("doneAt", cutoff) < cutoff)
        ]

    def find_todo(self, id_or_words: str) -> Json | None:
        query = id_or_words.strip().lower()
        if not query:
            return None
        todos = self.snapshot()["todos"]
        predicates: list[Callable[[Json], bool]] = [
            lambda t: bool(t["id"] == query),
            lambda t: not t["done"] and query in t["text"].lower(),
            lambda t: query in t["text"].lower(),
        ]
        for predicate in predicates:
            for todo in todos:
                if predicate(todo):
                    return dict(todo)
        return None

    async def set_todo_done(self, identifier: str, done: bool) -> Json | None:
        def mutate(state: Json) -> Json | None:
            for todo in state["todos"]:
                if todo["id"] == identifier:
                    todo["done"] = done
                    if done:
                        todo["doneAt"] = self.clock()
                    else:
                        todo.pop("doneAt", None)
                    return dict(todo)
            return None

        return await self._change(mutate)

    async def remove_todo(self, identifier: str) -> bool:
        def mutate(state: Json) -> bool:
            before = len(state["todos"])
            state["todos"] = [t for t in state["todos"] if t["id"] != identifier]
            return before != len(state["todos"])

        return await self._change(mutate)

    async def add_checkin(self, due_at: int, about: str, repeat: str | None = None) -> Json:
        """A check-in or reminder; `repeat` ("daily" or "weekdays") reschedules it when it fires."""
        checkin: Json = {
            "id": "c" + secrets.token_hex(8),
            "dueAt": due_at,
            "about": about.strip()[:300],
            "createdAt": self.clock(),
        }
        if repeat:
            checkin["repeat"] = repeat
        await self._change(lambda state: state["checkins"].append(checkin))
        return dict(checkin)

    async def mark_checkin_fired(self, identifier: str) -> None:
        def mutate(state: Json) -> None:
            now = self.clock()
            for checkin in state["checkins"]:
                if checkin["id"] == identifier:
                    checkin["firedAt"] = now
            state["checkins"] = [
                c
                for c in state["checkins"]
                if not c.get("firedAt") or now - c["firedAt"] < 86400000
            ]

        await self._change(mutate)

    async def cancel_checkins(self, which: Callable[[Json], bool] | None = None) -> int:
        def mutate(state: Json) -> int:
            before = len(state["checkins"])
            state["checkins"] = [
                c
                for c in state["checkins"]
                if c.get("firedAt") or (which is not None and not which(c))
            ]
            return before - len(state["checkins"])

        return await self._change(mutate)

    async def set_agent_link(self, patch: Json) -> None:
        unknown = patch.keys() - empty_state()["agent"].keys()
        if unknown:
            raise ValueError(f"unknown agent fields: {unknown}")
        await self._change(lambda state: state["agent"].update(patch))

    def briefed_on(self) -> str | None:
        value = self._state.get("briefedOn")
        return str(value) if value else None

    async def set_briefed_on(self, day: str) -> None:
        await self._change(lambda state: state.update(briefedOn=day))

    async def set_today_page_id(self, identifier: str) -> None:
        await self._change(lambda state: state.update(todayPageId=identifier))

import asyncio
from pathlib import Path

import pytest

from toad_server.store import Store


@pytest.mark.asyncio
async def test_parallel_memory_writes_have_unique_ids_and_persist(tmp_path: Path) -> None:
    store = Store(tmp_path, clock=lambda: 123456)
    await store.load()
    saved = await asyncio.gather(*(store.add_memory(f"memory {i}") for i in range(20)))
    assert len({m["id"] for m in saved}) == 20
    reloaded = Store(tmp_path)
    await reloaded.load()
    assert len(reloaded.snapshot()["memories"]) == 20
    assert saved[0]["createdAt"] == 123456
    assert not (tmp_path / "toad.json.tmp").exists()


@pytest.mark.asyncio
async def test_memory_limits_empty_and_snapshot_isolation(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    with pytest.raises(ValueError):
        await store.add_memory("  ")
    saved = await store.add_memory("x" * 600)
    assert len(saved["text"]) == 500
    snapshot = store.snapshot()
    snapshot["memories"].clear()
    assert len(store.snapshot()["memories"]) == 1
    await store.clear_memories()
    await store.load()
    assert store.snapshot()["memories"] == []


@pytest.mark.asyncio
async def test_focus_task_lifecycle_and_history_limit(tmp_path: Path) -> None:
    store = Store(tmp_path, clock=lambda: 1000)
    await store.load()
    for i in range(55):
        await store.set_focus(f"Focus {i}")
    assert len(store.snapshot()["focusHistory"]) == 50
    done = await store.finish_focus("done")
    assert done == {"task": "Focus 54", "startedAt": 1000, "doneAt": 1000, "outcome": "done"}
    assert store.desk()["focus"] is None
    assert len(store.snapshot()["focusHistory"]) == 50


@pytest.mark.asyncio
async def test_tasks_prefer_open_match_and_can_be_reopened(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    first = await store.add_todo("Review demo")
    second = await store.add_todo("Record demo")
    await store.set_todo_done(first["id"], True)
    assert store.find_todo("demo") == second
    reopened = await store.set_todo_done(first["id"], False)
    assert reopened and "doneAt" not in reopened
    assert await store.remove_todo(second["id"])
    assert not await store.remove_todo(second["id"])


@pytest.mark.asyncio
async def test_checkins_sort_cancel_and_prune_old_fired(tmp_path: Path) -> None:
    now = [1000]
    store = Store(tmp_path, clock=lambda: now[0])
    await store.load()
    late = await store.add_checkin(3000, "late")
    early = await store.add_checkin(2000, "early")
    assert store.desk()["checkins"] == [early, late]
    await store.mark_checkin_fired(early["id"])
    assert await store.cancel_checkins(lambda c: c["about"] == "late") == 1
    now[0] += 86400001
    new = await store.add_checkin(now[0] + 1000, "new")
    await store.mark_checkin_fired(new["id"])
    assert [c["id"] for c in store.snapshot()["checkins"]] == [new["id"]]


@pytest.mark.asyncio
async def test_startup_adopts_incoming_state_and_keeps_remote_link(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await store.load()
    await store.set_agent_link({"agentId": "synthetic-agent", "sessionId": "synthetic-session"})
    await store.set_today_page_id("synthetic-page")
    store.file.rename(tmp_path / "toad.incoming.json")
    reloaded = Store(tmp_path)
    await reloaded.load()
    assert reloaded.snapshot()["agent"]["sessionId"] == "synthetic-session"
    assert reloaded.snapshot()["todayPageId"] == "synthetic-page"
    assert not (tmp_path / "toad.incoming.json").exists()

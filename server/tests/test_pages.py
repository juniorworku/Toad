"""Port of Desku's page tests (server/test/pages.test.ts)."""

import re
from pathlib import Path

import pytest

from toad_server.pages import PAGE_HEADERS, PAGE_ID, Pages, with_kit


async def test_save_read_update_in_place_and_survive_a_restart(tmp_path: Path) -> None:
    clock = [1000]
    pages = Pages(tmp_path, lambda: clock[0])
    await pages.load()
    page = await pages.save("Open tickets", "<h1>3 open</h1>")
    assert PAGE_ID.fullmatch(page["id"])
    assert await pages.html(page["id"]) == "<h1>3 open</h1>"
    clock[0] = 2000
    updated = await pages.save("Open tickets (2)", "<h1>2 open</h1>", page["id"])
    assert updated["id"] == page["id"]
    assert (updated["createdAt"], updated["updatedAt"]) == (1000, 2000)
    reopened = Pages(tmp_path)
    await reopened.load()
    assert [p["title"] for p in reopened.listing()] == ["Open tickets (2)"]
    assert await reopened.html(page["id"]) == "<h1>2 open</h1>"


async def test_rejects_empty_oversized_and_unknown_ids(tmp_path: Path) -> None:
    pages = Pages(tmp_path)
    await pages.load()
    with pytest.raises(ValueError, match="empty"):
        await pages.save("x", "   ")
    with pytest.raises(ValueError, match="over"):
        await pages.save("x", "a" * (600 * 1024))
    with pytest.raises(ValueError, match="no page"):
        await pages.save("x", "<p>hi</p>", "AAAAAAAAAAAAAAAAAAAAAA")
    assert await pages.html("../index") is None


async def test_keeps_the_newest_50_and_deletes(tmp_path: Path) -> None:
    clock = [0]

    def tick() -> int:
        clock[0] += 1
        return clock[0]

    pages = Pages(tmp_path, tick)
    await pages.load()
    first = await pages.save("p0", "<p>0</p>")
    for i in range(1, 51):
        await pages.save(f"p{i}", f"<p>{i}</p>")
    assert len(pages.listing()) == 50
    assert await pages.html(first["id"]) is None
    assert not (tmp_path / "pages" / f"{first['id']}.html").exists()
    newest = pages.listing()[0]
    assert newest["title"] == "p50"
    assert await pages.delete(newest["id"]) is True
    assert await pages.delete(newest["id"]) is False


def test_served_sandboxed_with_no_way_to_send_data_out() -> None:
    csp = PAGE_HEADERS["Content-Security-Policy"]
    assert "sandbox allow-scripts" in csp
    assert "allow-same-origin" not in csp
    assert "connect-src 'none'" in csp and "form-action 'none'" in csp


def test_the_ui_kit_is_added_to_every_page_as_it_is_served() -> None:
    full = with_kit(
        "<!doctype html><html><head><title>t</title><style>.mine{}</style></head>"
        "<body><p>x</p></body></html>"
    )
    # Kit styles come before the page's own styles, so the page can override them.
    assert full.index("data-toad-kit") < full.index(".mine{}")
    assert full.index("<script data-toad-kit>") < full.index("</body>")
    assert "fonts.googleapis.com/css2?family=DM+Mono" in full
    # A bare fragment still gets both, and exactly one doctype.
    bare = with_kit('<div class="card">hi</div>')
    assert bare.startswith('<!doctype html><meta name="viewport"')
    assert len(re.findall("<!doctype", full, re.I)) == 1
    assert re.search(r"<script data-toad-kit>[\s\S]*</script>$", bare)

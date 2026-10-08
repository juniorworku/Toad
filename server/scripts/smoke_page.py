"""Live check of pages: real Toad brain (+ your apps if COMPOSIO_API_KEY is set), asking for
something to put on the screen. Uses a throwaway store and pages folder and no phone, so it never
touches a running desk. Writes the page, with the UI kit, to <tmp>/page.html to open in a browser.

Makes paid OpenAI requests.
Usage (repo root): .venv/bin/python server/scripts/smoke_page.py ["request"]
"""

import asyncio
import sys
import time

from _common import make_desk, settings

from toad_server.pages import with_kit
from toad_server.tools import Tools


async def main() -> None:
    config = settings()
    with_apps = bool(config.composio_api_key.get_secret_value())
    desk, client = await make_desk(config, with_apps=with_apps)
    try:
        heard = (
            sys.argv[1]
            if len(sys.argv) > 1
            else "What's on my calendar for the rest of today? Put it on the screen."
        )
        started = time.monotonic()
        assert desk.brain
        answer = await desk.brain.ask(f"[Heard] {heard}", Tools(desk, heard, None))
        print(f"TOAD ({time.monotonic() - started:.0f}s): {answer}")
        if desk.shown:
            html = await desk.pages.html(desk.shown[-1]["id"])
            out = desk.settings.data_dir / "page.html"
            out.write_text(with_kit(html or ""))
            print(f"open {out}")
        else:
            print("No page was shown.")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

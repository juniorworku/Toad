"""Live check of apps: real Composio session + real Toad brain, asking about the calendar.

Prints any Connect Link the user has to open. Makes paid OpenAI requests and Composio calls
for COMPOSIO_USER_ID (reads only, unless you ask it to change something).
Usage (repo root): .venv/bin/python server/scripts/smoke_apps.py ["question"]
"""

import asyncio
import sys

from _common import make_desk, settings

from toad_server.tools import Tools


async def main() -> None:
    desk, client = await make_desk(settings(), with_apps=True, temp=False)
    try:
        heard = sys.argv[1] if len(sys.argv) > 1 else "What's on my calendar for the rest of today?"
        print(f"USER: {heard}")
        assert desk.brain
        answer = await desk.brain.ask(f"[Heard] {heard}", Tools(desk, heard, None))
        print(f"TOAD: {answer}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

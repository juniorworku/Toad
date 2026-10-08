"""Live check of the brain alone: real Agents API, real tools, the demo photo as the camera.

Makes paid OpenAI requests. Uses a throwaway data folder, never your real memories.
Usage (repo root): .venv/bin/python server/scripts/smoke_brain.py
"""

import asyncio
import json

from _common import DEMO_PHOTO, make_desk, settings

from toad_server.tools import Tools


async def main() -> None:
    desk, client = await make_desk(settings(), photo=DEMO_PHOTO)
    try:

        async def say(heard: str) -> None:
            print(f"\nUSER: {heard}")

            async def progress(text: str, pending: list[str]) -> None:
                print(f"  (progress before {pending}) {text}")

            assert desk.brain
            answer = await desk.brain.ask(f"[Heard] {heard}", Tools(desk, heard, None), progress)
            print(f"TOAD: {answer}")

        await say("Can you read my to-do list? I'm holding it up.")
        await say("Okay, I'll do the first one for 25 minutes. Check in on me after.")
        await say("The grant is due Friday, just so you know.")  # not a save request: not saved
        store = desk.store
        summary = {
            "memories": store.memories(),
            "focus": store.focus(),
            "checkins": store.pending_checkins(),
        }
        print("\nstore:", json.dumps(summary, indent=1))
        if store.memories():
            print("UNEXPECTED: a memory was saved without being asked")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

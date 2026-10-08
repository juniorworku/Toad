"""Connects one app for Toad's owner: prints a Connect Link, then waits until it's approved.
Uses the engine's saved Composio session (DATA_DIR) so the engine sees the connection.
Usage (repo root): .venv/bin/python server/scripts/connect_app.py googlecalendar
"""

import asyncio
import sys

from _common import need, settings

from toad_server.store import Store


async def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: connect_app.py <toolkit-slug>   (e.g. googlecalendar, gmail, slack)")
    toolkit = sys.argv[1]
    config = settings()
    need(config.composio_api_key.get_secret_value(), "COMPOSIO_API_KEY")
    from composio import Composio

    store = Store(config.data_dir)
    await store.load()
    composio = Composio(api_key=config.composio_api_key.get_secret_value())
    saved = store.agent_link()["appsSessionId"]
    if saved:
        session = await asyncio.to_thread(composio.sessions.use, saved)
    else:
        session = await asyncio.to_thread(
            lambda: composio.sessions.create(user_id=config.composio_user_id)
        )
        await store.set_agent_link({"appsSessionId": session.session_id})
    request = await asyncio.to_thread(session.authorize, toolkit)
    print(f"Open this link to connect {toolkit} for {config.composio_user_id}:\n")
    print(f"  {request.redirect_url}\n")
    print("Waiting for approval (up to 15 minutes)…")
    account = await asyncio.to_thread(request.wait_for_connection, 15 * 60)
    print(f"Connected: {toolkit} → {account.id} ({account.status})")


if __name__ == "__main__":
    asyncio.run(main())

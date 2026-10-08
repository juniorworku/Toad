"""Wraps a desk page with the Toad UI kit (exactly as /p/<id> serves it) for a browser preview.

Usage (repo root):
  .venv/bin/python .claude/skills/toad-pages/scripts/preview_page.py page.html [out.html]
  .venv/bin/python .claude/skills/toad-pages/scripts/preview_page.py --today [out.html]
--today renders the Today screen from DATA_DIR (from .env, default ./data) without changing it.
"""

import asyncio
import sys
import time
from pathlib import Path

from toad_server.config import Settings
from toad_server.pages import PAGE_HEADERS, with_kit
from toad_server.store import Store
from toad_server.today import render_today

ROOT = Path(__file__).resolve().parents[4]


async def today_html() -> str:
    config = Settings(_env_file=ROOT / ".env")  # type: ignore[call-arg]
    data = config.data_dir if config.data_dir.is_absolute() else ROOT / config.data_dir
    store = Store(data)
    if (data / "toad.json").exists():
        await store.load()
    return render_today(store, config.time_zone, int(time.time() * 1000))


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args[0] == "--today":
        html = asyncio.run(today_html())
        out = Path(args[1]) if len(args) > 1 else Path("today.preview.html")
    else:
        source = Path(args[0])
        html = source.read_text()
        out = Path(args[1]) if len(args) > 1 else source.with_suffix(".preview.html")
    if len(html.encode()) > 512 * 1024:
        print("Warning: over 512 KB; the engine would refuse this page.")
    out.write_text(with_kit(html))
    print(f"Wrote {out} ({out.stat().st_size} bytes). Open it in a browser at phone width.")
    print("On the desk it's served with this CSP:")
    print("  " + PAGE_HEADERS["Content-Security-Policy"].replace("; ", "\n  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())

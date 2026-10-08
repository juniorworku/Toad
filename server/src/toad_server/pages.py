"""Link-readable, sandboxed HTML pages and atomic metadata."""

import asyncio
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

PAGE_ID = re.compile(r"^[A-Za-z0-9_-]{22}$")
PAGE_HEADERS = {
    "Content-Security-Policy": "; ".join(
        [
            "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox",
            "default-src 'none'",
            "script-src 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
            "style-src 'unsafe-inline' https://fonts.googleapis.com",
            "font-src https://fonts.gstatic.com",
            "img-src data: blob:",
            "connect-src 'none'",
            "form-action 'none'",
            "base-uri 'none'",
        ]
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class Pages:
    def __init__(self, data_dir: Path) -> None:
        self.directory = data_dir / "pages"
        self.index = self.directory / "index.json"
        self.items: list[dict[str, Any]] = []
        self.lock = asyncio.Lock()

    async def load(self) -> None:
        def read() -> list[dict[str, Any]]:
            self.directory.mkdir(parents=True, exist_ok=True)
            try:
                items = json.loads(self.index.read_text())
                return [
                    p for p in items if isinstance(p, dict) and PAGE_ID.fullmatch(p.get("id", ""))
                ]
            except (OSError, ValueError, TypeError):
                return []

        self.items = await asyncio.to_thread(read)

    def listing(self) -> list[dict[str, Any]]:
        return [dict(p) for p in sorted(self.items, key=lambda p: p["updatedAt"], reverse=True)]

    async def html(self, identifier: str) -> str | None:
        if not PAGE_ID.fullmatch(identifier) or not any(p["id"] == identifier for p in self.items):
            return None
        try:
            return await asyncio.to_thread((self.directory / (identifier + ".html")).read_text)
        except OSError:
            return None

    @staticmethod
    def atomic(path: Path, text: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text)
        tmp.replace(path)

    async def save(self, title: str, html: str, identifier: str | None = None) -> dict[str, Any]:
        if not html.strip():
            raise ValueError("html is empty")
        if len(html.encode()) > 512 * 1024:
            raise ValueError("html is over 512 KB")
        async with self.lock:
            existing = next((p for p in self.items if p["id"] == identifier), None)
            if identifier and not existing:
                raise ValueError("no page with that id")
            now = int(time.time() * 1000)
            page: dict[str, Any] = (
                dict(existing) if existing else {"id": secrets.token_urlsafe(16), "createdAt": now}
            )
            page.update(title=title.strip()[:120] or "Toad page", updatedAt=now)
            items = sorted(
                [page] + [p for p in self.items if p["id"] != page["id"]],
                key=lambda p: p["updatedAt"],
                reverse=True,
            )

            def write() -> None:
                self.atomic(self.directory / (page["id"] + ".html"), html)
                self.atomic(self.index, json.dumps(items[:50], indent=2))
                for old in items[50:]:
                    (self.directory / (old["id"] + ".html")).unlink(missing_ok=True)

            task = asyncio.create_task(asyncio.to_thread(write))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                self.items = items[:50]
                raise
            self.items = items[:50]
            return dict(page)

    async def delete(self, identifier: str) -> bool:
        async with self.lock:
            if not any(p["id"] == identifier for p in self.items):
                return False
            items = [p for p in self.items if p["id"] != identifier]

            def write() -> None:
                self.atomic(self.index, json.dumps(items, indent=2))
                (self.directory / (identifier + ".html")).unlink(missing_ok=True)

            task = asyncio.create_task(asyncio.to_thread(write))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                self.items = items
                raise
            self.items = items
            return True


def with_kit(html: str) -> str:
    assets = Path(__file__).parent / "assets"
    head = '<meta name="viewport" content="width=device-width, initial-scale=1">'
    head += "<style data-toad-kit>" + (assets / "kit.css").read_text() + "</style>"
    match = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    output = html[: match.end()] + head + html[match.end() :] if match else head + html
    script = "<script data-toad-kit>" + (assets / "kit.js").read_text() + "</script>"
    end = re.search(r"</body>", output, re.IGNORECASE)
    output = output[: end.start()] + script + output[end.start() :] if end else output + script
    return (
        output if re.match(r"\s*<!doctype", output, re.IGNORECASE) else "<!doctype html>" + output
    )

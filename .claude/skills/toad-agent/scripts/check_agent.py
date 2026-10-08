"""Checks agent/toad-agent.json against the Python server, offline.

1. The definition is valid and every function tool has a strict object schema.
2. Every function tool is implemented: each one is called on a throwaway desk through the real
   `Tools` class and must not come back as "Unknown function".
3. The agent is named Toad and introduces itself as Toad.

Usage (repo root): .venv/bin/python .claude/skills/toad-agent/scripts/check_agent.py [definition.json]
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
DEFINITION = ROOT / "agent" / "toad-agent.json"


def schema_problems(tool: dict[str, Any]) -> list[str]:
    name = tool.get("name", "?")
    params = tool.get("parameters") or {}
    problems = []
    if not tool.get("description"):
        problems.append(f"{name}: missing description")
    if params.get("type") != "object":
        problems.append(f"{name}: parameters must be an object schema")
    if params.get("additionalProperties") is not False:
        problems.append(f"{name}: set additionalProperties to false")
    properties = set((params.get("properties") or {}).keys())
    required = set(params.get("required") or [])
    if properties != required:
        problems.append(f"{name}: required {sorted(required)} must list every property")
    return problems


async def unimplemented(names: list[str]) -> list[str]:
    from toad_server.config import Settings
    from toad_server.desk import Desk
    from toad_server.store import Store
    from toad_server.tools import Tools

    with tempfile.TemporaryDirectory(prefix="toad-agent-check-") as data:
        store = Store(Path(data))
        await store.load()
        desk = Desk(
            Settings(device_token="check", data_dir=Path(data), always_listen=False),
            store,
            log=lambda message: None,
        )
        await desk.pages.load()
        tools = Tools(desk, "", None)
        missing = []
        for name in names:
            result = await tools(name, {})
            if not result["ok"] and str(result["error"]).startswith("Unknown function"):
                missing.append(name)
        await desk.close()
        return missing


def main() -> int:
    path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFINITION
    definition = json.loads(path.read_text())
    tools = definition.get("tools", [])
    functions = [t for t in tools if t.get("type") == "function"]
    names = [t["name"] for t in functions]
    problems = [p for t in functions for p in schema_problems(t)]
    if len(set(names)) != len(names):
        problems.append("duplicate function tool names")
    if definition.get("name") != "Toad" or "You are Toad" not in definition.get("instructions", ""):
        problems.append("the agent should be named Toad and introduce itself as Toad")
    missing = asyncio.run(unimplemented(names))
    problems += [f"{name}: not implemented in server/src/toad_server/tools.py" for name in missing]
    hosted = [t["type"] for t in tools if t.get("type") != "function"]
    print(f"{path.name}: {len(names)} function tools, hosted: {hosted}")
    print("  " + ", ".join(names))
    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("OK: schemas are strict and every function tool is implemented by the server.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Reproducible local Python setup; --check reports prerequisites without changes."""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise SystemExit("Python 3.12 or newer is required.")
    executable = ROOT / ".venv/bin/python"
    if args.check:
        print("Python:", sys.version.split()[0])
        print(
            "Repository environment:", "present" if executable.exists() else "missing"
        )
        for command in ("java", "adb"):
            print(command + ":", shutil.which(command) or "missing")
        print("Private .env:", "present" if (ROOT / ".env").exists() else "missing")
        return
    if not executable.exists():
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "-r",
            str(ROOT / "server/requirements.lock"),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "-e",
            str(ROOT / "server"),
        ],
        check=True,
    )
    configuration = ROOT / ".env"
    try:
        with open(
            configuration, "x", opener=lambda path, flags: os.open(path, flags, 0o600)
        ) as handle:
            template = (ROOT / "server/.env.example").read_text()
            handle.write(
                template.replace(
                    "DEVICE_TOKEN=\n",
                    "DEVICE_TOKEN=" + secrets.token_urlsafe(32) + "\n",
                )
            )
        print(
            "Created private .env with a new device token. Existing files are preserved."
        )
    except FileExistsError:
        print("Preserved existing .env.")
    print(
        "Start from repository root: .venv/bin/python -m uvicorn toad_server.main:app --port 8787 --no-access-log"
    )


if __name__ == "__main__":
    main()

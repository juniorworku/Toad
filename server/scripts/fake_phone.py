"""End-to-end check without a phone: acts as the desk device against a running engine.

Speaks lines into the live session (macOS `say`, or `espeak-ng`/`espeak` on Linux, or your own
WAV recordings with --wav), keeps sending silence like an open mic would, answers camera requests
with demo/handwritten-todo.jpg, prints both transcripts and saves Toad's audio as a WAV.

With PROVIDER_MODE=openai this makes paid GPT-Live and Agents API requests.
Usage (repo root, engine running):
  .venv/bin/python server/scripts/fake_phone.py "first line" "second line" ...
  .venv/bin/python server/scripts/fake_phone.py --wav question.wav
Env: PORT (8787), WAIT_MS (25000 ms of open mic after each line), OUT_WAV (where to save).
"""

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import wave
from array import array
from pathlib import Path

from _common import DEMO_PHOTO, settings
from websockets.asyncio.client import ClientConnection, connect

RATE = 24_000
CHUNK = 2400 * 2  # 100 ms of 24 kHz PCM16


def resample(path: Path) -> bytes:
    """Any 16-bit WAV → mono 24 kHz PCM16 (linear interpolation, no extra dependencies)."""
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise SystemExit(f"{path}: only 16-bit WAV files are supported")
        channels, rate = wav.getnchannels(), wav.getframerate()
        samples = array("h", wav.readframes(wav.getnframes()))
    if channels > 1:
        samples = array(
            "h",
            (sum(samples[i : i + channels]) // channels for i in range(0, len(samples), channels)),
        )
    if rate == RATE or not samples:
        return samples.tobytes()
    out = array("h")
    step = rate / RATE
    for n in range(int(len(samples) / step)):
        x = n * step
        i = int(x)
        nxt = samples[i + 1] if i + 1 < len(samples) else samples[i]
        out.append(int(samples[i] + (nxt - samples[i]) * (x - i)))
    return out.tobytes()


def tts(text: str, work: Path, index: int) -> bytes:
    wav = work / f"{index}.wav"
    if shutil.which("say") and shutil.which("afconvert"):
        aiff = work / f"{index}.aiff"
        subprocess.run(["say", "-o", str(aiff), text], check=True)
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16@24000", "-c", "1", str(aiff), str(wav)],
            check=True,
        )
    elif engine := shutil.which("espeak-ng") or shutil.which("espeak"):
        subprocess.run([engine, "-w", str(wav), text], check=True)
    else:
        raise SystemExit(
            "No text-to-speech found. Install espeak-ng (sudo apt install espeak-ng), "
            "or record the lines yourself and pass them with --wav."
        )
    return resample(wav)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("lines", nargs="*", help="sentences to speak, in order")
    parser.add_argument("--wav", action="append", default=[], help="16-bit WAV file to play")
    args = parser.parse_args()
    lines: list[str] = args.lines
    if not lines and not args.wav:
        lines = ["Hey Toad, can you read my to-do list? I'm holding it up to the camera."]
    config = settings()
    port = os.environ.get("PORT", str(config.port))
    wait_ms = int(os.environ.get("WAIT_MS", "25000"))
    work = Path(tempfile.mkdtemp(prefix="toad-phone-"))
    clips = [tts(text, work, i) for i, text in enumerate(lines)]
    clips += [resample(Path(p)) for p in args.wav]
    photo = base64.b64encode(DEMO_PHOTO.read_bytes()).decode()
    received: list[bytes] = []
    state = {"line": "", "role": ""}
    uri = f"ws://localhost:{port}/device?token={config.device_token}"

    async def listen(ws: ClientConnection) -> None:
        async for frame in ws:
            if isinstance(frame, bytes):
                received.append(frame)
                continue
            message = json.loads(frame)
            kind = message.get("type")
            if kind == "transcript":
                if message["role"] != state["role"]:
                    who = "USER" if message["role"] == "user" else "TOAD"
                    print(f"\n{who}: ", end="")
                    state["role"] = message["role"]
                print(message["delta"], end="", flush=True)
            elif kind == "capture":
                print(f"\n[phone] camera ({message['countdownSeconds']}s) → sending demo photo")
                await asyncio.sleep(message["countdownSeconds"])
                await ws.send(
                    json.dumps({"type": "photo", "requestId": message["requestId"], "image": photo})
                )
            elif kind == "state":
                line = message["live"] + (" thinking" if message["thinking"] else "")
                if line != state["line"]:
                    print(f"\n[state] {line}")
                    state["line"] = line
            elif kind != "desk":
                print(f"\n[{kind}] {json.dumps(message)}")

    async with connect(uri, max_size=8 * 1024 * 1024, proxy=None) as ws:
        listener = asyncio.create_task(listen(ws))

        async def stream(pcm: bytes, seconds: float) -> None:
            # Real time, like a mic. Silence when pcm runs out.
            end = time.monotonic() + seconds
            offset = 0
            while time.monotonic() < end:
                chunk = pcm[offset : offset + CHUNK] if offset < len(pcm) else bytes(CHUNK)
                offset += CHUNK
                if len(chunk) % 2:
                    chunk = chunk[:-1]
                await ws.send(chunk)
                await asyncio.sleep(0.1)

        await ws.send(json.dumps({"type": "start"}))
        for _ in range(300):
            if state["line"].startswith("open"):
                break
            await asyncio.sleep(0.1)
        else:
            raise SystemExit("\nThe voice session never opened; check the engine log.")
        await stream(b"", 1.5)
        for pcm in clips:
            await stream(pcm, len(pcm) / (RATE * 2) + wait_ms / 1000)
        await ws.send(json.dumps({"type": "stop"}))
        await asyncio.sleep(2)
        listener.cancel()
    audio = b"".join(received)
    out = Path(os.environ.get("OUT_WAV", work / "toad-reply.wav"))
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(audio)
    print(f"\n\nToad audio: {len(audio) / (RATE * 2):.1f}s → {out}")


if __name__ == "__main__":
    asyncio.run(main())

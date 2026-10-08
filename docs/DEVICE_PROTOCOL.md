# Device protocol

The WebSocket contract between the phone (`android/…/engine/EngineLink.kt`) and the engine (`server/src/toad_server/desk.py`). Any change here must change both sides; `server/tests/test_protocol.py` checks the engine against the Kotlin source. Synthetic examples of every message are in [protocol/device-fixtures.json](protocol/device-fixtures.json).

## Connection

`ws(s)://HOST:8787/device?token=<DEVICE_TOKEN>`, native WebSocket (not Socket.IO).

- The token is compared in constant time. A wrong token gets HTTP 401 on the upgrade (close 1008 on servers without denial responses).
- One phone at a time: a newer authenticated connection closes the older one with code 4000.
- On connect the engine sends `state` and `desk`, then (in `PROVIDER_MODE=fake`) an `error` saying the AI isn't connected. With `ALWAYS_LISTEN=1` it opens a voice session at once.
- If the phone stops reading and 128 frames are queued, the engine closes it with 1013.
- The engine's log redacts the token from the socket path.

## Audio

Binary frames in both directions: raw mono PCM16 little-endian at 24 kHz, no header, nominally 100 ms (4,800 bytes). Odd-length frames are rejected with an `error`. Mic audio is dropped while muted, before the voice session has started, and when no session is open. When a session stops, audio queued for the old session is discarded and `interrupt` tells the phone to flush its playback.

## Phone → engine (JSON)

| Type | Fields | Meaning |
| --- | --- | --- |
| `start` / `stop` | | Open the voice session (Talk, wake phrase) / end it. Stop also pauses always-listening until the next start. |
| `mute` / `unmute` | | Mic privacy; the engine drops audio and tells GPT-Live |
| `camera` | `enabled`: boolean | Camera privacy switch; when off the camera tool fails honestly |
| `photo` | `requestId`, `image` (base64 JPEG) | Reply to `capture` |
| `photo_error` | `requestId`, `reason` | The phone couldn't take the photo |
| `forget` | `id` | Delete one memory |
| `forget_all` | | Delete every memory |
| `say` | `text` | A tap on a screen button; the brain answers it out loud as `[Tapped on the desk screen] text` |
| `presence` | `present`: boolean | On-device face detection sees (or stops seeing) someone |

Booleans must be JSON booleans (the Android app sends booleans). Malformed JSON or an unknown type gets an `error`.

## Engine → phone (JSON)

| Type | Fields | Meaning |
| --- | --- | --- |
| `state` | `live` (`idle`/`connecting`/`open`), `muted`, `camera`, `thinking` | Sent on every change |
| `transcript` | `role` (`user`/`assistant`), `delta` | Live captions for both sides |
| `desk` | `memories[{id,text,createdAt}]`, `focus{task,startedAt}` or null, `checkins[{id,dueAt,about,createdAt}]` | On connect and after every stored change; times are epoch milliseconds |
| `capture` | `requestId`, `countdownSeconds` (0) | Take one photo now (the camera is always on); 20 s timeout |
| `checkin` | `about` | A check-in is starting: wake the screen. An `about` starting with `Reminder: ` is a reminder; the phone shows it as a notice instead of the focus check-in screen |
| `page` | `id`, `title`, `url` | Open the relative `url` (`/p/<id>?v=<updatedAt>`; the version makes the phone reload an updated page) |
| `link` | `url`, `label` | An app Connect Link for the user to open |
| `calling` | `about` | Toad is phoning the user, or someone for them |
| `control` | `action` | `camera_on`, `camera_off`, `close_camera`, `mute_mic`, `show_memories`, `hide_memories`, `end_conversation` |
| `interrupt` | | Drop queued speech (barge-in within 3 s of Toad's audio, at most once a second; or the session stopped) |
| `error` | `message` | Shown to the user (`voice: …`, `brain: …`, `phone call: …`) |

## Fake provider

`PROVIDER_MODE=fake` counts incoming audio without recognizing it. A `say` gets a labeled transcript `[Fake provider] Received: <text>` and a 300 ms test tone in three binary frames. No model, paid service or real reply is involved.

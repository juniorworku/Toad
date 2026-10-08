# Device protocol: implemented subset

Baseline: Desku `2aea122`, `EngineLink.kt` and `Desk.ts`. Kotlin and Python use native WebSockets, not Socket.IO.

Connect to `/device?token=<DEVICE_TOKEN>`. Invalid tokens receive HTTP 401 when the ASGI server supports denial responses (otherwise close 1008). One device is active; a newer authenticated connection closes the older one. Token is compared in constant time. Keep the configured key out of logs.

Binary frames are raw mono PCM16 little-endian at 24 kHz. Nominal 100 ms frames contain 4,800 bytes. There is no WAV header. The engine accepts variable even-length frames. It rejects odd lengths. Microphone audio is dropped when muted, stopped or not yet open.

Implemented device JSON:

| Type | Fields |
| --- | --- |
| `start`, `stop`, `mute`, `unmute`, `forget_all` | none |
| `camera` | `enabled`: boolean |
| `presence` | `present`: boolean |
| `say` | `text`: string |
| `forget` | `id`: string |
| `photo` | `requestId`, `image` (base64 JPEG) |
| `photo_error` | `requestId`, `reason` |

Implemented outbound JSON: `state`, `desk`, `transcript`, `capture`, `interrupt`, `error`. `state` contains `live` (`idle`/`connecting`/`open`), `muted`, `camera`, `thinking`. `desk` contains `memories`, `focus`, `checkins`, matching Kotlin's existing parser. Stored memory fields remain `id`, `text`, `createdAt` (epoch milliseconds).

Strict boolean validation is an intentional protocol boundary improvement over JavaScript coercion; valid Android messages are unchanged. Unknown/malformed messages produce `error`. Stop invalidates queued session audio and emits `interrupt` to flush Android playback. Only the current session generation can emit PCM.

`PROVIDER_MODE=fake` is currently the only supported mode. It counts incoming audio bytes without recognizing speech. `say` returns a labeled diagnostic transcript and a quiet 300 ms tone in three binary frames. No model, paid service, tool execution or actual spoken reply is implied. Camera requests are callable through the coordinator and tested; the diagnostic provider does not invoke camera tools automatically.

Pending: `checkin`, `link`, `calling`, `control`, `page`, hosted-brain delegation, voice reconnection/idle scheduling and all provider adapters. Presence is tracked but does not yet trigger greetings/check-ins. Focus/check-in persistence is implemented; scheduler and model tool wiring remain pending.

# Toad: Python server and Kotlin Android rebuild plan

## Objective and scope

Build Toad as an independent AI desk companion with Desku's workflows, screen structure, hardware behavior and two operating modes. Keep native Kotlin/Jetpack Compose on Android. Replace the TypeScript/Node server with Python. Change the product name and character: Toad is a moss-green toad with raised eyes, a pale belly, broad feet, subtle spots and teal accents. Keep the dark Nightlight interface outside the character.

Repository destination: `~/Documents/codes/Personal_Projects/Toad`. Android identity: `com.toad.companion`; Gradle project: `Toad`; Python package: `toad_server`. These are local project identifiers, not a claim to a registered brand, domain or store listing. Wake phrase becomes “Hey Toad”; recognizer variants must be measured with real speech rather than obtained by replacing strings.

Baseline: Desku commit `2aea122`, source review dated October 8, 2026. See [BASELINE_REVIEW.md](BASELINE_REVIEW.md) for the source behavior. Identical means equivalent features, protocol, timing rules and interactions, with the requested language and branding changes. Model output need not match word for word. Do not import existing credentials, owner phone, project/account IDs, saved agent sessions, app connections or private state.

The initial deliverable is this implementation plan, a fresh Git repository, a Python environment, a minimal health endpoint and an avatar reference. Android runtime and provider integrations remain implementation milestones; directory creation does not complete them.

## Architecture and environment

| Area | Decision |
| --- | --- |
| Android | Preserve Kotlin, Compose, StateFlow/coroutines, CameraX, AudioRecord/AudioTrack, Vosk, OkHttp, TTS, local Anthropic brain and kiosk APIs. Retain source build versions initially to avoid an unrelated upgrade. |
| Python | Python 3.12 baseline, repository `.venv`, `pyproject.toml`, pip editable installation and an exact tested dependency lock after resolution. Never transplant a virtual environment from a temporary folder. |
| HTTP/device socket | FastAPI on Uvicorn, native WebSocket text and binary frames. No Socket.IO conversion. |
| Concurrency | `asyncio`, one desk coordinator, serialized brain turns, one outbound device writer, cancellation-aware provider tasks, bounded audio queues and explicit shutdown. |
| Models/configuration | Pydantic discriminated message models, environment settings, timezone-aware datetime at boundaries and epoch milliseconds on the wire. |
| Provider transports | Adapter interfaces around brain, voice, connected apps and calls; use supported Python SDKs or async HTTP/WebSocket transports after checking the exact source APIs. |
| Persistence | Preserve atomic file-backed JSON plus HTML/index storage for parity. One engine writer and one active phone. SQLite is a separate future decision. |
| Browser interfaces | Keep plain HTML/CSS/JavaScript and page kit; rebrand and serve through Python. Browser JavaScript is allowed; no Node/TypeScript backend or build pipeline. |
| Testing | pytest, pytest-asyncio, HTTP/WebSocket integration fixtures, provider fakes and existing Android JVM scenarios. Ruff for lint; mypy for server types. |
| Deployment | Python container, one Uvicorn worker, persistent data volume, graceful termination. Keep Fly as the reference hosting option with independent app/volume names. |

FastAPI supports [WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) and [lifespan-managed startup/shutdown](https://fastapi.tiangolo.com/advanced/events/). Uvicorn exposes [worker and lifespan settings](https://www.uvicorn.org/settings/). Python provides [structured async task groups](https://docs.python.org/3.12/library/asyncio-task.html#task-groups) and [virtual environments](https://docs.python.org/3.12/library/venv.html). Use these capabilities to manage the device, providers and scheduler without leaking background tasks. One worker is a project constraint because the engine owns in-process device and scheduler state.

Provider/model strings in Desku are source configuration, not verified current API availability. Do not substitute the generally available Realtime API or local Agents SDK for the source's voice/saved-agent endpoints and label that identical. If those endpoints are inaccessible, record the blocker and propose a documented alternative before changing the behavior. Paid calls, connections and deployment require a separate explicitly requested live-validation step.

## Repository layout

```text
Toad/
  README.md, LICENSE, .gitignore, .python-version
  android/                     # Kotlin Gradle project, created in milestone 2
  server/
    pyproject.toml, .env.example
    src/toad_server/
      main.py, config.py
      api/                     # HTTP, authentication, device upgrade
      protocol/                # typed device messages and fixtures
      engine/                  # desk, tools, Today, scheduler
      brain/                   # saved-agent adapter and memory policy
      live/                    # voice transport, transcript buffer
      store/                   # atomic JSON state
      pages/                   # page persistence and kit
      apps/                    # Composio adapter
      phone/                   # AgentPhone adapter
    public/                    # browser device and dashboard
    tests/                     # migrated behavior tests
  agent/                       # rebranded definition and terminal client
  design/avatar/               # toad reference and expression specification
  docs/                        # plan, protocol, parity checklist, decisions
  scripts/                     # Python/Bash operating tools
  .venv/                       # local and ignored
```

Subpackage directories are assigned responsibilities, not completed implementations. Implement modules when their milestone starts. Use module factories and dependency injection so server tests never require paid services.

## Source-to-Python migration map

| Desku implementation | Toad target | Preserve |
| --- | --- | --- |
| `server/src/index.ts` | `main.py`, `api/http.py`, `api/device.py` | routes, auth, cached overview, lifecycle, shutdown |
| `config.ts` | `config.py` | explicit continuous-listening default, optional integrations, timezone/quiet hours |
| `engine/Desk.ts` | `engine/desk.py`, `engine/scheduler.py` | one device, voice orchestration, delegation, presence, photos, check-ins |
| `engine/tools.ts` | `engine/tools.py` | all 12 tools, validation, memory/call gates, tool result shapes |
| `engine/today.ts` | `engine/today.py` | escaped deterministic HTML, stable page ID, countdown |
| `brain/AgentBrain.ts` | `brain/agent_brain.py` | remote saved-agent/session model, hash sync, serialized stream handling, recovery/idempotency |
| `brain/MemoryPolicy.ts` | `brain/memory_policy.py` | affirmative-to-offer and explicit latest-turn memory requests |
| `live/LiveClient.ts` | `live/client.py` | provider wire events, queued setup, PCM/base64 bridge, mute, commentary |
| `live/Transcript.ts`, `prompt.ts` | `live/transcript.py`, `live/prompt.py` | fragment merging, recent context, delegation/persona rules |
| `store/Store.ts` | `store/store.py`, `store/models.py` | IDs, millisecond timestamps, focus/history, todos, check-ins, atomic write |
| `pages/Pages.ts`, `kit.*` | `pages/pages.py`, unchanged/rebranded kit assets | random IDs, retention, size limit, sandbox/CSP, UI kit |
| `apps/Apps.ts` | `apps/client.py` | stable new owner ID, session reuse, tool filtering, schemas, auth URLs |
| `phone/AgentPhone.ts` | `phone/client.py` | E.164 validation, caller lookup, polling, timeout and transcript |
| `server/scripts/*.ts` | `scripts/*.py` | fake phone, provider smoke tools, app connect and USB/cloud bridge |
| `agent/desku.sh` | `agent/toad.sh` | separate CLI behavior and state; do not treat it as the main engine |

## Compatibility contract

Freeze the protocol before changing Android networking. Port field names and optional-value behavior from source into JSON fixtures. Preserve unknown/invalid-message error behavior deliberately. Never globally convert camelCase wire keys into Python snake_case.

| Contract | Requirement |
| --- | --- |
| Device connection | `/device?token=...`, shared-token validation with constant-time comparison; replacement connection closes previous device. Test rejection during WebSocket upgrade against OkHttp behavior. |
| Audio | Raw binary PCM16 little-endian, mono, 24 kHz, roughly 100 ms/4,800-byte frames. Both directions use binary; do not encode device audio as JSON. Provider-only base64 remains inside its adapter. |
| Device messages | `start`, `stop`, `mute`, `unmute`, `camera(enabled)`, `photo(requestId,image)`, `photo_error(requestId,reason)`, `forget(id)`, `forget_all`, `say(text)`, `presence(present)`. |
| Server messages | `state(live,muted,camera,thinking)`, `transcript(role,delta)`, `desk`, `capture(requestId,countdownSeconds)`, `checkin(about)`, `link(url,label)`, `calling(about)`, `error(message)`, `control(action)`, `page(id,title,url)`, `interrupt`. Extract the full `desk` structure from source. |
| HTTP | `/`, `/healthz`, `/agent`, `/agent.html`, bearer-protected `GET /api/overview`, `POST /api/apps/connect`, `DELETE /api/pages/<id>` and link-readable `GET /p/<id>`. |
| Page links | Send relative `/p/...` URLs because Kotlin adds the engine origin. Match CSP, content types, cache behavior and main-navigation restrictions. |
| Timing | Five-second scheduler; 400 ms delegation settle; 20-second camera timeout; 150-second brain turn timeout; at least ten-second live reconnect interval; 120-second demand-session idle close. |
| Interrupt | User transcript within three seconds of outgoing audio triggers `interrupt`, throttled to once per second. Android flushes pending audio and envelope state. |
| Storage | Match source fields, stable IDs, millisecond timestamps, focus history limit 50, page retention 50, HTML cap 512 KB, memory text cap 500 characters. Use synthetic fixture data. |

Keep all 12 server function tools and hosted web search. Preserve six local Claude tools. Keep engine and local memory stores separate. Read model tool schemas from source, including nullable/optional fields; Python SDK serialization must not silently omit required nulls or alter schemas.

## Implementation milestones

### 0 — Foundation and frozen baseline

- Create new Git repository, ignore secrets/builds/data, preserve original MIT notice and record attribution.
- Add this plan, baseline review, brand specification, toad SVG reference, Python package skeleton and minimal `/healthz` endpoint.
- Create `.venv` in its final destination. Install development dependencies and generate a tested lock when implementation begins; no unverified version pins or provider-specific SDK added now.
- Capture synthetic device JSON, tool schemas and state/page fixtures from source. Create a parity checklist with links to relevant modules.

Exit: independent repo exists, Python environment works, scaffolding compiles, and the remaining milestones are visibly incomplete.

### 1 — Python/device vertical slice and provider feasibility

- Implement auth, socket replacement, state snapshots, `say`, start/stop, camera/mute preferences and binary transport with fake voice/brain.
- Introduce adapters and ordered send/receive tasks. Avoid blocking provider requests, disk writes and synchronous SDK calls on the audio loop. Bound queues and invalidate frames from old device/session generations.
- Verify source's exact voice endpoint and saved-agent API with official provider references and the account's actual access. Prototype audio upload/download, transcript events, delegate event, agent tool execution and spoken reply.
- Run Kotlin phone against Python via `adb reverse tcp:8787 tcp:8787`; then test LAN. Explicitly select fake or real providers. Fake mode must not imply a functioning AI conversation.

Exit: one full voice turn, one tool turn and barge-in work; mute/stop/disconnect cancel the correct tasks; reconnect cannot play stale audio. This is the go/no-go point for provider parity.

### 2 — Kotlin app baseline and new identity

- Create Android Gradle project under `android/`; migrate the audited Kotlin modules, resources, fonts and JVM tests without upgrading dependencies at the same time.
- Rename package/imports/manifest components, app label, project name, prompts, test namespaces, broadcast actions, logs and debug property prefixes. Preserve wire protocol keys.
- Keep phone-only Claude, local speech/TTS, memories and timer, plus server-connected behavior. Python replaces only the backend.
- Replace `Desku.kt` character drawing with `Toad.kt`/`ToadFace`; keep expression dispatch and size contracts. Define dozing, listening, thinking, talking, muted and peeking states, eye tracking, blink, breathing and mouth/audio animation.
- Update launcher foreground, wake phrase/phonetic variants and character preview. Video fallback remains optional; no original human-face footage is bundled.

Exit: independently installable debug APK, both mode switches work, original app can coexist, identity is consistent, and Kotlin tests pass after toolchain setup.

### 3 — Persistent state, tools and brain

- Port file store and policies; atomic writes under a lock; snapshot state before offloading writes so readers cannot observe partial mutation. Use `asyncio.to_thread` where disk work would block audio.
- Port all server tool schemas/dispatch and synthetic tests, including images, structured tool results, consent rejections and error paths.
- Preserve saved-agent synchronization hashes, remote session persistence, serialized turn queue, idempotent tool submissions, streamed events, 150-second timeout and one unusable-session recovery.
- Keep provider/project IDs empty until independently configured; persona identifies Toad.

Exit: memories, focus, todos and remote session references survive restart; tool failures do not duplicate writes; cancellation semantics are tested; no live provider required for the behavior suite.

### 4 — Pages, Today and browser interfaces

- Port page persistence, stable Today page updates, retention and kit injection. Preserve CSP and WebView restrictions rather than defaulting to unrestricted static HTML.
- Move/rebrand dashboard and browser client. Keep authorization and delete operations, overview cache and pending-connection refresh semantics.
- Preserve native overlays, caption strip and origin-relative page messages.

Exit: add/complete/remove tasks refresh the same Today page; generated page create/update/delete survives restart; HTML escaping, CSP and limits pass tests; Android opens the pages correctly.

### 5 — Presence, focus and check-ins

- Preserve camera analysis/snapshot on Kotlin; Python receives only presence transitions and requested photos.
- Port scheduler, focus changes, offline startup grace, two-minute absence threshold, unanswered check-in wait, quiet hours and welcome-back guards.
- Fake-clock tests cover timezone, midnight, DST, reconnect and multiple due events. Do not use long real sleeps in tests.
- Track original focus cancel/finish and welcome-back contradictions as explicit decisions below.

Exit: on-desk check-in, offline/absent path, Today arrival, mute and restart behavior match documented decisions. No calls occur in fake-provider mode.

### 6 — Optional apps and calls

- Verify equivalent Composio Python SDK/meta-tool behavior or supported HTTP route; preserve filtering, output truncation, authorization URLs and a new `toad-owner` identity. Python availability alone does not prove the same tools/session semantics.
- Port AgentPhone async HTTP/polling, new caller configuration, exact transcript mapping, 20-minute timeout and single-call guard.
- Test disabled/unconfigured integrations, partial failures, canceled operations and link extraction with fakes.

Exit: optional integrations cannot break core voice; independent account setup is documented; any live account-write/call checks are separately authorized and recorded.

### 7 — Kiosk, operations and deployment

- Preserve device-owner policies, PIN administration, Wi-Fi setup, brightness, permissions and lifecycle. Use an independent PIN configuration and device-owner component name.
- Replace TS scripts with Python/Bash equivalents; support this Linux host instead of depending on `afconvert`/`caffeinate`.
- Add Python Docker image, one-worker entrypoint, data volume and health checks. Keep no original app/volume/project identifiers.
- Add orderly shutdown: stop scheduling, close device/live sockets, cancel/drain tasks and persist state. Document backup and ownership transfer.

Exit: reproducible local/container startup, safe shutdown, no duplicate schedulers, restart recovery, kiosk entry/recovery and independent deployment configuration. Actual publishing is a later requested action.

### 8 — Parity acceptance and release readiness

- Port the assertions from all 42 server test declarations; retain the 13 Android scenarios. Count is a baseline, not a substitute for equivalent behavior coverage.
- Measure real-device audio delay, echo, interruption and wake phrase in a room; test offline/reconnect and foreground/background behavior.
- Compare screens against source and reference captures: same layout, modes and actions with Toad's character. Capture new screenshots only during the requested visual-validation work.
- Verify honest privacy switches and memory deletion scope, missing credentials, inaccessible provider APIs and clear error states.
- Build debug and release; signing/install/distribution decisions are separate. Record the exact tested dependencies/toolchains and remaining known gaps.

Exit: parity matrix is complete or each exception is explicitly accepted; real-provider/device checks are distinguished from fake/syntax checks.

## Behavior decisions and known gaps

Default policy: preserve source behavior until a deviation is recorded in `docs/DECISIONS.md`. Avoid silently treating existing bugs as new product requirements.

| Topic | Baseline | Planned handling |
| --- | --- | --- |
| Continuous listening | Defaults on while engine connected | Preserve; document `ALWAYS_LISTEN=1` explicitly. Stop pauses until Talk; mute releases Android mic. |
| Focus stop/completion | No explicit engine tools | Port baseline first; propose explicit cancel/finish tools before changing schemas. |
| New conversation | Clears local Brain/UI only | Preserve initially and label correctly; remote reset is a separate recorded improvement. |
| Welcome back | Requires no live session, conflicts with always listening | Preserve/test guard; decide correction after vertical slice. |
| Consent | Code gates for memory, weaker prompt/gate coverage for apps/calls | Preserve explicit memory gate; record any stronger action confirmation as a behavior change. No hidden automatic live writes in tests. |
| Local automatic events | May inherit prior consent wording | Record and fix with a latest-user-turn token only if approved as a parity exception. |
| Check-in delivery | Marked fired before success | Test baseline; durable retry/status model is a recorded improvement, not an unnoticed storage rewrite. |
| Privacy labels | Describe local behavior even in engine mode | Rewrite labels to describe actual selected mode; no change to functionality required. |
| Corrupt storage | Resets to empty | Capture behavior; quarantine/recovery is a documented reliability improvement. |
| Browser microphone | Capture remains active while muted | Native parity remains primary; browser mic release/interruption improvements tracked separately. |

## Acceptance matrix

| Scenario | Fake/automated proof | Device/live proof |
| --- | --- | --- |
| Talk, reply, interrupt | PCM fixtures, transcript ordering, cancellation and stale-frame checks | Speech heard clearly; user can interrupt without delayed playback |
| Local mode | JVM SDK/history/memory scenarios | SpeechRecognizer/TTS, timer, no engine dependency |
| Camera and presence | Request IDs, unavailable/timeouts, presence timing | lens switch, orientation, face follow, camera-off respected |
| Memories | explicit request/offer, rejection, IDs, persistence | save/recall/delete, Undo, clear confirmation |
| Focus and check-ins | fake time, quiet hours, offline grace, due-event decisions | countdown, chime, Done/extend/switch behavior |
| Tasks and Today | add/complete/remove, escaping, stable page ID | live task page refresh and overlay navigation |
| Generated pages | CSP, sandbox, size/retention/update/delete | requested visuals open and audio/captions continue |
| Apps | tools/schema/auth-link fakes, disabled mode | independent connection/read; writes only as requested |
| Calls | gate, number validation, polling, timeout, no duplicate calls | separately requested call reaches intended number |
| Reconnect/restart | socket replacement, persisted state, task cleanup | network toggles and process restart recover |
| Kiosk and brand | package/resource scan, expression geometry | owner mode/PIN/Wi-Fi and all six toad expressions |

## Work completed versus pending

This plan and the new scaffold do not replace the application yet. Implementation order is 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Provider feasibility in milestone 1 blocks claims of an identical online voice experience; optional provider adapters can be developed against fakes meanwhile.

Current host has Python 3.12.3. Source review found no Java/adb on PATH and no installed server dependencies. Android build verification needs JDK 17 and the Android SDK; Python dependency installation and live credentials are separate from repository creation. Maintain progress and commands/results in the new repo so scaffold, fake validation and real-device success cannot be confused.

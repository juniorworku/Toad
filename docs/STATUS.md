# Rebuild status

## Implemented

- Kotlin Android app rebranded to `com.toad.companion`, with native animated moss-green toad and matching launcher icon. Local Claude mode and original 13 JVM test declarations are retained.
- Python FastAPI device transport, authentication, bounded output, cancellation-safe Stop, microphone mute, camera capture and atomic state persistence.
- Opt-in GPT-Live voice adapter: startup handshake, PCM24k audio, transcript deltas, client delegation and commentary/thinking responses.
- Saved-agent Python SDK adapter: agent definition synchronization, persistent sessions, serialized turns, timeouts, session recovery and idempotent event submission.
- Desk tools: status, consent-gated memory save/delete, focus, camera, controls, task add/complete/remove and Today/generated pages. Phone calls explicitly report unavailable.
- Lifecycle scheduler: bounded-rate voice reconnection, idle closing, end-after-reply closing, explicit Stop pause and once-only persisted check-ins. Offline reminders wait for a phone.
- Reproducible Python setup script creates a private configuration without overwriting existing values.
- Persisted HTML pages with bounded size/retention, kit injection, CSP and authenticated deletion. Diagnostic fake remains the default.

## Validation

- **49 Python tests pass**, including mock SDK HTTP/SSE tool actions and real loopback voice-provider WebSocket exchange.
- Strict mypy and Ruff lint/format checks pass. Dependency versions are locked.
- Local fake-mode HTTP/device smoke passes; Android XML and avatar SVG parse successfully.
- Android build remains blocked by missing JDK; device audio, wake phrase and avatar rendering are unverified.
- No live AI calls, original secrets, or private state imported. GitHub target is `juniorworku/Toad`; deployment has not been performed.

## Remaining parity work

1. Presence welcome-back behavior and optional away/no-reply calling. Current check-ins wait offline because phone calls are not configured.
2. Browser client/dashboard and optional Composio/AgentPhone integrations.
3. JDK 17/Android SDK setup, Android build/tests and physical-device audio/avatar/wake/kiosk acceptance.
4. Live provider account verification and deployment/operating scripts.

Workflow and batch history: [WORKFLOW.md](WORKFLOW.md).

See [implementation plan](IMPLEMENTATION_PLAN.md) and [provider compatibility](PROVIDER_COMPATIBILITY.md).

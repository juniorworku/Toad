# Implementation workflow and progress

## Working method

1. Compare each workflow with Desku source and the implementation plan.
2. Implement in Python while preserving the Kotlin device protocol.
3. Verify changes with deterministic regression tests and local transport smoke checks. Use simulated providers before any live validation.
4. Update STATUS.md with evidence and limitations, then commit a reviewable batch.
5. Keep tokens, environment files, generated state and local Android configuration outside Git.

## October 8, 2026 — voice, reasoning and branding

Renamed the app/package to Toad and replaced the owl with a native moss-green toad. Added GPT-Live transport, saved-agent SDK integration, tool actions and HTML/Today storage. Validation: 44 Python tests, strict typing and lint. Provider access and Android behavior remain unverified.

## October 8, 2026 — setup and lifecycle

Added a reproducible setup script with prerequisite inspection and private configuration generation. Added a lifespan-owned scheduler that shuts down with the server, retries dropped always-listening sessions at bounded intervals, honors Stop until Start, closes idle sessions and waits for reply activity before ending a conversation. Due check-ins are persisted as fired and delivered once; reminders remain pending while offline. Scheduled requests cannot grant memory-save consent.

Validation: 49 Python tests, including controlled-clock idle/reconnect/Stop/end-after-reply checks, concurrent reminder delivery, persisted offline reminders and scheduler shutdown. Ruff lint/format, strict mypy and the real local HTTP/WebSocket fake-mode smoke all pass. The setup script was executed successfully: dependencies installed and a mode-0600 private `.env` created.

At the end of this batch Java and adb were absent; the subsequent Android validation batch installs them. No paid AI calls or deployment occurred. Presence welcomes, browser dashboard, connected apps and phone calls are subsequent batches.

## Repeatable checks

```bash
python3 scripts/setup.py --check
.venv/bin/python -m pytest server/tests -q
.venv/bin/python -m ruff check server scripts
.venv/bin/python -m ruff format --check server scripts
.venv/bin/python -m mypy --strict server/src
.venv/bin/python scripts/smoke_local.py
```

Run from the repository root. In the restricted Codex environment, tests using async thread callbacks or loopback sockets require execution outside the sandbox. The installed environment was renamed from Nook; invoke tools via `.venv/bin/python -m` to avoid stale console-script paths.

## October 8, 2026 — Android toolchain validation

Installed official Amazon Corretto Java 17.0.20.1 and Google Android command-line tools after checking SHA-256 values from the publishers. Installed SDK platform 36 revision 2, build tools 36.0.0 and platform tools 37.0.1. Added local environment/validation scripts, SDK path configuration, Gradle distribution checksum and download retries. No shell profile or system Java change was required.

Validation completed with Gradle 9.7.1: debug APK assembly succeeded; all 13 JVM tests passed; lint passed with zero errors and 33 warnings. Fixed an unguarded API-28 kiosk call, paired coarse/fine location permissions and grants, and observed Compose locale changes. Updated deprecated avatar path calls. Verified APK signing, package identity and SDK range. The validation script caps Gradle concurrency at two workers. Physical-device tests are deferred by the user's instruction; adb lists no devices. See ANDROID_VALIDATION.md for the final artifact and checks.

## October 8, 2026 — engine parity, agent client, operating tools and skills

Compared the whole Desku codebase with Toad and closed every server-side gap. Ported Desku's engine behavior into the Python engine: brain message formats, the "Sorry" fallback so every delegation is answered, full voice instructions, tool outputs and errors, the kit-styled Today screen, presence welcome-back, Composio apps (Python SDK 0.25), AgentPhone away calls and calls on request, desk controls, the agent page and browser test client, `/api/overview` and `/api/apps/connect`. Added the Python terminal agent client, the live-check scripts (`server/scripts/`), the operating shell scripts with Linux support, Docker/Fly files, the demo photo, the vendored `composio` skill and five Toad skills, `CLAUDE.md`, and the live testing steps.

Found and fixed along the way: GPT-Live would wait forever on an empty delegation or a brain failure; Stop cancelled brain turns mid-tool-call; uvicorn logged the device token; desk pages loaded without the kit's fonts; the Android memory regex had a duplicated alternative. An independent review against Desku then found and fixed: a full GPT-Live command queue could drop spoken replies and leave a billed session open; a failed tool-result submit replayed the whole turn (re-running tools); `end_conversation` and screen taps changed the always-listening pause differently from Desku; two `call_phone` calls in one turn both reported success; brain timeouts had an empty error message. Each has a regression test.

Validation: 110 server tests (all 42 Desku server cases ported, plus protocol conformance against the Kotlin source), 41 agent CLI tests, Ruff, strict mypy, the agent/tool parity check, `smoke_local.py`, and a local fake-mode run through the USB bridge with `fake_phone.py`. Android: 13 JVM tests, debug APK (77,197,220 bytes), lint zero errors and 33 warnings. No live provider call, phone install or deployment was made; see [LIVE_TESTING_STEPS.md](LIVE_TESTING_STEPS.md).

# Live testing steps

Everything that can be checked without real accounts or a real phone is already automated and passing (see [Before you start](#0-before-you-start)). This file covers what is left: the paid AI providers, the optional integrations and the physical phone. Work through the stages in order: each one is cheaper than the next and narrows down where a problem is.

Tick each box as you go, and note anything that differs from **Expect** in the results table at the end.

> **Costs.** Stages A–G use the OpenAI API (GPT-Live is billed per minute while a voice session is open; each brain turn is billed per token). Stage F also uses Composio, and stage G places real phone calls with AgentPhone credit. Keep `ALWAYS_LISTEN=0` while testing so the voice session closes after `IDLE_CLOSE_SECONDS` of quiet.

## 0. Before you start

Run the offline checks from the repository root. Don't start live testing until both pass.

```bash
python3 scripts/setup.py --check
.claude/skills/toad-engine/scripts/check.sh      # server + agent tests, lint, types, agent/tool parity
source scripts/android-env.sh && scripts/validate-android.sh   # Android JVM tests, APK, lint
```

- [ ] `check.sh` ends with `All Toad engine checks passed.`
- [ ] `validate-android.sh` ends with `BUILD SUCCESSFUL`

You will need:

| For stage | What |
| --- | --- |
| A–G | An OpenAI API key with `api.agents.read`, `api.agents.write` and `api.responses.write`, on a paid tier (GPT-Live isn't on the free tier) |
| C, D | Headphones (GPT-Live is full duplex and hears its own voice through speakers) |
| D | `espeak-ng` (`sudo apt install espeak-ng`) or your own 16-bit WAV recordings |
| E | An Android 8.0+ phone with USB debugging on, a USB cable |
| E (wake phrase) | The Vosk model: `android/scripts/fetch-wake-model.sh` (~40 MB) |
| F | A Composio Platform project key (`ak_…`) and an app account to connect (e.g. Google Calendar) |
| G | An AgentPhone API key, an AgentPhone number attached to an agent, a payment method on that account, and your own phone number |

## 1. Configure

Edit the private `.env` in the repository root (created by `scripts/setup.py`; never commit it):

```bash
PROVIDER_MODE=openai
OPENAI_API_KEY=sk-...
OPENAI_PROJECT=            # optional: your project id
ALWAYS_LISTEN=0            # while testing: voice opens on Talk/check-in, closes when quiet
IDLE_CLOSE_SECONDS=120
TIME_ZONE=Africa/Addis_Ababa   # your IANA zone; check-ins and quiet hours use it
```

Leave `COMPOSIO_API_KEY` and the `AGENTPHONE_*` values empty until stages F and G.

Check what's set without printing secrets:

```bash
for k in OPENAI_API_KEY DEVICE_TOKEN COMPOSIO_API_KEY AGENTPHONE_API_KEY OWNER_PHONE; do
  grep -qE "^$k=.+" .env && echo "$k: set" || echo "$k: empty"; done
```

## 2. Stage A: the engine starts and syncs the agent

```bash
.venv/bin/python -m uvicorn toad_server.main:app --host 0.0.0.0 --port 8787 --no-access-log
```

- [ ] The log shows no traceback and ends with `Toad engine ready.`
- [ ] Open `http://localhost:8787/agent.html`. **Expect:** the dashboard opens without asking for a token (localhost), shows agent **Toad**, an `agentId` (`agent_…`), 12 desk tools plus web search, and Brain/Voice as connected or idle.
- [ ] `.claude/skills/toad-engine/scripts/overview.sh` prints `provider: openai` and the same agent id.
- [ ] Stop the engine (Ctrl-C) and start it again. **Expect:** no new agent is created (same `agentId`); the definition is only re-synced when `agent/toad-agent.json` changes.

If startup fails with a 401/403 from OpenAI, the key lacks the Agents permissions or the project is wrong. If it fails with a 404 on `/agents`, the account has no Agents API access yet: record it as a blocker.

## 3. Stage B: the brain alone

With the engine stopped (the script uses a throwaway data folder, but the same saved agent):

```bash
.venv/bin/python server/scripts/smoke_brain.py
```

- [ ] **"Can you read my to-do list?"**: the camera tool sends `demo/handwritten-todo.jpg`. **Expect:** Toad names how many items there are and the first few. (Desku read all five items in 3 of 4 runs; one miss is not a failure.)
- [ ] **"I'll do the first one for 25 minutes. Check in on me after."** **Expect:** `store:` at the end shows that focus and one check-in about 25 minutes out.
- [ ] **"The grant is due Friday, just so you know."** **Expect:** `memories: []` and no `UNEXPECTED` line. Toad may offer to remember it.

Optional, the terminal client (separate state in `agent/state/`):

```bash
cp agent/.env.example agent/.env    # add OPENAI_API_KEY
.venv/bin/python agent/toad_agent.py create-agent
.venv/bin/python agent/toad_agent.py start "Hey Toad, I'm working on the grant intro for 1 minute. Check in on me after."
sleep 70 && .venv/bin/python agent/toad_agent.py tick
```

- [ ] `start` streams a reply and a `set_focus` tool call; `tick` delivers the check-in and Toad asks how it went.

## 4. Stage C: voice in the browser

Start the engine (stage A command). Put on headphones, open `http://localhost:8787/`, press **Connect**, then **Talk**, and allow the microphone.

- [ ] **Expect:** state goes `connecting` → `open`; your words appear as captions.
- [ ] Say "Hi Toad." **Expect:** a short spoken greeting, no delegation (small talk stays in the voice model).
- [ ] Say "What time is it?" **Expect:** a short filler ("one sec"), then the correct local time spoken. The engine log shows `desk: delegation …: "What time is it?"`.
- [ ] Say "I'm working on the grant intro. Check in on me in one minute." **Expect:** a confirmation; the dashboard shows the focus and a check-in. After about a minute, **Toad speaks first** with a check-in ("How's the grant intro going?"), with no input from you.
- [ ] Say "Remember that the grant is due Friday at noon." **Expect:** "saved"-style confirmation; the memory appears on the dashboard and the page.
- [ ] Say "The budget review is on Monday, just so you know." **Expect:** not saved (Toad may offer to save it; saying "yes" then saves it).
- [ ] Say "What did I ask you to remember?" **Expect:** it answers from the saved memory.
- [ ] Press **Stop**, then **Talk** again (a new voice session) and ask "What was I working on?" **Expect:** "the grant intro": the brain session carries over between voice sessions.
- [ ] Talk over Toad while it's speaking. **Expect:** it stops within about a second (barge-in sends `interrupt`; queued audio is dropped).
- [ ] Say "Add email Felipe to my to-dos" and then "What's on my list?" **Expect:** the Today page link appears in the test client log, and `/p/<id>` shows the list.
- [ ] Stay silent for `IDLE_CLOSE_SECONDS`. **Expect:** state returns to `idle` (no idle charges).

## 5. Stage D: the stand-in phone (camera, scripted speech)

With the engine running:

```bash
.venv/bin/python server/scripts/fake_phone.py "Hey Toad, can you read my to-do list? I'm holding it up to the camera."
```

- [ ] **Expect:** `[phone] camera … → sending demo photo`, then Toad describes the list. Toad's audio is saved as a WAV (path printed at the end); play it and check it sounds like speech.
- [ ] Switch the camera off in the test client (or send `{"type":"camera","enabled":false}`) and ask again. **Expect:** Toad says the camera is off instead of describing anything.

## 6. Stage E: the real phone over USB

```bash
source scripts/android-env.sh
adb devices -l                         # the phone shows as "device"
(cd android && ./gradlew :app:installDebug)
adb reverse tcp:8787 tcp:8787
```

On the phone: allow microphone and camera; long-press the clock → Settings → engine `ws://127.0.0.1:8787` and the `DEVICE_TOKEN` from `.env` (or preset `toad.serverUrl` and `toad.deviceToken` in `android/local.properties` before installing).

- [ ] **Connect.** The dashboard shows *Desk phone* as online. The toad character is visible and animates (dozing, listening).
- [ ] **Talk button.** Tap **Talk**, ask "What's the date today?" **Expect:** the toad listens (aura follows your voice), thinks, then talks with its mouth moving with the loudness of the speech. Audio comes from the loudspeaker without echo feedback.
- [ ] **Camera read.** Hold up a handwritten list: "Can you read this?" **Expect:** a brief glance (no countdown) and a spoken summary.
- [ ] **Focus and check-in.** "I'll work on the slides, check in after one minute." **Expect:** timer chip; after a minute the screen wakes and Toad asks how it went.
- [ ] **No-reply call path off.** Without AgentPhone configured, an unanswered check-in just waits. **Expect:** no call, no error.
- [ ] **Mute.** Tap mute. **Expect:** Android's mic indicator disappears; speaking does nothing; tapping unmute restores it. Saying "mute the mic" also mutes (via `control_desk`).
- [ ] **Memories screen.** Tap memories, delete one. **Expect:** it disappears on the dashboard too. "Forget that" by voice also works.
- [ ] **Screen buttons.** Tap a suggested reply (e.g. "10 more minutes"). **Expect:** Toad answers it out loud as if you'd said it.
- [ ] **Pages.** "Show my day" and "Put a comparison of … on the screen." **Expect:** the page opens on the phone in the dark Toad kit style.
- [ ] **Presence.** Sit in front of the phone. **Expect:** the Today screen appears when it first sees you. With a focus set, leave for more than 10 minutes, then come back (outside quiet hours). **Expect:** Toad welcomes you back and asks about the focus.
- [ ] **Wake phrase** (model fetched before installing). With the mic unmuted say "Hey Toad". **Expect:** it wakes. Also say similar phrases ("hey road", "today") and check they don't wake it. Note false wakes/misses in the results; the grammar is untested on real speech.
- [ ] **Reconnect.** Unplug USB for 30 seconds and plug it back in (re-run `adb reverse` or use `scripts/start-toad.sh`). **Expect:** the app reconnects by itself; any check-in that came due meanwhile is delivered on reconnect.
- [ ] **On-phone mode still works.** Clear the engine address in Settings and add an Anthropic key. **Expect:** the original phone-only Claude mode works (`scripts/demo.sh` runs the scripted demo).

Wi-Fi instead of USB: set the engine to `ws://<laptop LAN IP>:8787` (debug builds allow plain `ws://`).

## 7. Stage F: apps (Composio)

Set `COMPOSIO_API_KEY` in `.env` and restart the engine. **Expect:** the log shows `apps: session … (N tools)`.

- [ ] Ask "What's on my calendar today?" **Expect:** Toad says the calendar isn't connected and a **Connect app** link appears on the phone screen and in the test client (it never reads the URL aloud).
- [ ] Connect from the dashboard (*Connect an app* → Google Calendar) or `.venv/bin/python server/scripts/connect_app.py googlecalendar`. **Expect:** the dashboard chip goes from connecting to connected.
- [ ] Ask again. **Expect:** a spoken summary of today's events; "Put it on the screen" shows a page.
- [ ] Ask it to create an event. **Expect:** it says exactly what it will create and waits for your yes before doing it.
- [ ] If anything fails, the error includes `(Composio log log_…)`; keep that ID for diagnosis.

Terminal alternative: `.venv/bin/python server/scripts/smoke_apps.py "What's on my calendar today?"`.

## 8. Stage G: away and on-request calls (AgentPhone)

Set `AGENTPHONE_API_KEY`, `AGENTPHONE_NUMBER` (Toad's number, `+1…`) and `OWNER_PHONE` (yours) in `.env`; restart. **Expect:** `away calls on: from … after 60s without a reply`.

- [ ] `.venv/bin/python server/scripts/call_me.py` **Expect:** your phone rings from Toad's number; Toad introduces itself as an AI; the transcript prints at the end. A `402` means the AgentPhone account needs a payment method.
- [ ] At the desk: "Call me." **Expect:** your phone rings right away (even in quiet hours, because you asked).
- [ ] No reply: set a 1-minute check-in, then don't answer the spoken check-in for `AWAY_CALL_AFTER_SECONDS` (60 s). **Expect:** the phone screen shows *calling*, your phone rings; after you hang up, the dashboard reflects anything you changed on the call. Something you asked it to remember on the call is saved; anything else is not.
- [ ] Reply at the desk within 60 s instead. **Expect:** no call.
- [ ] Phone offline: close the app, wait for a check-in to come due. **Expect:** a call (not during the first 2 minutes after the engine starts, and never during `QUIET_HOURS` unless you asked).
- [ ] Call a friend (US/Canada only, with their permission): "Call my friend at +1 …, tell them I'm running late." **Expect:** Toad reads the number back and waits for your yes; on the call it says it's an AI calling for you; afterwards it tells you at the desk what they said. A number nobody asked for is refused.

## 9. Stage H: kiosk and cloud (optional)

- [ ] **Kiosk** (a spare phone with no accounts): `adb shell dpm set-device-owner com.toad.companion/.kiosk.ToadAdmin` after setting `toad.kioskPin` in `local.properties` and reinstalling. **Expect:** boots straight into Toad; no status bar, home or app switcher. Exit: hold the top of the screen 5 s and enter the PIN. *Losing the PIN means a factory reset.*
- [ ] **Cloud** (Fly.io, your own account): set the secrets from `.env` with `fly secrets set`, then `fly deploy --ha=false` (or `scripts/switch-to-cloud.sh`). **Expect:** `https://toad-engine.fly.dev/healthz` returns `ok`, the phone connects on `wss://…/device`, and the dashboard works at `/agent`. Run one engine at a time.
- [ ] **USB bridge** (phone without internet): `.venv/bin/python server/scripts/usb_bridge.py https://toad-engine.fly.dev` with `adb reverse tcp:8787 tcp:8787`. **Expect:** the phone keeps `ws://127.0.0.1:8787` and talks to the cloud engine.

## 10. Results

Copy this table into an issue or `docs/STATUS.md` with the date, phone model and Android version.

| Stage | Result (pass / fail / blocked) | Notes |
| --- | --- | --- |
| A: engine starts, agent synced | | |
| B: brain alone (camera, focus, memory refusal) | | |
| C: browser voice (delegation, check-in, memory, barge-in, idle close) | | |
| D: stand-in phone (camera round trip) | | |
| E: real phone (audio, camera, check-in, mute, pages, presence, wake phrase, reconnect) | | |
| F: apps (connect link, read, consent before writing) | | |
| G: calls (call me, no-reply call, offline call, friend call, quiet hours) | | |
| H: kiosk / cloud / USB bridge | | |

## Troubleshooting

- **The engine log** is the first stop: every delegation, tool call and failure is logged (`desk: …`, `live: …`, `apps: …`, `phone: …`). Tokens are redacted.
- **No answer after speaking:** look for `desk: brain failed:`; the user hears "Sorry, I couldn't get to that just now". A `brain turn timed out` means a turn took over 150 s.
- **`voice: …` errors on the phone** come from GPT-Live (e.g. model access, quota).
- **Phone won't connect:** wrong token (the dashboard and phone must use the same `DEVICE_TOKEN`), `adb reverse` missing, or another device replaced it (close code 4000).
- **Echo or the toad talking to itself:** use headphones in the browser; on the phone, the loudspeaker plus call-grade echo cancellation should prevent it. Note the phone model if it doesn't.

## Cleanup

- Stop the engine (Ctrl-C) and `scripts/start-toad.sh` if used; `adb reverse --remove tcp:8787`.
- Set `PROVIDER_MODE=fake` again if you don't want the engine to make paid calls next time it starts.
- The saved agent and its session stay on your OpenAI project for reuse. To start fresh, clear `agent` in `data/toad.json` (engine) or run `.venv/bin/python agent/toad_agent.py end` (terminal client).

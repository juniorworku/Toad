---
name: toad-android
description: Build, test, install and drive Toad's Kotlin/Compose Android app (android/, package com.toad.companion). Use when changing the phone app, running its JVM tests or lint, installing it on a phone or emulator, pointing it at the Python engine, driving it with debug broadcasts, setting up the locked kiosk, or the "Hey Toad" wake phrase.
---

# Toad Android app

The phone app is a faithful port of Desku's app, rebranded: package `com.toad.companion`, the moss-green toad character (`ui/Toad.kt`, six expressions), the Nightlight screens, wake phrase "Hey Toad". It has two modes:

- **Engine mode** (Settings → engine address set): the phone is the Python engine's device. Mic up and voice down as 24 kHz PCM16, camera on request, the screen shows the engine's state. `engine/EngineLink.kt` is the protocol client; keep it in step with `server/src/toad_server/desk.py` (see the `toad-engine` skill).
- **On-phone mode** (address blank): Claude runs on the phone (`brain/Brain.kt`) with its own six tools and `memory/MemoryStore.kt`.

## Build and test (no device needed)

```bash
source scripts/android-env.sh      # repo-local JDK 17 + Android SDK in .tools/
scripts/validate-android.sh        # JVM tests, debug APK and lint (about 2 minutes)
```

Reports: `android/app/build/reports/tests/testDebugUnitTest/` and `android/app/build/reports/lint-results-debug.html`. APK: `android/app/build/outputs/apk/debug/app-debug.apk`. Lint must stay at zero errors.

## Install on a USB phone and connect to the engine

Ask before installing on someone's phone: it changes that device.

```bash
source scripts/android-env.sh
adb devices -l                                   # the phone must be listed and authorized
android/scripts/fetch-wake-model.sh              # optional: ~40 MB Vosk model for "Hey Toad"
(cd android && ./gradlew :app:installDebug)
adb reverse tcp:8787 tcp:8787                    # the phone reaches the laptop engine on localhost
```

In the app: long-press the clock → Settings → engine `ws://127.0.0.1:8787` and the `DEVICE_TOKEN` from `.env` (or preset `toad.serverUrl` / `toad.deviceToken` in `android/local.properties`). On Wi-Fi use `ws://<laptop LAN IP>:8787`; release builds need `wss://`.

## Drive it without speaking (debug builds only)

```bash
adb shell "am broadcast -p com.toad.companion -a com.toad.companion.debug.SAY --es text \"Help me plan my afternoon\""
adb shell "am broadcast -p com.toad.companion -a com.toad.companion.debug.WAKE"
adb shell "am broadcast -p com.toad.companion -a com.toad.companion.debug.SCREEN --es mode checkin --es text 'grant intro'"
scripts/demo.sh                                  # the whole on-phone demo with screenshots
```

Other actions: `PHOTO --es name todo.jpg`, `TIMER --ei seconds 10 --es task x`, `NEW_CONVERSATION`, `KIOSK_EXIT --es pin <PIN>`. Logcat tag: `Toad`.

## Kiosk (device owner)

Only on a phone with no accounts: `adb shell dpm set-device-owner com.toad.companion/.kiosk.ToadAdmin`. Exit: hold the top of the screen 5 s and enter `toad.kioskPin` from `local.properties`. Losing the PIN means a factory reset; say so before setting it up.

## Wake phrase

`voice/WakeWord.kt` grammar is `"hey toad"` plus decoys. It needs real-room validation; `scripts/check-wake-word.sh` checks synthetic voices offline (needs the model and espeak-ng or macOS `say`). Keep its Python grammar identical to `WakeWord.kt`.

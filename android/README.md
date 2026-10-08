# Toad Android

Native Kotlin/Compose app migrated from Desku commit `2aea122`. Namespace/application ID: `com.toad.companion`; Gradle project: `Toad`. Both local Claude and server-connected modes are retained. The default animated character is an moss-green toad, with all six expressions, eye-follow and voice-driven beak movement. Optional video-avatar fallback remains supported.

From this directory:

```bash
./gradlew :app:testDebugUnitTest :app:assembleDebug
```

Requires JDK 17 and Android SDK platform 36. Copy `local.properties.example` to `local.properties` and fill only your own values. For a USB-connected phone, use `adb reverse tcp:8787 tcp:8787`, configure `ws://127.0.0.1:8787`, and use the Python server's new device token. The server currently returns diagnostic text/test tones, not AI speech.

Run `scripts/fetch-wake-model.sh` to obtain the separate Vosk English model. “Hey Toad” is the initial recognition grammar; pronunciation accuracy remains untested. No model or human avatar assets are bundled. Original 13 JVM test scenarios were retained and rebranded. No successful APK build or device test has been established yet.

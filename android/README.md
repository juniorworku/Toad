# Toad Android

Native Kotlin/Compose app migrated from Desku commit `2aea122`. Namespace/application ID: `com.toad.companion`; Gradle project: `Toad`. Both local Claude and server-connected modes are retained. The default animated character is a moss-green toad, with all six expressions, eye-follow and voice-driven mouth movement. Optional video-avatar fallback remains supported.

From this directory:

```bash
./gradlew :app:testDebugUnitTest :app:assembleDebug
```

Requires JDK 17 and Android SDK platform 36. Copy `local.properties.example` to `local.properties` and fill only your own values. For a USB-connected phone, use `adb reverse tcp:8787 tcp:8787`, configure `ws://127.0.0.1:8787`, and use the Python server's new device token. Default fake mode returns diagnostic text/test tones. Opt-in live speech is implemented but requires account and device validation.

Run `scripts/fetch-wake-model.sh` to obtain the separate Vosk English model. “Hey Toad” is the initial recognition grammar; pronunciation accuracy remains untested. No model or human avatar assets are bundled. Original 13 JVM test scenarios were retained and rebranded. Debug APK assembly and all 13 JVM tests pass; Android lint has zero errors and 33 warnings. Device tests remain pending. See [validation details](../docs/ANDROID_VALIDATION.md).

## Repository-local toolchain

This host now has verified Amazon Corretto Java 17 and Google's Android command-line tools in the ignored `.tools/` directory. Installed SDK components: platform 36, build tools 36.0.0 and platform tools 37.0.1. `android/local.properties` points to the local SDK and remains ignored. The shell profile and system Java were not changed.

From the repository root:

```bash
source scripts/android-env.sh
java -version
adb version
scripts/validate-android.sh
```

The validation script runs debug JVM tests, APK assembly and Android lint, then lists connected devices. You can override the local paths with `TOAD_JAVA_HOME` and `TOAD_ANDROID_HOME` before sourcing the environment. SDK/Gradle caches and APK output are excluded from Git.

For a fresh host, install JDK 17 from [Amazon Corretto](https://docs.aws.amazon.com/corretto/latest/corretto-17-ug/downloads-list.html) and command-line tools from [Android Developers](https://developer.android.com/studio#command-tools), verifying the published checksums. Put Java in `.tools/jdk-17` and command-line tools in `.tools/android-sdk/cmdline-tools/latest`, or use the override variables. Accept the SDK licenses with `sdkmanager --licenses`, then install `sdkmanager 'platforms;android-36' 'build-tools;36.0.0' 'platform-tools'`. Configure `sdk.dir` in your ignored `android/local.properties` if using an SDK elsewhere.

Physical-device validation is deferred at the user's request. When ready, enable USB debugging, approve the computer, and check `adb devices -l`. Build output will be `android/app/build/outputs/apk/debug/app-debug.apk`; use `adb install -r` only when ready to install Toad on a test phone.

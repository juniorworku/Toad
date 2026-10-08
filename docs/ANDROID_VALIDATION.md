# Android validation — October 8, 2026

## Result

`testDebugUnitTest`, `assembleDebug` and `lintDebug` all completed successfully. The final incremental validation took 1 minute 52 seconds after the initial toolchain/dependency installation.

- JVM tests: 13 passed, zero failures/errors/skips (9 brain scenarios, 4 memory scenarios).
- Debug APK: `android/app/build/outputs/apk/debug/app-debug.apk`, 77,197,220 bytes.
- Package: `com.toad.companion`, version `0.1.0` (code 1), minimum API 26, target/compile API 36.
- `apksigner verify` succeeded; this is a debug build.
- APK SHA-256: `a1489e90235852406c7f3741864412d47e251751a492d36cddfd37b683a7858f`.
- Android lint: zero errors, 33 warnings. No lint baseline or error suppression was added.
- adb works; no device is connected. Physical-device testing is deferred by user instruction.

## Installed environment

Amazon Corretto Java 17.0.20.1, Gradle 9.7.1, Android command-line tools 22.0, platform 36 revision 2, build tools 36.0.0 and platform tools 37.0.1. Toolchains/caches live in ignored `.tools/`; SDK location is configured in ignored `android/local.properties`. Java, Android tools and Gradle downloads were verified against publisher SHA-256 checksums. System Java and shell profiles were not changed.

## Fixes found during validation

The first lint scan found three errors. Kiosk lock-task features are now applied only on API 28+, retaining Android 8 support. Wi-Fi configuration declares and grants coarse location alongside fine location. The remembered-card timestamp reads the Compose configuration locale, so locale changes are observed. Avatar curves use the current `quadraticTo` API.

## Remaining warnings and limits

Lint warnings include dependency-update notices, older kiosk APIs, cleartext network configuration for the existing local engine connection, resource/style suggestions and launcher-icon improvements. SDK metadata and Gradle deprecation warnings also remain. Debug native libraries retain symbols. These did not fail validation; the detailed local lint report is `android/app/build/reports/lint-results-debug.html`.

Build/test success does not establish physical-device audio, camera, voice-provider access, wake recognition, avatar appearance or device-owner kiosk behavior. These remain acceptance checks for a connected test phone. The Vosk wake model is a separate download and is not bundled.

## Repeat the validation

From the repository root:

```bash
source scripts/android-env.sh
scripts/validate-android.sh
```

The script uses two Gradle workers, runs JVM tests, debug assembly and lint, then lists adb devices. Test reports are in `android/app/build/reports/tests/testDebugUnitTest/`; all generated reports/APKs and private settings are excluded from Git.

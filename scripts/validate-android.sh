#!/usr/bin/env bash
set -euo pipefail
TOAD_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$TOAD_SCRIPT_DIR/android-env.sh"
if [[ ! -x "$JAVA_HOME/bin/java" || ! -x "$ANDROID_HOME/platform-tools/adb" ]]; then
  echo 'Missing local Java or Android platform tools. See android/README.md.' >&2
  exit 1
fi
java -version
adb version
cd "$TOAD_REPO_ROOT/android"
./gradlew --no-daemon --max-workers=2 :app:testDebugUnitTest :app:assembleDebug :app:lintDebug
adb devices -l

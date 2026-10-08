#!/usr/bin/env bash
# Source this file to use Toad's repository-local Android toolchain.
TOAD_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export JAVA_HOME="${TOAD_JAVA_HOME:-$TOAD_REPO_ROOT/.tools/jdk-17}"
export ANDROID_HOME="${TOAD_ANDROID_HOME:-$TOAD_REPO_ROOT/.tools/android-sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_USER_HOME="${TOAD_GRADLE_USER_HOME:-$TOAD_REPO_ROOT/.tools/gradle}"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

#!/bin/sh
# Emulator check of the debug APK built with -PlaunchOrigin=http://10.0.2.2:8080: it installs, the launcher
# opens, a browser inside the emulator loads the web app from the server on the runner, the app's JS runs.
#   sh android/ci/emulatore.sh <apk> <server log> <output dir>
set -eu
apk=$1 log=$2 out=$3
mkdir -p "$out"
adb wait-for-device
adb shell settings put global package_verifier_enable 0 || true
adb install -r "$apk"
adb shell pm list packages | grep -qx 'package:it.alias_pv60kg.everfit'
adb shell dumpsys package it.alias_pv60kg.everfit | grep -E 'versionCode|versionName|minSdk|targetSdk' | tee "$out/package.txt"
# the browser's first-run screens would hide the page: skip them where Chrome reads this file
adb shell 'echo "chrome --disable-fre --no-default-browser-check --no-first-run" > /data/local/tmp/chrome-command-line' || true
adb shell monkey -p it.alias_pv60kg.everfit -c android.intent.category.LAUNCHER 1
for _ in $(seq 1 60); do
  if grep -q ' GET /js/apk.js ' "$log"; then break; fi
  sleep 2
done
sleep 5
adb exec-out screencap -p > "$out/schermo.png"
adb shell dumpsys activity activities | grep -E 'topResumedActivity|ResumedActivity' | tee "$out/attivita.txt" || true
grep -E ' GET (/|/js/main.js|/js/apk.js|/manifest.webmanifest) ' "$log" | tee "$out/richieste.txt"
grep -q ' GET / ' "$log"
grep -q ' GET /js/main.js ' "$log"
grep -q ' GET /js/apk.js ' "$log"
echo "emulator: APK installed, launched, web app loaded from the runner"

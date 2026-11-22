# EverFit Android

The Android app is a [Trusted Web Activity](https://developer.chrome.com/docs/android/trusted-web-activity): it opens `https://fit.everbright.it` in Chrome, fullscreen, with the same service worker and web push as the PWA. There is no app code: the APK is a manifest, resources and `androidbrowserhelper`. Every feature lives in the web app (`web/`).

## Layout

| Path | What |
|---|---|
| `twa-manifest.json` | Bubblewrap scaffold configuration; Gradle and `VERSION` control the shipped shell |
| `app/build.gradle` | package `it.alias_pv60kg.everfit` (hyphen is not valid in a Java package), launch URL, colors, signing, R8 |
| `VERSION` | `versionName`; bump it for a release people should notice |
| `app/src/main/AndroidManifest.xml` | androidbrowserhelper activities and the notification delegation service |
| `app/src/main/res` | icons and splash, written by `web/scripts/icons.mjs` from `web/public/logo.svg`, like the web icons |
| `app/lint.xml` | lint runs with warnings as errors; only "newer version available" checks are informational |

Scaffolded once with Bubblewrap 1.27.0, then trimmed by hand. Do not run `bubblewrap update` on this folder: it would bring the removed code back.

## Versions

- `versionCode` = number of commits on `main` (`git rev-list --count HEAD`), passed by CI as `-PversionCode`. It only grows and a rerun of the same commit gives the same number.
- The launch URL carries `?apk=<versionCode>`. `web/src/components/UpdateBanner.tsx` compares it with `https://servizi.everbright.it/download/EverFit-Android.json` once a day and shows "Nuova versione dell'app" with the APK link when a newer one is published. Android installs it over the old one because the signing key is the same.
- Web content needs no APK: the app is the live site.

## Signing

Release key: alias `everfit`, certificate SHA-256 `C0:2C:72:77:08:F5:FD:8B:06:32:46:E8:43:9E:68:DF:C7:22:80:B5:53:3F:62:00:1B:48:27:28:52:0B:40:E8`. The same fingerprint is in `web/public/.well-known/assetlinks.json`; CI fails if they differ. The keystore is never in the repository: CI decodes it from the `ANDROID_KEYSTORE_B64` secret into a temp file. Losing the key means no update can ever be installed over existing installs.

## Build locally

```
cd android
gradlew assembleDebug lintRelease
```

Needs JDK 17+ and the Android SDK (platform 37, build-tools 37.0.0).

## Traps

- Digital Asset Links: Google fetches `/.well-known/assetlinks.json` without cookies. The backend serves the web shell anonymously and closes only `/api`; without a valid file Chrome shows the URL bar.
- The update check fetches another origin: the CSP in `Caddyfile` allows `connect-src https://servizi.everbright.it`, and servizi sends `Access-Control-Allow-Origin: https://fit.everbright.it` on that JSON only.

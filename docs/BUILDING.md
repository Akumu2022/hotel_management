# Building the apps

Three Android apps share this repo:

| App | Folder | Install name | Notes |
|---|---|---|---|
| Customer | `mobile/` (flavor `customer`) | Chakula | orders food |
| Rider | `mobile/` (flavor `rider`, entry `lib/rider/main.dart`) | Chakula Rider | jobs, GPS in the background |
| SMS (Till phone) | `forwarder/` (Kotlin) | Chakula Till | reads the Till's M-Pesa SMS |

## Everyday work (fast)

Use a debug run with hot reload. It takes seconds after the first build:

```bash
cd mobile
flutter run --flavor customer -d emulator-5554 --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
flutter run --flavor rider -t lib/rider/main.dart -d emulator-5554 --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
```

`10.0.2.2` is the PC as seen from the Android emulator. For a real phone on the same Wi-Fi use the PC's address (for example `http://10.0.0.158:8000/api/v1`) and allow port 8000 through Windows Firewall.

## APKs for a phone (release, one chip type)

```bash
cd mobile
API=http://10.0.0.158:8000/api/v1
flutter build apk --release --flavor customer --target-platform android-arm64 --dart-define=API_BASE=$API
flutter build apk --release --flavor rider -t lib/rider/main.dart --target-platform android-arm64 --dart-define=API_BASE=$API
# for the emulator use --target-platform android-x64
```

Output: `mobile/build/app/outputs/flutter-apk/app-customer-release.apk` and `app-rider-release.apk`.

SMS app: `cd forwarder; .\build-apk.ps1 -Server http://10.0.0.158:8000 -Out <where to put the apk>`.

## Rules that keep builds fast

- **Never delete `~/.gradle`.** It holds about 3 GB of downloaded libraries. Wiping it makes the next build re-download everything (the first build after a wipe took about an hour).
- **`path_provider_android` is pinned to 2.2.23** in `mobile/pubspec.yaml` (`dependency_overrides`). Version 2.3.x needs the `jni` library, which compiles C code with the Android NDK for every phone chip type. That made a release build take about 59 minutes. With the pin it takes minutes. Remove the pin only when a later release no longer needs `jni` (check with `flutter pub deps --style=compact | grep jni`).
- Gradle settings in `mobile/android/gradle.properties` and `forwarder/gradle.properties` turn on parallel builds, the build cache and incremental Kotlin.
- Build one chip type (`--target-platform android-arm64` for phones, `android-x64` for the emulator), not `--split-per-abi`, unless you are publishing.
- Add a library only when it is worth its build and download cost.

## Version numbers

An Android phone refuses an update whose internal version number (`+N` in `mobile/pubspec.yaml`) is lower than the installed one. It is `1.1.0+3000`. Raise `N` for every build you hand out. If you hit `INSTALL_FAILED_VERSION_DOWNGRADE`, uninstall the old app or raise `N`.

## Emulator notes

- Start it with `emulator -avd Medium_Phone_API_36.1 -camera-back none -camera-front none`. Opening the virtual camera crashes this PC's emulator graphics; photo upload is tested through the gallery instead (`adb push` a JPG to `/sdcard/Pictures`, then `adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Pictures/<name>`).
- Set the GPS to Bungoma: `adb emu geo fix 34.5606 0.5635` (longitude first).
- Send a test M-Pesa SMS: `adb emu sms send MPESA "<message text>"`. Use today's date and time in the message: the server refuses to confirm an order with a payment dated before the order existed (it goes to manual review).
- The disk image of the emulator is about 9 GB. Keep at least 2 GB free on C: or the emulator crashes.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q      # about 4 minutes, needs the Docker database
cd mobile && flutter test                             # seconds
cd web && npx tsc --noEmit -p .                       # type check
```

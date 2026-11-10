# gta4xlwifi Adaptive Audio

Final selected configuration: **Samsung SoundBooster + original Dolby tuning,
with -7 dB speaker volume-policy attenuation** for the **Galaxy Tab S6 Lite
(2020) Wi-Fi SM-P610 / gta4xlwifi**, **LineageOS 23.2 / Android 16**.

[Italiano](docs/README.it.md) · [Build](docs/BUILD.md#final-selected-build--7-db) ·
[Install / restore](docs/INSTALL.md#final-selected-version--7-db) ·
[Testing](docs/TESTING.md) · [Design](docs/DESIGN.md)

I chose this version after testing -11, -9 and -7 dB on my tablet.
It is the final choice for this device, **not a claim of universal safety or
acoustic equivalence to Samsung One UI**. The project remains experimental.
Not compatible with SM-P613, SM-P615, other revisions, One UI or other ROM builds.

## What this version does

- Runs the original, locally supplied ARM32 Samsung SoundBooster engine through
  a project-authored legacy Android effect bridge, on speaker music playback.
- Uses the **original Dolby XML**, not the earlier custom bass/treble EQ.
- Reduces covered speaker policy curves by **700 millibels (-7 dB)** relative
  to the reference ROM. This includes **alarms, notifications and calls**, not
  just music. Headphone/Bluetooth policy curves remain unchanged.
- Keeps the reviewed engine parameters unchanged. Non-speaker/mixed routes
  bypass the bridge; this behavior is native-tested, not tested on every real route.
- Requires no root in Android, no startup service and no SELinux weakening.

The policy reduction is not a hard acoustic limiter: downstream DSP can change
loudness. Start low and stop at the first audible distortion.

## Verified status

- Device: SM-P610, LineageOS `23.2-20261107-NIGHTLY-gta4xlwifi`.
- Final installation: recovery status **0**, followed by independent full vendor
  read-back matching the reviewed -7 dB image.
- Android boots; the two installed -7 dB policy hashes match the built image.
- Live speaker playback: SoundBooster **status 0**, configured/enabled,
  **stereo float, 48000 Hz**, speaker route `0x2`.
- Two live snapshots: **6772800 -> 6970560 processed frames**, zero bypass.
- Dolby and SoundBooster coexist in the running audio pipeline. No claim is
  made about long-term stability, all routes, fault paths or measured distortion.
- **79 private tests pass**; firmware-free runs pass 73 and skip six optional
  private-input tests. Full-size install/idempotence/restore checks also pass.

The bridge handles HIDL configuration mask `0x1e` and loads the original engine
and existing vendor C++ runtime as explicit local-group dependencies, fixing
the configuration and runtime-loading failures found during device testing.

## Important difference from the earlier installer

This final version is **not the old XML-only adaptive installer**. It rebuilds
vendor contents and its AVB hashtree/FEC for exact reviewed images, preserving
partition size, unrelated file contents/metadata and existing AVB policy.
It does not flash boot/vbmeta/EFS/recovery or disable verification.

**Do not reuse after an OTA**, even another LineageOS 23.2 nightly. The installer
accepts only exact pinned reference, previous -9 dB or final -7 dB images.
Unknown/torn blocks or unrelated changes are refused. Never remove these guards.
The historical XML-only workflow remains in the source for regression and
reproducibility; its OTA assumptions do not apply to the final SoundBooster build.

## Local packages and installation

This is a **source-only repository**. Samsung libraries, parameter payloads,
firmware, vendor images, device logs and generated ZIPs are **not published**.
Supply your own reviewed firmware inputs and follow the
[final build instructions](docs/BUILD.md#final-selected-build--7-db).

The retained local distribution is `dist/soundbooster-final/`:

| File | Operation |
|---|---|
| `audio-soundbooster-preflight-gta4xlwifi-los23.2.zip` | Checks without vendor writes |
| `audio-soundbooster-install-gta4xlwifi-los23.2.zip` | Installs the final -7 dB image |
| `audio-soundbooster-restore-gta4xlwifi-los23.2.zip` | Returns the **entire vendor to the reference ROM** |
| `SHA256SUMS`, `manifest.json` | Local package identities and build scope |

**Restore removes SoundBooster and -7 dB attenuation; it does not return to
-9/-11 dB.** No device backup is created. Keep the matching restore and your
official full ROM recovery path available. Known whole-block mixtures can be
restored, but torn/unknown blocks are refused; power-loss recovery is not guaranteed.

In recovery, choose **Apply update -> Apply from ADB**, sideload preflight then
install, re-entering sideload between them. Accept only your own hash-verified
local ZIP when prompted about its missing official signature. Require
`SOUNDBOOSTER APPLY VERIFIED` and recovery status 0, not just transfer completion.
Enable **Advanced -> Enable ADB** before reboot to inspect the log and full vendor
hash. See the [complete procedure](docs/INSTALL.md#final-selected-version--7-db).

## Development

Python 3.11+, C++17, pinned public dependencies and Android NDK 28.2.

```sh
python3 tools/fetch_sources.py
python3 tools/build_tools.py --host-only
python3 -m unittest discover -s tests -v
```

Public tests use synthetic files, never block devices or firmware. Optional
private emulation tests need Unicorn and locally supplied Samsung inputs;
see [build requirements](docs/BUILD.md). CI does not contain or flash firmware.
Keep local build inputs/evidence outside version control.

For bug reports, provide model, ROM version, operation, exact error and a
**redacted** log excerpt. Do not upload firmware, personal data or full logs.

## License and attribution

Project-authored code is [MIT](LICENSE); dependency and firmware rights remain
with their owners. See [THIRD_PARTY.md](THIRD_PARTY.md).
This community experiment is not affiliated with Samsung, Dolby or LineageOS.

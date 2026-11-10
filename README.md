# gta4xlwifi Adaptive Audio

I built this experimental, root-free recovery installer for my **Samsung
Galaxy Tab S6 Lite (2020) Wi-Fi, SM-P610 / gta4xlwifi**, running
**LineageOS 23.2 / Android 16**.

It reapplies a conservative speaker preset after compatible nightly updates
without flashing an old vendor image. **Not for SM-P613, SM-P615, other Tab S6
Lite revisions, stock One UI, or other LineageOS versions.**

[Italiano](docs/README.it.md) · [Build](docs/BUILD.md) ·
[Install / restore / updates](docs/INSTALL.md) · [Testing](docs/TESTING.md) ·
[Design and EQ values](docs/DESIGN.md)

## Why I made it

After installing LineageOS on my tablet, I noticed that the speakers were
louder, but sounded worse and crackled at higher volumes. I wanted cleaner
sound, not more volume, so I put together a conservative EQ and reduced
the speaker playback level.

It sounds better to me on my tablet. I haven't measured the acoustic response
or established exactly what caused the distortion, so **this isn't a
calibration or a recreation of Samsung's stock audio processing**.

I also wanted to reapply the preset after a nightly update without flashing
an entire vendor image from an older build. That's why I made the installer
adaptive rather than tying it to one nightly.

## What I changed

My preset:

- Subtracts **600 millibels (6 dB)** from speaker volume-curve points:
  **media, alarms, notifications, calls, and other configured speaker groups**.
  Your alarms will be quieter.
- Applies only cuts to the existing 20-band Dolby speaker optimizer.
- Leaves headphone/Bluetooth curves, amp gains, calibration, existing
  regulators and other Dolby parameters unchanged.
- Adds no new DSP, root, startup service or OTA-persistence script.

Android-added `AUDIO_STREAM_REROUTING`, `AUDIO_STREAM_PATCH` and
`call_assistant` groups are **not covered**. A policy gain reduction is not
a universal acoustic output ceiling: downstream DSP may compensate it,
and software cannot repair damaged speakers.

## How it works

The installer reads the **currently installed vendor**, checks the three
audio XML files against recognized original/patched templates, discovers
their EROFS offsets and stages changes before writing anything to vendor.

It changes only three 4 KiB compressed data clusters. Existing metadata,
permissions, SELinux labels, links, partition size and unrelated content are
preserved. A small persistent backup binds those blocks to whole-image
SHA256 identities. Reflashing an already applied preset is a no-op, not
another 6 dB reduction.

**The same locally built ZIP can be reused after a compatible 23.2 nightly.**
By “compatible,” I don't mean every nightly: changed XML, compression layout,
Android version or vendor verification causes refusal. It does not silently
accept new manufacturer tuning or overwrite newer vendor components.

## Safety and current status

**Experimental. Raw partition writes can prevent booting. Back up your data
and know how to reach recovery before using this. No warranty.**

No boot/vbmeta/EFS/recovery writes, partition resizing or AVB disabling are
performed. The original vendor hashtree remains unchanged and no longer
matches modified data. The installer only supports the tested first-stage
mount arrangement without vendor AVB flags; that check is not proof of
every possible future boot-chain behavior. Never relock the bootloader
with this custom ROM installed.

Here's what I've tested so far:

- My SM-P610, running LineageOS `23.2-20261107-NIGHTLY-gta4xlwifi`.
- An earlier full-image prototype: I installed it, checked that Android
  booted, and listened to the result.
- Adaptive tool: host and ARM64 **file-image** apply, idempotency and restore.
- Adaptive ZIP: real recovery preflight and apply with the preset **already
  present**, followed by successful boot and unchanged XML hashes/curves.
- I haven't yet tested adaptive raw-device writes from an untouched ROM,
  adaptive restore on a real partition, or a real subsequent nightly update.

I've documented the details in [the test matrix](docs/TESTING.md).
Do not treat successful sideload
transfer alone as successful installation.

## Obtain the installer

I'm publishing this as a **source-only** project. I've left out firmware,
vendor images, proprietary Dolby XML templates, and flashable ZIPs containing them.
Build locally using your own official reference ROM:

1. Follow [BUILD.md](docs/BUILD.md).
2. Verify the generated `dist/SHA256SUMS`.
3. Use **preflight**, then **install**, from Lineage Recovery.
4. Keep **restore** and its cache backup; read [INSTALL.md](docs/INSTALL.md)
   before flashing.

The local build creates three small ZIPs, not a full vendor image. Building
uses the original, publicly hashed **20261107** reference OTA to derive
recognized templates. Those templates may match later nightlies; the
installed nightly itself need not have that date.

Before incremental OTAs you may still need to restore unmodified vendor.
An adaptive reinstallation does **not** make an OTA delta valid against
modified source partitions. Do not wipe cache before restoring.

## Development

Python 3.11+, C++17, pinned public dependencies and an installed Android NDK.
No Python packages are required. See [BUILD.md](docs/BUILD.md).

```sh
python3 tools/fetch_sources.py
python3 tools/build_tools.py --host-only
python3 -m unittest discover -s tests -v
```

Host tests build pinned EROFS tools and require autotools, pkg-config, zlib
development headers and a C/C++ toolchain. They use synthetic XML and temporary regular
files, never block devices. CI does not contain or flash firmware.

If you run into a problem, please include your model, ROM version, operation, exact error
and a **redacted** relevant log excerpt. Remove serial numbers, account names,
file paths and other private details. Do not upload whole firmware, user
data or unredacted logs. Stop at a compatibility refusal; do not remove
guards or try this on another model.

## License and attribution

I've released the project code under [MIT](LICENSE). Third-party components retain their
licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).

This is my own community experiment. I'm not affiliated with Samsung, Dolby
or LineageOS; mentioning them doesn't imply their endorsement.

# Installation, recovery and updates

**SM-P610 / gta4xlwifi only. Experimental. Back up personal data first.**
Keep access to your installed ROM's official full OTA and working Lineage
Recovery. Do not relock the bootloader, format data, or disable AVB for this
project. Do not use the older full-vendor-image prototype after an OTA.

## Before starting

- Read the compatibility and test limits in [README](../README.md).
- Build the ZIPs locally and verify `dist/SHA256SUMS`.
- Keep all three ZIPs on your computer, plus a supported ROM recovery path.
- Charge the tablet and use a reliable cable. Never disconnect or power off
  during vendor writes.
- Keep Wavelet and other EQ apps disabled for comparison; preserve their
  settings. Stacking DSP makes results unpredictable.
- This preset lowers **alarm and notification volume as well as media**.

## Preflight

1. Enter Lineage Recovery using the device's supported procedure.
2. Choose **Apply update > Apply from ADB**.
3. From the project root:

   ```sh
   adb sideload dist/audio-adaptive-preflight-gta4xlwifi-los23.2.zip
   ```

4. A locally generated ZIP has no official Lineage signature. Recovery may
   show `footer is wrong` / `Signature verification failed`, followed by
   **Install anyway?**. Accept only your own hash-verified package. Do not
   globally disable signature checking. If there is no confirmation or a
   different error, stop.
5. Require **`ADAPTIVE PREFLIGHT OK`** on the tablet after confirmation.
   A completed ADB transfer or a particular percentage is not success.

Preflight does not write vendor or create its persistent backup. It mounts
system/product read-only with journal replay disabled and may recreate
temporary logical-partition mappings. It copies vendor to temporary storage
for validation; insufficient space is a refusal, not permission to bypass checks.

## Install

1. Return to **Apply update > Apply from ADB**.
2. Run:

   ```sh
   adb sideload dist/audio-adaptive-install-gta4xlwifi-los23.2.zip
   ```

3. Accept the expected local-signature prompt if present.
4. Require **`ADAPTIVE APPLY OK`**. The tool checks templates/layout, builds
   and checks a temporary image, saves a verified persistent backup, writes
   only three clusters, then verifies SHA256 of the entire result.
5. Reboot with **Reboot system now**.

If already applied, it recognizes all three patched XML files and returns
success without stacking attenuation. It does not fabricate an original
backup when the preset was already installed by another method.

## Listen and check

Start at low volume with familiar speech/music. Increase gradually; stop
at the first distortion and reduce the volume. Do not use prolonged high-level
tones. No software limiter guarantees speaker protection.

The following ordinary speaker groups have a 600-millibel policy reduction:
voice_call, system, ring, music, alarm, notification, bluetooth_sco,
enforced_audible, dtmf, tts, accessibility, assistant.

Internal rerouting/patch/call_assistant groups are not a covered universal
ceiling. Dolby Off may bypass optimizer EQ, and downstream loudness processing
may compensate attenuation. Headphone/Bluetooth curves are unchanged, but
every physical route/profile still needs testing on your device.

Advanced checks, if ADB is available:

```sh
adb shell sha256sum /vendor/etc/audio_policy_volumes.xml \
    /vendor/etc/audio_policy_engine_stream_volumes.xml \
    /vendor/etc/dolby/dax-default.xml
adb shell dumpsys media.audio_policy
adb shell dumpsys media.audio_flinger
adb shell logcat -b crash -d
```

Compare XML hashes to the locally generated manifest. Verify the actual
runtime curves/effects, not only file installation. Do not publish unredacted
dumps: they can contain app and device information.

## Restore

The backup lives in recovery-accessible ext4 cache:

```text
/cache/lineage-audio-adaptive/<original-whole-vendor-sha256>.bak
```

It contains only the original/modified audio clusters, their offsets, image
size, whole-image hashes and a checksum (about 25 KiB). It is **not a backup
of user data**. Do not wipe cache before restoration. Copy the backup to
your computer when recovery ADB access permits it; availability of that
access depends on the installed recovery.

To restore, use **Apply from ADB**:

```sh
adb sideload dist/audio-adaptive-restore-gta4xlwifi-los23.2.zip
```

Require **`ADAPTIVE RESTORE OK`**. Restore checks the entire vendor outside
the recorded audio clusters and refuses a different nightly. It can recover
partial writes inside those clusters, not corruption elsewhere. A missing,
corrupt or ambiguous backup causes refusal.

If installation failed **after writes began**, stay in recovery and apply
restore before booting. If backup restoration cannot work, use the device's
officially supported full-ROM recovery procedure; do not blindly format data
or flash a vendor from another build.

**Migration from the earlier fixed-build prototype:** already-patched
configuration is a no-op and creates no adaptive backup. Keep the original
fixed-build restore for that one build. On a fresh compatible vendor,
adaptive install creates its own backup.

## Nightly updates

For a compatible LineageOS 23.2 nightly:

1. If your OTA needs unmodified source partitions (especially incremental
   OTAs), restore the current vendor first.
2. Update with the official LineageOS method.
3. If the update overwrote vendor, reflash **the same adaptive preflight and
   install ZIPs**. There is no automatic addon.d persistence.
4. A new original vendor gets a new identity-bound backup.

You do not need to regenerate solely because the nightly date changes.
You **do** need a reviewed update to the project if XML contents, compression,
boot format, version or other checked assumptions change. A guard failure is
expected safe behavior. Never edit out guards to force installation.

## Error messages

| Message | Meaning / next step |
|---|---|
| `footer is wrong` before confirmation | Usually the expected lack of an official ZIP signature; not the tool's success or failure |
| `E9501` / `E9504` / `E9506` | Wrong model, Android or Lineage version; stop |
| `E9503` / `E9505` | Unsupported system/product layout or mount failure; stop |
| `E9511` | Unsupported boot ramdisk/vendor verification; AVB is not changed |
| `E9512` | Persistent cache unavailable; do not bypass backup requirements |
| `E9513` | Tool refused or failed; inspect `AUDIO ERROR` in recovery log |
| `Unrecognized audio configuration` | New/modified XML is not supported; request review |
| `Mixed/partial audio preset` | Not all three files agree; restore appropriately first |
| `ALREADY APPLIED` | Recognized preset, no extra attenuation and no vendor writes |

Any failure after writes start requires recovery handling, not repeated blind
reboots. A successful preflight cannot guarantee uninterrupted future writes.

# Installation, recovery and updates

## Final selected version: -7 dB

Only SM-P610/gta4xlwifi on the exact reviewed LineageOS 23.2 reference vendor,
previous -9 dB or final -7 dB images. This is a **broad vendor reconstruction**,
not the historical XML-only installer below. Never reuse after an OTA.
Back up personal data, charge the tablet and keep official full-ROM recovery
available. Do not relock the bootloader, disable AVB or weaken SELinux.

1. Build locally following [the final build](BUILD.md#final-selected-build--7-db).
   Verify all entries in `dist/soundbooster-final/SHA256SUMS`.
2. Keep the matching restore ZIP on the computer. It removes SoundBooster and
   the -7 dB attenuation, restoring the **entire reference vendor**, not -9/-11 dB.
3. Enter Lineage Recovery, **Apply update -> Apply from ADB**, then:

   ```sh
   adb sideload dist/soundbooster-final/audio-soundbooster-preflight-gta4xlwifi-los23.2.zip
   ```

4. Accept the missing official-signature prompt only for your verified local
   package. Require `SOUNDBOOSTER PREFLIGHT VERIFIED`. Re-enter sideload:

   ```sh
   adb sideload dist/soundbooster-final/audio-soundbooster-install-gta4xlwifi-los23.2.zip
   ```

5. Require `SOUNDBOOSTER APPLY VERIFIED` and recovery status 0. Transfer completion
   alone is insufficient. **Do not reboot on failure after writes start**:
   remain in recovery and use the matching restore. Unknown/torn blocks may
   require official full-ROM recovery; never blindly format data.
6. Enable **Advanced -> Enable ADB** before reboot. Check:

   ```sh
   adb shell 'tail -n 40 /tmp/recovery.log; sha256sum /dev/block/mapper/vendor'
   ```

   Require vendor SHA256
   `20eb8ae447797bbb386127c2010aa0610a698f2bd2271d15bf69ce93345674c8`.
7. Reboot Android, unlock and play familiar music through the speakers at low
   volume. Inspect `adb shell dumpsys media.audio_flinger` twice: SoundBooster
   status 0, `configured=1 enabled=1 device=0x2`, stereo float 48000 Hz, increasing
   `processed_frames`, zero speaker bypass. Dolby should also have status 0.
   The -7 dB policy covers alarms/notifications/calls too; it is not a hard limiter.

To undo, sideload
`dist/soundbooster-final/audio-soundbooster-restore-gta4xlwifi-los23.2.zip`
and require `SOUNDBOOSTER RESTORE VERIFIED` plus reference vendor SHA256
`278862bb89de2057e6fb78b9fd19bb5840762369ad7752cc02a0b49960d9beea`.
No device backup is created. Recognized whole-block mixtures are supported for
restore, but torn/unknown blocks are refused; power-loss recovery is not guaranteed.
Before an OTA follow the ROM's update procedure and restore unmodified vendor
when required. Do not reapply these exact-image ZIPs to the updated ROM.

## Historical XML-only installation and experiments

The remaining sections describe earlier workflows retained for development.
Their OTA reuse claims do not apply to the selected final SoundBooster version.

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
   and checks a temporary image, writes
   only three clusters, then verifies SHA256 of the entire result.
5. Reboot with **Reboot system now**.

If already applied, it recognizes all three patched XML files and returns
success without stacking attenuation. It does not fabricate an original
backup. The ZIP does not use cache or create backups.
The exact previous -6 dB and -9 dB presets can be replaced directly with the new -11 dB
preset. Unknown or mixed configurations are refused.

## Listen and check

Start at low volume with familiar speech/music. Increase gradually; stop
at the first distortion and reduce the volume. Do not use prolonged high-level
tones. No software limiter guarantees speaker protection.

The following ordinary speaker groups have an 1100-millibel policy reduction:
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

### Samsung Dolby baseline comparison

The optional baseline ZIP removes the project's optimizer adjustments by
installing the **byte-exact Dolby XML from the reviewed Samsung firmware**.
Its 20 speaker optimizer gains are zero. The same file is already present
in the unmodified Lineage reference, so this is not evidence that the full
Samsung sound is flat. Speaker volume curves remain reduced by 11 dB.
SoundBooster/SoundAlive libraries, mixer settings and hardware calibration
are not installed or changed.

After building and verifying the separate packages, use the same recovery
procedure, substituting:

```sh
adb sideload dist/samsung-dolby-baseline/audio-samsung-baseline-preflight-gta4xlwifi-los23.2.zip
adb sideload dist/samsung-dolby-baseline/audio-samsung-baseline-install-gta4xlwifi-los23.2.zip
```

Re-enter **Apply from ADB** between packages and require the corresponding
`ADAPTIVE ... OK` messages. The baseline installer accepts the reviewed
current +2 dB bass preset directly, without backup or prior reset.
Its restore ZIP resets the three XML files to their reference-ROM originals,
including removal of the -11 dB policy reduction; it does not restore the
previous custom EQ.

For comparison keep spatial audio off and use the same passage at a low
listening level. **This is not a full One UI/SoundBooster reproduction.**
Recovery/file-image verification does not establish acoustic equivalence.

### Experimental native SoundBooster packages

These are **separate private packages**, not replacements for the XML-only ZIPs
above. Do not install them merely because the native PCM tests passed.
An authorized device trial verified installation/read-back and Android boot.
The first bridge attached but failed configuration with status `-22`; the
installed correction accepts HIDL mask `0x1e`. Actual processing and
route/volume/Dolby coexistence still require active-playback verification.

The new experimental installer performs **broad block reconstruction of vendor**,
not a three-cluster edit. It accepts only the byte-exact reviewed reference ROM,
the inspected current custom preset, or the reviewed SoundBooster candidate.
It refuses a different nightly or unrelated vendor changes even if the device
and Android versions match. Never bypass these guards or reuse after an OTA.
The three ZIPs are generated together in a fresh, separate directory.

The `hidl-fix` migration set instead pins reference, first installed SoundBooster
and corrected SoundBooster images. Keep its matching restore available:
the initial experimental restore cannot recognize the corrected image.
The corrected vendor SHA256 verified by recovery and independent raw read-back is
`35472c09cae0800bf611cf690a35687625fc8c03db91a89c742fc854f64f9d1c`.
After boot, unlock the tablet and play music through its speakers. Inspect
`adb shell dumpsys media.audio_flinger` twice: require effect status `0`,
`configured=1 enabled=1`, speaker `device=0x2`, and increasing
`processed_frames`. An enabled effect alone does not establish processing;
`bypassed_frames` is reported separately. Do not bypass the lock screen.

The later active-playback check still failed with `-22`: the engine's
`__cxa_call_unexpected` dependency was not visible in the service namespace.
The separate `runtime-fix` set pins reference, HIDL-corrected and runtime-linked
images. Its candidate hash is
`529c2a3e0559854b567f75f2e934407ad74d7ea0aeab0521ad690b9a00ff2a36`.
It adds no installed files beyond the same three SoundBooster files and does
not replace vendor libc++ or change SELinux/linker configuration. Keep its
matching restore; the earlier restore sets do not recognize this new image.
Passing isolated namespace tests does not replace the live playback checks above.

The runtime-linked version has now passed those live speaker checks with Spotify:
status 0, configured/enabled, stereo float 48 kHz, increasing processing counters,
zero bypass, Dolby concurrently status 0, and unchanged -11 dB policy hashes.
The user rebooted before the latest recovery log/full vendor hash was captured;
that read-back remains unverified. No acoustic equivalence or all-routes claim
follows from this successful speaker session.

For the separately built **SoundBooster -9 dB comparison**, use the preflight
and install ZIPs in `dist/soundbooster-minus9`. This raises covered speaker
policy curves by 2 dB, including alarms/notifications, and leaves SoundBooster,
Dolby and non-speaker curves unchanged. Start playback at low volume after boot.
To return to working SoundBooster **-11 dB**, use the **install** ZIP in
`dist/soundbooster-return-minus11`. The **restore** ZIP still removes the whole
experiment and returns vendor to reference-ROM originals, not -11 dB.
Keep the matching packages and official ROM recovery path available.

The further **-7 dB** comparison uses `dist/soundbooster-minus7`; it adds
another 2 dB to covered speaker policy curves compared to -9 dB. Use the
**install** ZIP in `dist/soundbooster-return-minus9` to return to SoundBooster
-9 dB. Earlier restore sets do not recognize the -7 dB image; use the matching
new restore only to reset the entire vendor to the reference ROM.
SoundBooster/Dolby remain unchanged. Increase listening volume gradually and
stop at the first audible distortion; this is not a guaranteed protection limit.

The **preflight** reads the whole logical vendor and the installed boot, checks
all original/current/candidate block identities and reconstructed whole-image
hashes. It does not write vendor. Like the older preflight, it mounts
system/product read-only without journal replay and recreates temporary logical
partition mappings. Recovery's temporary RAM must fit the extracted block bundle
(approximately 332 MB) plus the ZIP and tooling. Insufficient space is a refusal.

The **install** checks the same gates, writes changed vendor blocks, syncs and
verifies the entire partition SHA256. It does not reboot automatically.
Keep a stable power source, the matching restore ZIP and official full ROM ready.
Do not install while recovery's checks or package identity are uncertain.

The **restore** returns the **entire vendor to the exact reference ROM**,
including removal of -11 dB attenuation; it does not restore the previous custom
EQ. No device backup or cache file is created. It also accepts known mixtures of
whole reference/current/candidate blocks after an interrupted write. Unknown or
torn blocks are refused **before any new writes**; this is not guaranteed
power-loss recovery. If writes failed, stay in recovery and use the matching
SoundBooster restore. If it refuses unknown blocks, stop and use the supported
official ROM recovery path, not another vendor image or data formatting.

Require `SOUNDBOOSTER PREFLIGHT VERIFIED`, `SOUNDBOOSTER APPLY VERIFIED` or
`SOUNDBOOSTER RESTORE VERIFIED` from the ZIP as appropriate. The native tool also
prints its verified whole-image hash after writes. A successful transfer alone
is not success. Do not use the older `audio-adaptive-restore` ZIP to undo
SoundBooster: it cannot remove the added libraries/filesystem metadata.

These local ZIPs contain proprietary vendor-derived blocks and are not for
public redistribution. No acoustic equivalence to Samsung One UI is claimed.

## Restore

The restore ZIP replaces a recognized previous or current preset with the
three original reference-ROM XML files. No cache backup is required or created.
It preserves unrelated vendor content and refuses unknown configurations.
It is not a full vendor or user-data backup.
The decoded XML is restored exactly; recompression can differ from the
original ROM bytes, so this does not guarantee incremental-OTA source hashes.

To restore, use **Apply from ADB**:

```sh
adb sideload dist/audio-adaptive-restore-gta4xlwifi-los23.2.zip
```

Require **`ADAPTIVE RESTORE OK`**. Both install and restore stage the changes
and verify that only the three audio clusters change. An interrupted write
that leaves unknown XML cannot be repaired by this template-based restore.

If installation failed **after writes began**, stay in recovery and apply
restore before booting if the configuration is still recognized. Otherwise use the device's
officially supported full-ROM recovery procedure; do not blindly format data
or flash a vendor from another build.

**Migration from earlier presets:** the reviewed -6 dB and -9 dB
configuration is accepted directly. Restore returns to the original ROM
values, not the previous preset.

## Nightly updates

For a compatible LineageOS 23.2 nightly:

1. If your OTA needs unmodified source partitions (especially incremental
   OTAs), restore the current vendor first.
2. Update with the official LineageOS method.
3. If the update overwrote vendor, reflash **the same adaptive preflight and
   install ZIPs**. There is no automatic addon.d persistence.
4. A fresh compatible vendor is recognized without any old backup.

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
| `E9513` | Tool refused or failed; inspect `AUDIO ERROR` in recovery log |
| `Unrecognized audio configuration` | New/modified XML is not supported; request review |
| `Mixed/partial audio preset` | Not all three files agree; restore appropriately first |
| `ALREADY APPLIED` | Recognized preset, no extra attenuation and no vendor writes |

Any failure after writes start requires recovery handling, not repeated blind
reboots. A successful preflight cannot guarantee uninterrupted future writes.

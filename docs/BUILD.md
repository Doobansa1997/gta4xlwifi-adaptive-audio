# Build locally

## Final selected build: -7 dB

The selected distribution is now **SoundBooster + original Dolby, -7 dB**,
not the historical XML-only preset below. Only `dist/soundbooster-final/`
is retained as the local distribution. Everything under `build/`, `inputs/`,
`third-party/` and `dist/` stays ignored and must not be published.

Use the requirements, public dependency download, host build and reference-ROM
preparation steps below. Build the Android recovery tool as described in this
document. Supply the hash-checked Samsung SM-P610 firmware inputs described in
the native SoundBooster sections, extracted locally into `build/samsung/vendor`.
No Samsung binary or parameter data is provided by this repository.

Build the two pinned images required by the final three-state bundle:

```sh
python3 tools/stage_soundbooster.py \
  --image build/reference-vendor.img --vendor build/samsung/vendor \
  --ndk "$ANDROID_NDK_HOME" --speaker-attenuation-mb 900 \
  --output build/samsung/soundbooster-minus9 --prepare-partition

python3 tools/stage_soundbooster.py \
  --image build/reference-vendor.img --vendor build/samsung/vendor \
  --ndk "$ANDROID_NDK_HOME" --speaker-attenuation-mb 700 \
  --output build/samsung/soundbooster-minus7 --prepare-partition

python3 tools/package_soundbooster.py --profile final \
  --original build/reference-vendor.img \
  --live build/samsung/soundbooster-minus9/partition/vendor.img \
  --candidate build/samsung/soundbooster-minus7/partition/vendor.img \
  --output dist/soundbooster-final

cd dist/soundbooster-final
shasum -a 256 -c SHA256SUMS
```

Output directories must be new; retained local inputs do not need rebuilding.
Staging defaults to 700 millibels and packaging defaults to `final`. The separate
legacy XML tool still defaults to -11 dB; it is not the final build command.
The -9 dB image is a local migration/build input, not a second distributed preset.
The final candidate hash is
`20eb8ae447797bbb386127c2010aa0610a698f2bd2271d15bf69ce93345674c8`.
Image and firmware pins are never bypassed to accommodate another compiler/ROM.

Retain the three ZIPs plus `SHA256SUMS` and `manifest.json`. `blocks.bin`
is an intermediate already embedded in every ZIP and may be removed from
the output directory after offline verification. Original build inputs,
audits and rollback evidence remain local for reproducibility.
Do not delete required inputs merely to shrink the Git repository: they are
already ignored. Old generated ZIP variants are not part of the final distribution.

**Restore resets the full reference vendor**, removing SoundBooster/attenuation.
The final ZIPs cannot be reused after an OTA. See
[final installation](INSTALL.md#final-selected-version--7-db).

## Historical workflows and supporting tools

The following sections retain earlier experiments, analysis methods and
XML-only commands for reproducibility/testing. They are not alternate final
installation instructions. Explicit historical profiles are required when
rebuilding earlier packages.

## Requirements

Tested development host: macOS Apple Silicon, Python 3.15 and Android NDK
`28.2.13676358`. Python **3.11+** is required. Linux host tests also run in CI;
Linux NDK cross-building is supported by the script but not device-validated.
Windows is not supported directly.

Install only missing tools. Example package lists:

```sh
# macOS
brew install python erofs-utils brotli autoconf automake libtool pkgconf

# Debian/Ubuntu
sudo apt-get install build-essential python3 erofs-utils brotli \
    autoconf automake libtool pkg-config zlib1g-dev
```

Install Android NDK 28.2 through your normal Android SDK setup, then set:

```sh
export ANDROID_NDK_HOME="/absolute/path/to/ndk/28.2.13676358"
```

No root privileges are needed for compilation or host tests.

## 1. Download public source dependencies

```sh
python3 tools/fetch_sources.py
```

This fetches pinned erofs-utils 1.9.4, LZ4 1.10.0, PicoSHA2, Android's
Reed-Solomon codec and Lineage's `avbtool.py`, verifies
SHA256 and extracts them using Python's restricted tar-data filter.
No firmware is downloaded. Sources go into ignored `third-party/`.

If GitHub regenerates a source archive with different bytes, the build will
stop. Review the upstream commit/archive before updating its checksum;
do not bypass verification.

## 2. Run public synthetic tests

```sh
python3 tools/build_tools.py --host-only
python3 -m unittest discover -s tests -v
```

These tests build synthetic EROFS and boot fixtures, then check file-image
apply/restore and failures without requiring or redistributing firmware.
The host build also compiles pinned erofs-utils 1.9.4 into `build/host-bin`;
scripts prefer those tools to older distribution versions lacking `--cat`.

## 3. Supply the official reference ROM locally

Obtain `lineage-23.2-20261107-nightly-gta4xlwifi-signed.zip` through the
[official device download page](https://download.lineageos.org/devices/gta4xlwifi/builds).
Verify its SHA256 against the official listing:

```text
3c8fffba1139086d931cfcdb7936ecdec309056747ae28ee93765352b77da96a
```

Place it outside Git or in ignored `inputs/`. The project does not mirror
that ROM. If the build is no longer available officially, do not substitute
an untrusted download or disable the checksum guard.

```sh
python3 tools/prepare_rom.py --rom /absolute/path/to/reference-ROM.zip
```

The script reconstructs **only vendor**, checks its SHA256, reads five
configuration files, and extracts the official boot and update-binary.
It supports the reference full-OTA v4 `new` transfer format, not incremental
or A/B payload packages. Inputs stay in ignored `build/`.

Expected original vendor SHA256:

```text
278862bb89de2057e6fb78b9fd19bb5840762369ad7752cc02a0b49960d9beea
```

## 4. Compile Android ARM64 tools

```sh
python3 tools/build_tools.py
```

The tools are built statically for ARM64 Android API 28. NDK paths are supplied
via the environment, not embedded in source. `configure` is generated locally
with autotools. LZ4 support is explicitly required: a build without it fails
rather than producing an unusable filesystem checker.

## 5. Generate local packages

```sh
python3 tools/package.py
cd dist
shasum -a 256 -c SHA256SUMS     # macOS; Linux: sha256sum -c SHA256SUMS
```

Outputs:

- `audio-adaptive-preflight-gta4xlwifi-los23.2.zip`
- `audio-adaptive-install-gta4xlwifi-los23.2.zip`
- `audio-adaptive-restore-gta4xlwifi-los23.2.zip`
- `manifest.json` and `SHA256SUMS`

These generated packages contain locally extracted templates and the official
updater executable. They are **not covered wholesale by this project's MIT
license**. Do not commit `build/`, `dist/` or redistribute proprietary firmware
material without appropriate permission. This repository's release is source-only.

Before flashing, run the additional local reference-image test:

```sh
cd ..
python3 tools/check_reference.py
```

That test operates on a temporary copy, compares the resulting three XML
files to generated templates, checks idempotency, and restores the exact
original image. It does not test the raw block-device path or future OTAs.

Read [INSTALL.md](INSTALL.md) before touching the tablet.

### Optional Samsung Dolby baseline

This is a separate comparison profile, not a reconstruction of SoundBooster.
Supply a local Samsung SM-P610 `P610XXS7FYD1` vendor extraction. The packager
requires the reviewed Dolby SHA256 and byte equality with the original
Lineage reference. It copies that Dolby XML unchanged and keeps the existing
1100-millibel speaker policy reduction. No Samsung DSP libraries are packaged.

```sh
python3 tools/package.py --profile samsung-dolby-baseline \
    --samsung-vendor build/samsung/vendor
python3 tools/check_reference.py --stage build/stage-samsung-baseline \
    --samsung-vendor build/samsung/vendor
cd dist/samsung-dolby-baseline
shasum -a 256 -c SHA256SUMS
```

Outputs are named `audio-samsung-baseline-{preflight,install,restore}-gta4xlwifi-los23.2.zip`
in `dist/samsung-dolby-baseline/`, with a separate manifest and checksums.
The existing custom ZIPs in `dist/` are not overwritten. The baseline accepts
the reviewed custom presets, including the +2 dB bass revision; returning
from baseline to custom requires a newly built custom ZIP with baseline support.
`tools/check_reference.py` checks exact Samsung bytes after installation,
not merely zero numeric optimizer gains.

### Read-only SoundBooster AMF analysis

These commands produce local analysis reports, **not an installable SoundBooster
effect or a complete Samsung preset**. The first uses only Python's standard
library and accepts the reviewed parameter-file hash:

```sh
python3 tools/soundbooster.py \
    --parameters build/samsung/vendor/etc/SoundBoosterParam.txt \
    --output build/samsung/soundbooster-amf.json
```

An optional verification uses Unicorn in an isolated virtual environment.
It emulates only the reviewed ARM32 type-1 coefficient routine and intercepts
its two math imports; the Android library is never loaded into the host
process or installed on the tablet.

```sh
python3 -m venv build/samsung/emulator-venv
build/samsung/emulator-venv/bin/python -m pip install unicorn==2.1.4
build/samsung/emulator-venv/bin/python tools/verify_soundbooster.py \
    --engine build/samsung/vendor/lib/lib_SoundBooster_ver1050.so \
    --parameters build/samsung/vendor/etc/SoundBoosterParam.txt \
    --output build/samsung/soundbooster-emulation.json
```

The same optional environment can trace conditional control dispatch and
verify the reviewed high-pass coefficient response:

```sh
build/samsung/emulator-venv/bin/python tools/trace_soundbooster.py \
    --engine build/samsung/vendor/lib/lib_SoundBooster_ver1050.so \
    --parameters build/samsung/vendor/etc/SoundBoosterParam.txt \
    --output build/samsung/soundbooster-controls.json
SOUNDBOOSTER_VENDOR=build/samsung/vendor \
    build/samsung/emulator-venv/bin/python -m unittest discover \
    -s tests -p test_soundbooster.py -v
```

The trace executes reviewed parameter routines, original compression-curve
generation and FILX/EMQF parameter conversion, not the complete DSP.
It stubs dependent objects and intercepts unimplemented stages; its explicit
assumptions and false runtime/audio-verification flags must be retained.
The private tests also use synthetic markers and invalid/boundary values
against the reviewed instructions; they do not modify firmware or the device.

All tools reject unknown firmware identities. Keep extracted proprietary
inputs and reports local in ignored `build/`. The public test suite uses
synthetic records and requires no Unicorn installation; six private
original-instruction tests are skipped unless `SOUNDBOOSTER_VENDOR` is supplied.
See [DESIGN.md](DESIGN.md#verified-static-soundbooster-amf-model) for the
verified scope and remaining runtime/DRC limitations.

### Optional native SoundBooster engine probe

This is **not an installer or an Android effect**. It compiles a separate
ARM64 shell executable and, only with `--run-device`, temporarily copies the
reviewed 64-bit engine, NDK C++ runtime, executable and generated parameter
payload to a unique directory under `/data/local/tmp/`.
No audio API is called: synthetic PCM is processed in memory and discarded.
No effect is registered/enabled and no partition, setting or system file is
modified. The engine is native proprietary code, **not sandboxed emulation**;
use only the hash-verified input on the reviewed test device.

Extract the original vendor files locally (not firmware data for committing):
`lib64/lib_SoundBooster_ver1050.so` and `etc/SoundBoosterParam.txt`.
Build-only command (no ADB/device access):

```sh
ANDROID_NDK_HOME=/path/to/android-ndk \
python3 tools/probe_soundbooster.py --vendor build/samsung/vendor \
    --output build/samsung/soundbooster-native.json
```

Opt-in execution requires an explicit connected-device serial:

```sh
ANDROID_NDK_HOME=/path/to/android-ndk \
python3 tools/probe_soundbooster.py --vendor build/samsung/vendor \
    --adb /path/to/adb --serial YOUR_SERIAL --run-device \
    --output build/samsung/soundbooster-native.json
```

Transfer hashes are checked on-device. Each probe process has a 30-second
alarm; ADB subprocesses have a 90-second timeout. Named temporary files and
the unique directory are removed in `finally`, including on failure; cleanup
errors are surfaced. A disconnected device may require manual cleanup of
that exact directory once reconnected. The JSON is written only after both
mode reports pass validation and cleanup succeeds; build-only does not write
that report. Keep inputs and output local.

### Experimental effect-adapter harness

The native launcher also builds and tests the project-authored legacy Android
effect adapter. Add `--effect-harness` to the native command and use a separate
report path:

```sh
ANDROID_NDK_HOME=/path/to/android-ndk \
python3 tools/probe_soundbooster.py --effect-harness \
    --vendor build/samsung/vendor --adb /path/to/adb \
    --serial YOUR_SERIAL --run-device \
    --output build/samsung/soundbooster-adapter.json
```

This copies one additional test `.so` to the same unique temporary directory,
loads it only in the harness, verifies PCM against the engine and removes all
five files. Both PCM16 and native float stereo at 48000 Hz are compared exactly;
float speaker input is limited to finite normalized samples in [-1,1].
Both WRITE and ACCUMULATE output modes are tested: accumulation preserves the
existing destination, saturates PCM16 and retains finite float headroom.
The report includes WRITE processing-time/audio-period ratios for 192 calls per
format; this is a shell benchmark, not real-time service certification.
No system effect activation, XML edit or audio playback occurs.
The bridge embeds the temporary engine/payload paths and the exact binary
payload SHA256; the output is **not suitable for installing under vendor**.
Build-only omits `--run-device --serial` as above.

For independent ABI validation, also supply
`--aosp-include build/samsung/aosp-include`. That directory must contain
original Android 16 AOSP headers at these relative paths:

- `hardware/audio_effect.h` from
  [platform/hardware/libhardware/include_all](https://android.googlesource.com/platform/hardware/libhardware/+/refs/heads/android16-release/include_all/hardware/audio_effect.h).
- `system/audio_effect.h`, `audio_effect-base.h`, `audio.h`,
  `audio-base-utils.h`, `audio-base.h`, `audio-hal-enums.h` and
  `audio_common-base.h` from
  [platform/system/media/audio/include](https://android.googlesource.com/platform/system/media/+/refs/heads/android16-release/audio/include/system/).
- `cutils/bitops.h` from
  [platform/system/core/libcutils/include](https://android.googlesource.com/platform/system/core/+/refs/heads/android16-release/libcutils/include/cutils/bitops.h).

Keep the original headers and their license notices local under ignored
`build/`; no header modifications or stand-in definitions are needed.
The launcher pins the three effect-header hashes and records them in the
report. Unknown revisions fail rather than silently accepting changed ABI.
Without that option, the harness runs but reports independent AOSP-header
verification as false.

### ARM32 service compatibility and candidate configuration

The reviewed Lineage vendor image's audio service, HIDL effect implementation
and DAP library are **ELF32 ARM**, even though the tablet also supports ARM64.
The live implementation paths agree with this layout. A 64-bit shell test
cannot demonstrate that the 32-bit effect service will load the same library.
Use the original ARM32 engine for the service-compatible harness:

```sh
ANDROID_NDK_HOME=/path/to/android-ndk \
python3 tools/probe_soundbooster.py --abi armeabi-v7a --effect-harness \
    --aosp-include build/samsung/aosp-include \
    --vendor build/samsung/vendor --adb /path/to/adb \
    --serial YOUR_SERIAL --run-device \
    --output build/samsung/soundbooster-adapter-arm32.json
```

`--abi arm64-v8a` remains the default for reproducing earlier experiments.
Both ABIs use separate build directories under `build/samsung/native-probe/`.
The report records the selected ABI, its pinned engine hash and the actual
harness pointer width, refusing a process-width mismatch. Omit
`--effect-harness --aosp-include ...` to run the direct Music/Legacy matrix.

Prepare a music attachment candidate from the exact reviewed vendor config:

```sh
python3 tools/configure_soundbooster.py \
    --effects build/samsung/lineage/audio_effects.xml \
    --output build/samsung/soundbooster-music-config-arm32
```

The output directory must not exist. This writes a candidate `audio_effects.xml`,
the byte-exact `audio_effects.original.xml` and a manifest of hashes/scope.
Unknown input configurations, prior attachment and output-directory reuse are
refused. The change declares one library/effect and a music postprocess apply;
all existing declarations, preprocessing and comments are preserved.

This is **not a ZIP or deployable bundle**: no binaries are included and the
test library still embeds temporary paths. Its intended library path is
`/vendor/lib/soundfx/libadaptive_soundbooster.so`, not `/vendor/lib64/`.
The default shared-runtime prototype requires NDK `libc++_shared.so`, absent
from the observed vendor library directory; existing `libc++.so` is not a drop-in replacement. Do not
rename libraries, overwrite the ROM's C++ runtime, or assume shell
`LD_LIBRARY_PATH` proves HIDL service/SELinux/linker compatibility.
The saved original XML is not a complete library/partition rollback procedure.

### Embedded C++ runtime experiment

Add `--static-runtime` to the effect-harness command to build a separate
embedded-runtime variant under `build/samsung/native-probe/ABI/static-runtime/`.
For example:

```sh
ANDROID_NDK_HOME=/path/to/android-ndk \
python3 tools/probe_soundbooster.py --abi armeabi-v7a --static-runtime \
    --effect-harness --aosp-include build/samsung/aosp-include \
    --vendor build/samsung/vendor --adb /path/to/adb \
    --serial YOUR_SERIAL --run-device \
    --output build/samsung/soundbooster-static-arm32.json
```

This option requires `--effect-harness`; ordinary direct probes retain the
shared runtime. Both bridge and harness link NDK libc++ statically. The bridge
version script exposes only `AELI`; all incorporated C++ symbols remain private.
The harness hides all static-library exports. Build inspection refuses
extra/missing exports or direct dependencies other than libc/libm/libdl/liblog.
No NDK shared runtime is transferred, and execution clears `LD_LIBRARY_PATH`
rather than adding the temporary directory.

The harness checks its process maps before loading the effect and after the
PCM matrices. Any `libc++_shared.so` mapping fails the embedded-runtime test.
The existing platform `libc++.so` is nevertheless mapped in the shell process;
its presence is recorded, not hidden. This proves removal of the direct NDK
shared-runtime dependency, **not** absence of every platform C++ runtime or
exclusive binding of all engine symbols to the embedded copy. Coexistence,
symbol interposition, HIDL linker namespaces and SELinux still need service
validation before installation. No ROM runtime is overwritten.

Every effect-harness build now derives a relocation fixture from the hash-pinned
original engine using NDK `llvm-readelf`. The fixture must include all reviewed
C++ ABI slots: 105 ARM32 slots across eight symbols, or 31 ARM64 slots across
five symbols. Unsupported relocation kinds, duplicates, misalignment and
missing slots are refused. The harness inspects the actual relocated pointers
in the loaded engine's readable ELF segments and uses `dladdr` to identify
their providers; this is not just a `dlsym` lookup or library-mapping inference.
The report records each symbol, provider class and slot count and validates
complete coverage against the fixture.

Observed in default embedded and shared builds: all those engine slots resolve to
the platform `/system/lib[64]/libc++.so`, not the adapter's embedded runtime.
This result describes the shell-process link graph only. Do not remove the
platform runtime or claim the HIDL vendor namespace will resolve the same way.
The report excludes addresses and arbitrary device paths. Default embedded
builds require platform providers; shared builds also permit the transferred
NDK provider. No embedded bridge C++ provider is accepted now that those
symbols are private.

### Installed vendor-runtime compatibility experiment

The service's vendor linker namespace searches vendor libraries and its ELF
declares `libc++.so`. The installed ARM32 vendor runtime matches the extracted
reference image at SHA256
`05b594f7ce7f249e743f2e170ebe844e157d9a5e016ffbadf657d6d6d59ed663`.
To test against that exact runtime rather than the shell's system copy:

```sh
ANDROID_NDK_HOME=/path/to/android-ndk \
python3 tools/probe_soundbooster.py --abi armeabi-v7a --static-runtime \
    --vendor-runtime --effect-harness --aosp-include build/samsung/aosp-include \
    --vendor build/samsung/vendor --adb /path/to/adb \
    --serial YOUR_SERIAL --run-device \
    --output build/samsung/soundbooster-vendor-runtime-arm32.json
```

`--vendor-runtime` requires the ARM32 embedded-runtime harness. Before any
temporary device directory is created, the launcher checks the installed
`/vendor/lib/libc++.so` hash and refuses mismatches. It runs only the test process
with that installed file in `LD_PRELOAD` and an empty `LD_LIBRARY_PATH`.
No runtime is copied, modified or globally preloaded. Other experiments
explicitly clear `LD_PRELOAD`.

The entire PCM/lifecycle matrix must pass with all 105 reviewed engine C++
slots resolving to the vendor runtime. A system/NDK/embedded fallback, absent
vendor mapping or any system libc++ mapping fails the evidence validation.
This tests binary compatibility and actual relocation provenance with the
installed vendor C++ runtime, **not** the real service namespace, SELinux
domain, automatic effect attachment or Dolby coexistence. The C++ export
restriction to `AELI` is regressed in both default embedded ABIs and this
vendor-runtime mode; no ROM runtime is replaced.

Any eventual distributed binary must also include the applicable NDK runtime
license notices; this experiment does not package or distribute a ZIP.

### Offline SoundBooster filesystem staging (not an installer)

After building host tools, the following command builds the stripped ARM32 bridge
with persistent vendor paths and reconstructs an EROFS filesystem locally:

```sh
python3 tools/stage_soundbooster.py \
  --image build/reference-vendor.img \
  --vendor build/samsung/vendor \
  --ndk "$ANDROID_NDK_HOME" \
  --speaker-attenuation-mb 1100 \
  --output build/samsung/soundbooster-filesystem-review
```

The output directory must not exist. No device is accessed. All original files,
ownership, modes, timestamps, SELinux xattrs, symlinks and hardlink groups are
audited. Only the effect XML and the two speaker policies change; the three
SoundBooster files are added. Speaker attenuation remains -11 dB; Dolby XML is
reference-original, without the experimental EQ. Static harness builds use the
same stripping and section-garbage-collection flags as this bridge.

The current reference produces a **159,551,488-byte filesystem**, compared with
159,375,360 original data bytes in the 162,500,608-byte partition image.
The command saves the full audit and `result.json`, then **exits with an error**
because the candidate would overlap the original AVB region by 176,128 bytes.
It deliberately does not produce a vendor partition image or a ZIP.

The apparent partition padding is not free space: the original footer describes
a SHA-1 hashtree and two-root FEC, unsigned VBMeta (`NONE`), and flags zero.
Moving that region requires properly regenerating and verifying it, not
truncating it or setting verification-disabled flags. Fitting in the raw partition size alone is not an installation safety check.
Actual vendor-namespace/SELinux loading and automatic music attachment remain
unverified; do not flash the standalone filesystem.

#### Optional local AVB/FEC and rollback proof

Add `--prepare-partition` to the staging command, using a fresh output directory,
to regenerate the original verification metadata after the full filesystem
audit. It creates `partition/vendor.img`, an offline block bundle, and a separate
`partition/result.json`. These are **not recovery-installable packages**.
The host build now provides an encode-only `fec` frontend using the original
Android `init_rs_char`/`encode_rs_char` codec, with the original field polynomial,
two roots, interleaving and footer format. It accepts only raw regular files
up to 1 GiB and supports neither sparse images nor decoding. The upstream codec
is LGPL-licensed; its pinned sources and notices remain in ignored
`third-party/fec-90857de`. It is linked only into the local host tool, not into
the Android adapter or existing recovery ZIPs.

Before creating the candidate, regeneration must reproduce **every byte** of
the exact reference partition, including its SHA-1 tree, FEC and footer.
The candidate retains the same `NONE` algorithm, zero flags, salt, rollback
indices, properties and partition size. No signing key is replaced and no
verification-disable flag is set. `avbtool verify_image` checks the hashtree;
the tool separately regenerates and compares all FEC bytes, since `avbtool`
does not validate FEC parity itself.

The verified maximum filesystem size with unchanged AVB/FEC settings is
159,854,592 bytes. The 159,551,488-byte candidate therefore fits, leaving
303,104 bytes under that conservative maximum. The completed partition remains
exactly 162,500,608 bytes.

`offline-reversible-blocks.zip` contains changed original/candidate blocks and
per-block/whole-image hashes, **not an Android update-binary or installer**.
Local simulation verifies exact apply/restore, repeated application, recovery
from a mixture of whole original/candidate blocks, and rejection of an unknown
block before any writes. Torn/partially written blocks are deliberately refused,
not silently guessed or repaired. All simulations operate on disposable regular
files; the archive has not been executed in recovery. A safe real installer and
actual installed-partition identity checks are still required.

#### Private experimental recovery packages

After the recovery read-only preflight identifies the exact installed vendor
and the native recovery tool is rebuilt, generate a separate package set:

```sh
python3 tools/package_soundbooster.py --profile initial \
  --original build/reference-vendor.img \
  --live build/samsung/lineage/recovery-live-vendor.img \
  --candidate build/samsung/soundbooster-reversible-review/partition/vendor.img \
  --output dist/soundbooster-experimental
```

The output directory must not exist. This packager pins all three complete
image identities, not just selected XML files. It writes separate preflight,
install and original-reference restore ZIPs, SHA256 sums, a manifest and
`blocks.bin`. It does not modify existing XML-only packages or access a device.
The block bundle carries three states: reference, inspected live preset and
SoundBooster. The native streaming engine verifies the bundle digest, all block
payloads, all three reconstructed full-image hashes, boot compatibility, actual
vendor mapping and mount state before any write. Native apply refuses mixtures;
restore accepts known whole-block mixtures and returns to the exact reference.
Unknown/torn blocks are always refused.

This is a broad vendor reconstruction, private and experimental; the packages
include proprietary original/candidate blocks and must not be published.
Recovery RAM-only native execution and real-vendor read-only preflight are
separate gates from installing/booting the effect. Do not flash automatically.
See [installation limits](INSTALL.md#experimental-native-soundbooster-packages).

The first installed bridge rejected HIDL's PCM configuration mask `0x1e`
because it required the obsolete buffer bit (`0x1f`). The corrected bridge
accepts exactly these two masks and supports the canonical `EFFECT_CMD_DUMP`
command with processing/bypass counters. ARM32 vendor-runtime and ARM64 native
tests cover the correction, including PCM16/float accumulation.
Generate the separately pinned migration from the first SoundBooster image:

```sh
python3 tools/package_soundbooster.py --profile hidl-fix \
  --original build/reference-vendor.img \
  --live build/samsung/soundbooster-reversible-review/partition/vendor.img \
  --candidate build/samsung/soundbooster-hidl-fix/partition/vendor.img \
  --output dist/soundbooster-hidl-fix
```

Keep the initial artifacts unchanged. Use the matching `hidl-fix` restore;
the initial bundle does not recognize the corrected image. The corrected image
has passed real recovery write/read-back and Android boot; active music
processing is a separate verification gate.

The active-service trial then exposed a second issue: the original ARM32 engine
has unresolved C++ ABI imports but no `DT_NEEDED` for libc++. Preloading vendor
libc++ in a shell had hidden that omission. The `runtime-fix` build gives the
bridge two explicit absolute dependencies, the unchanged engine and the existing
hash-checked `/vendor/lib/libc++.so`, in one local dependency group. Linking only
libc++ to the bridge is insufficient for a subsequently `dlopen`-loaded engine.
Link-only import stubs carry those dependency names; they are not installed.
No runtime exports, global preload, namespace weakening or platform library
replacement is added.

The regression now creates an isolated Android namespace with vendor library
search and only libc/libm/libdl/liblog linked from the system namespace. The
unmodified bridge reproduces `-22`/`__cxa_call_unexpected`; the linked bridge
processes 1024 synthetic float frames with zero bypass. The full ARM32 matrix
also checks all 105 C++ relocation slots against the vendor runtime.

```sh
python3 tools/probe_soundbooster.py \
  --abi armeabi-v7a --static-runtime --effect-harness --vendor-search-path \
  --linked-vendor-runtime build/samsung/lineage/libc++.so \
  --aosp-include build/samsung/aosp-include --vendor build/samsung/vendor \
  --ndk "$ANDROID_NDK_HOME" --adb adb --serial YOUR_SERIAL --run-device \
  --output build/samsung/lineage/soundbooster-linked-runtime.json

python3 tools/stage_soundbooster.py \
  --image build/reference-vendor.img --vendor build/samsung/vendor \
  --ndk "$ANDROID_NDK_HOME" --speaker-attenuation-mb 1100 \
  --output build/samsung/soundbooster-runtime-fix \
  --prepare-partition

python3 tools/package_soundbooster.py --profile runtime-fix \
  --original build/reference-vendor.img \
  --live build/samsung/soundbooster-hidl-fix/partition/vendor.img \
  --candidate build/samsung/soundbooster-runtime-fix/partition/vendor.img \
  --output dist/soundbooster-runtime-fix
```

The local runtime input to the probe must be extracted unchanged from the
reviewed reference image (`/lib/libc++.so`), SHA256
`05b594f7ce7f249e743f2e170ebe844e157d9a5e016ffbadf657d6d6d59ed663`.
Staging extracts and checks it automatically. All output directories must be new.
The isolated regression is still not proof of actual audio-service processing:
install/read-back, boot and increasing live playback counters remain required.
Use only the matching `runtime-fix` restore after this migration.

#### Private SoundBooster -9 dB comparison

The historical baseline is -11 dB. The `minus9` transition raises every
covered speaker curve by exactly 200 millibels relative to `runtime-fix`;
SoundBooster binaries/parameters, effects XML, Dolby and all other filesystem
contents/metadata are unchanged. Non-speaker curves remain original.

```sh
python3 tools/stage_soundbooster.py \
  --image build/reference-vendor.img --vendor build/samsung/vendor \
  --ndk "$ANDROID_NDK_HOME" --speaker-attenuation-mb 900 \
  --output build/samsung/soundbooster-minus9 --prepare-partition

python3 tools/package_soundbooster.py --profile minus9 \
  --original build/reference-vendor.img \
  --live build/samsung/soundbooster-runtime-fix/partition/vendor.img \
  --candidate build/samsung/soundbooster-minus9/partition/vendor.img \
  --output dist/soundbooster-minus9

python3 tools/package_soundbooster.py --profile return-minus11 \
  --original build/reference-vendor.img \
  --live build/samsung/soundbooster-minus9/partition/vendor.img \
  --candidate build/samsung/soundbooster-runtime-fix/partition/vendor.img \
  --output dist/soundbooster-return-minus11
```

The **install** ZIP in `soundbooster-return-minus11` returns to the exact
working SoundBooster -11 dB image. It is not the **restore** ZIP: restore in
either set still returns to the full reference ROM, removing SoundBooster
and attenuation. Do not mix these operations or use old restore sets on -9 dB.
All image identities are pinned; no arbitrary attenuation/hash override is
accepted. New complete images retain the audited original AVB/FEC policy.

For the further **-7 dB** comparison, use `--speaker-attenuation-mb 700`
and a new staging directory `build/samsung/soundbooster-minus7`.
Package with `--profile minus7`, `--live` pointing to the -9 dB partition,
`--candidate` to the -7 dB partition and output `dist/soundbooster-minus7`.
Generate `--profile return-minus9` with those two images reversed and output
`dist/soundbooster-return-minus9`. Its **install** returns to SoundBooster
-9 dB; **restore** still returns to the full reference ROM. Only the two
speaker policy files differ from the -9 dB image; the selected final is -7 dB.
This adds another 2 dB on covered speaker curves, including alarms/notifications.
Do not infer speaker protection or distortion-free playback from policy checks.

## Reproducibility limits

Dependency revisions, source/archive checksums, ROM and XML identities are
pinned. This is not a claim of byte-for-byte reproducible ZIPs across hosts:
ZIP timestamps, compiler versions and compression implementations may differ.
Trust comes from input checks, tests and read-back verification, not a universal
prepublished hash for everyone's locally generated build.

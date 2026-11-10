# Evidence and test limits

## Final selected configuration

The selected final is **SoundBooster + original Dolby, -7 dB speaker policies**.
Recovery returned status 0 and independent full vendor read-back matched
`20eb8ae447797bbb386127c2010aa0610a698f2bd2271d15bf69ce93345674c8`.
Android boots and both installed policy hashes match the final image.

Subsequent real speaker playback verifies SoundBooster status 0,
configured/enabled, stereo float at 48000 Hz, route `0x2`, HIDL masks 30.
Two snapshots show **6772800 -> 6970560 frames**, zero bypass.
The user selected this version after listening. This is not a calibrated
distortion test, Samsung acoustic equivalence, all-route coverage or an OTA test.

The final local set is `dist/soundbooster-final`: preflight/install/restore ZIPs
and their manifest/checksums. Old distribution variants are removed; local
firmware inputs and evidence remain ignored for reproducibility. The final
profile accepts only reference, reviewed previous -9 dB or final -7 dB images.
All **77 private tests pass**; public firmware-free tests pass 71 and skip six.

The sections below preserve chronological evidence, including earlier failures.
They are not the current selected preset or a claim that those failures persist.

## Initial device observation

One SM-P610 / gta4xlwifi running official
`23.2-20261107-NIGHTLY-gta4xlwifi`. The user reported louder, poorer speaker
audio and crackling. The exact cause and stock signal chain were not proven.
The preset is experimental, not extracted/verified stock Samsung calibration.

## Validation matrix

| Surface | Evidence | Limitation |
|---|---|---|
| First full-image prototype | Actual vendor install, read-back, Android boot, three XML hashes | Old build-specific installer, not the public adaptive write path |
| Runtime policy after prototype | 12 configured speaker groups exactly -600 millibels, 63 remaining curves unchanged | Internal groups excluded; not an acoustic dB measurement |
| Listening | User reported improved sound, lower volume, no crackling on tested material | One listener/device; no calibrated measurement or universal protection |
| Global effects | Wavelet force-stopped, Dynamics Processing absent, DAX3 present | Effective Dolby EQ transfer function/profile behavior not measured |
| Adaptive native tests | Regular-file apply/restore, idempotency, different offsets, invalid inputs, backup failures | Synthetic layout variants are not real future nightlies |
| Adaptive ARM64 tool | File-image preflight/apply/reapply/restore on tablet, exact original SHA256 restored | No raw-device writes in this test |
| Adaptive recovery ZIP | Preflight and apply accepted, preset already present, boot and hashes/curves unchanged | Real-device write/restore from an untouched vendor not performed |
| Future OTA | Compatibility logic and image-identity tests | No actual later nightly installed as part of testing |
| Other routes | Non-speaker XML/runtime curves preserved | No complete physical headphone/Bluetooth/profile test matrix |

Do not describe the adaptive installer as fully OTA-validated or promise
stock-identical volume/EQ.

## Public tests

```sh
python3 tools/fetch_sources.py
python3 tools/build_tools.py --host-only
python3 -m unittest discover -s tests -v
```

All fixtures are generated locally from project-authored synthetic XML/cpio,
without firmware. Tests operate only on temporary regular files. Cases include:

- No writes/backups in preflight.
- Exact patched template contents and idempotent reapplication.
- Full-image identity preserved by restore, including unrelated changes.
- Dynamic offsets on newly generated EROFS.
- Refusal to restore onto a different image.
- Recovery of an interrupted write within a saved cluster.
- Unknown XML, bad backup, missing backup storage, non-EROFS, wrong target type.
- Known-answer SHA256 and LZ4 round-trip.
- Boot parsing and refusal of a vendor AVB-enabled fixture.
- Edify wrapper device/version/read-only-mount guards.
- Backup-free replacement/reset, previous-preset migration and mixed-preset refusal.

The current ZIPs use backup-free `replace`/`reset`. Legacy `apply`/`restore`
backup tests remain for compatibility. Private reference tests also verify
previous-preset replacement, idempotency and exact decoded original XML reset.
Recompressed original clusters need not match the ROM's compressed bytes.
No new raw-device success is implied by these file-image tests.
The targeted bass revision checks exact changes only at 141, 234 and 328 Hz,
unchanged other bands/volume curves, and migration from the restored-treble
-11 dB preset. Its acoustic response and distortion have not been measured.

The optional Samsung Dolby baseline has synthetic tests for installation
from original/custom XML, exact original Dolby bytes, unchanged -11 dB policy
templates, idempotency, reset and switching back to custom. Packaging rejects
unknown Samsung Dolby hashes. The private reference check accepts an explicit
baseline stage and verifies the installed Dolby bytes against the reviewed
local Samsung extraction. This does not validate SoundBooster, One UI runtime
mode selection, physical speaker response or baseline raw-device installation.

Local baseline validation completed: 27 tests passed; host and ARM64 builds
passed; both custom and baseline private reference-image checks passed.
All three baseline archives passed CRC/SHA256 checks, exact target-template
and ARM64 executable checks, and absence-of-Samsung-DSP-binaries checks.
The existing custom install ZIP was confirmed unchanged byte-for-byte.
The baseline ZIP has **not** been installed or listened to on the tablet.

## Read-only SoundBooster AMF verification

The analysis tools add six synthetic tests: strict complete record schema,
duplicate/missing/malformed records, firmware-identity refusal, disabled-bank
handling, unsupported enable/type refusal, peaking center/end-point response,
stable coefficients, bandwidth interpretation and explicit incomplete-DSP scope.
The complete suite passed **33 tests** after these additions.

Local Unicorn 2.1.4 emulation of the reviewed engine's coefficient function
checked all 32 filters in enabled parameter banks. Maximum absolute coefficient
error versus the floating model was `2.287785456633884e-7`.
Maximum single-filter response error on the 20 analysis frequencies plus
each filter center was `0.003730173878964904 dB`; maximum summed-bank error
on the 20 analysis frequencies was `0.003447929985269993 dB`.
The verifier enforces coefficient error <= `2e-6` and both response errors
<= `0.02 dB`. These are **sampled static-model checks**, not continuous-band
error bounds, bit-exact processing or a test of the complete engine.

The AA/AC static response is about +4.25 dB at 141 Hz; BA/BC reaches about
+12.44 dB at the sampled 11250 Hz point. This is not a recommendation to
apply those gains: HPF, gain scaling, DRC and runtime control are excluded.
No new SoundBooster device preset was generated or installed.

## Read-only SoundBooster control and HPF verification

The complete public suite now discovers **40 tests: 36 passed and four
optional private tests skipped** without firmware/Unicorn. The SoundBooster
module contains nine public tests and four optional private tests; all 13
passed with the reviewed local vendor extraction and Unicorn 2.1.4.
The complete suite also passed **all 40 tests** with those optional inputs enabled.
The extra public cases check AMF ABI packing, unsupported mode refusal and
conditional fourth-order HPF response/invalid inputs. Engine-hash refusal is
also tested before the optional emulator is imported.

The private checks execute original instructions for:

- Conditional group A/B forwarding in explicitly selected Music/Legacy modes.
- First/second AMF bank selection using deliberately distinct synthetic markers.
- Stored volume clamp boundaries, including signed 32-bit extremes.
- Enabled Legacy DRC forwarding of four 12-element arrays and downstream
  controls, including correct signed register arguments.
- Invalid Legacy DRC fields resetting to zero rather than saturating.
- Both reviewed HPF coefficient responses versus a fourth-order Butterworth
  model on the 20 analysis frequencies plus cutoff/half-cutoff/twice-cutoff.

Maximum sampled HPF error was `0.001195422789518119 dB` at 75 Hz cutoff and
`0.0003521814347706709 dB` at 100 Hz cutoff, below the enforced `0.02 dB`
limit. Original coefficients give about -3.01064 dB at the 75 Hz cutoff.
This confirms conditional HPF order/response, not continuous-band error bounds,
bit-exact processing or whether One UI actually enables it on a given route.

Control traces use zeroed synthetic format fields, null gain-scaler objects
and explicit mode choices. They do not measure effective gain, reproduce
compression/envelopes, validate stock runtime control sequences or establish
physical channel assignment. The default-mode interpretation is corrected to
**2 = Legacy, 1 = Music, 0 = Lite**; initialization data may override the default.
See [BUILD.md](BUILD.md#read-only-soundbooster-amf-analysis) for reproducible
commands. No ZIP was regenerated or installed for this analysis.

### Compression-backend follow-up

The expanded suite discovers **43 tests**: 37 public tests and six optional
private tests. With local reviewed firmware/Unicorn, all 43 pass.
The SoundBooster module contains ten public and six private tests.

Original-instruction tests verify the reviewed 12-control split into
11 FILX / 3 EMQF internal slots with explicit zero padding, and execute
the original gain-curve generator rather than stubbing it. Backend tests
cover gains -30, -6, 0, 3, 4, 5 and 30 dB, thresholds -30, -12 and 0 dB,
time values 0, 1 and 2000 ms and synthetic frame sizes 512/1024 at 48000 Hz.
All generated mode-2 curve records match the independent model exactly.
Gain and threshold amplitude conversions plus timing coefficients are
checked within integer tolerances (1 unit, except EMQF Q23 threshold: 2);
the actual reviewed group A/B controls match with zero integer error.
An independent public test checks monotonic curve coordinates over all
61 integer gain values times 31 integer thresholds in the accepted range.

This is not a full compressor waveform test: frequency-band assignment,
envelope application, transient limiting and the stock FFT runtime context
are still unverified. Read-only tablet inspection also confirms that direct
stock-wrapper installation needs absent Samsung libraries; no loadability,
playback or compatibility success is claimed. Existing ZIP checksums and
device configuration are preserved.

## Native engine PCM experiment

Three additional public tests validate the native payload ABI/identity guard,
exact tone matrix and RMS measurements, and rejection of malformed reports,
non-silent silence, out-of-bounds/clipped/empty output and absent nonlinear
behavior. Total suite: **46 tests**, with six optional private tests.

The separate opt-in native probe was compiled with the installed NDK using
`-Wall -Wextra -Werror` and executed on the connected Lineage tablet. Both
explicit engine modes passed all 15 cases each: silence plus four frequencies
at three levels. No measured sample reached PCM16 clipping in this matrix.
Every processing call returned 256 frames and output-buffer canaries remained
intact. On-device SHA256 checks validated all four transferred files;
temporary files/directories were removed. The existing AudioFlinger chain
still reported DAX3, with no SoundBooster effect added.

This test executes real engine initialization, parameter application, PCM
processing and destruction, not stub DSP dependencies. It remains a shell
process experiment: no audible output, stock wrapper, audio-service loading,
route-specific activation, complete latency/distortion measurements or
faithful One UI runtime control are validated. The reviewed binary itself
is not proven memory-safe by the output canaries. See
[BUILD.md](BUILD.md#optional-native-soundbooster-engine-probe) for exact scope,
opt-in commands and cleanup limitations.

## Experimental effect-adapter verification

Two more public tests validate the adapter report matrix/scope and original
AOSP effect-header identity refusal. Total suite: **48 tests** (42 public,
six optional private). With the reviewed firmware and emulator, all 48 pass.

The separate Android adapter harness compiles with warnings as errors and
original AOSP Android 16 headers, comparing API sizes, offsets and constants
independently of the project's ABI declarations. It loads the experimental
shared object in a shell process on the tablet, not AudioFlinger.

The harness checks factory/descriptor identity, modified-payload hash refusal,
invalid/null commands, missing replies, unsupported formats/rates/channel
layouts/access modes, rejected active reconfiguration, configuration readback,
enable/disable/reset, malformed process buffers and volume bounds.
Non-speaker masks (unknown, wired, Bluetooth, USB and mixed) must produce
byte-identical bypass. Speaker processing at zero/quarter/unity volume
indication and block sizes 48/96/256/1024, plus in-place PCM processing,
must match a separate direct-engine instance sample for sample across
**137472 frames** (68864 PCM16 and 68608 native float).
Output canaries must remain unchanged. Float NaN, infinity and samples outside
[-1,1] must be rejected before modifying output; non-speaker float bypass must
remain byte-identical even for NaN, infinity and signed zero. Switching between PCM16 and float while disabled creates a
fresh appropriately configured engine.

The harness measures 192 WRITE processing calls per format. In the reviewed device
run, median/p99/max elapsed time divided by the respective block's audio period
was 0.0394/0.3844/0.4360 for PCM16 and 0.0395/0.2336/0.2343 for float.
The report validates finite positive ordered timing measurements and separately
records whether p99 was below one period. A slow run is reported as slow, not
silently treated as real-time success. Unit tests cover malformed measurements
and the slow-run flag. Results include shell scheduling noise, limited synthetic
inputs and no concurrent service workload; they are not latency guarantees.

ACCUMULATE has an additional **1060032 frames** of exact comparisons (530016
per format). Block sizes 1/48/96/256/1024/4096 exercise both scratch-buffer
boundaries, three volume indications and separate/exactly aliased buffers.
The expected output is independently processed native-engine PCM plus the
original destination, with PCM16 saturation and unclipped float addition.
Tests assert unchanged READ inputs and output canaries, speaker/non-speaker
and disabled accumulation, both saturation limits, float headroom, invalid
input/destination values and overflow refusal without partially modifying output.
The report requires both matrices and at least 7000 checks; an old WRITE-only
report is rejected rather than accepted as evidence of chain compatibility.

The adapter test passes these checks, including explicit original-header ABI
verification. Its dependencies do not include the incompatible Samsung wrapper
or Samsung feature libraries. Device temporary files are removed and existing
installed audio XML hashes and ZIP checksums remain unchanged.

This is not an audio-service integration or listening test. Both PCM16 and
float pass in isolation; the tablet exposes both kinds of processing thread.
Real routing/volume delivery, service linker compatibility, all lifecycle
sequences, latency, thread-contention behavior, distortion/protection, Dolby
coexistence and a reversible installation mechanism remain unverified.
There is **no installable SoundBooster ZIP** in this experiment.
The ADB shell lacks privileged deployment access and vendor is read-only EROFS;
system activation needs a separately validated reversible recovery/root or ROM
integration path. No root/remount, reboot or partition write is attempted by
these tests.

### Service-ABI and attachment-candidate checks

The reference service is ARM32, not ARM64. The same 7132-check adapter matrix
passes using **each** ABI and its original engine, with independent original
AOSP header assertions. Each report includes actual pointer width; mismatches
against the selected ABI are rejected. Comparisons are against the matching
native engine, not a claim that ARM32 and ARM64 produce identical DSP samples.
The direct ARM32 Music/Legacy 30-case matrix also passes.

Three new public tests validate the configuration generator's exact structural
delta, preservation of existing nodes/comments, strict input identity,
rejection of existing attachments, original XML rollback bytes, manifest
hashes/scope and refusal to overwrite outputs. Generation with the actual
reviewed/live-matching configuration succeeds. The generated candidate is not
installed and is not a full deployment rollback.

Current total: **51 tests**, all passing with private firmware/emulator;
without private inputs, 45 pass and six explicitly skip. Run the bounded private
emulator suite without concurrent compiler load; an instruction/time-budget
timeout during a parallel run disappeared on the isolated rerun, without
relaxing any bound.

### Embedded-runtime verification

An additional public test enforces the static build's exact export set for
ARM32/ARM64, an empty harness export set and allowed direct system-library
dependencies. Extra exports, leaked harness C++ symbols, missing required
exports and NDK/platform shared-C++ direct dependencies are refused.
Report tests additionally require the selected shared/embedded mode to match
the observed NDK runtime-absence flag and require explicit platform-mapping
evidence.

Both embedded-runtime device harnesses pass the same **1197504-frame** matrices
and original AOSP ABI assertions. Additional process-map checks increase the
check count beyond the shared-runtime baseline; the count depends on mappings,
not on a different PCM matrix. There is no `libc++_shared.so` transfer or mapping
and `LD_LIBRARY_PATH` is cleared for execution. The adapter's ELF needs only
libc/libm/libdl/liblog, and the harness exports no dynamic definitions.
An existing platform `libc++.so` is mapped and reported as present: these tests
do not establish exclusive engine symbol binding or absence of C++ interposition
inside the actual service.

Current total: **52 tests**, all passing with private inputs; public-only runs
pass 46 and explicitly skip six private cases. Embedded/shared builds retain
separate directories, and both original shared-runtime ABIs are regressed.

### Actual engine C++ relocation-provider verification

Two further public tests validate relocation-fixture extraction and runtime
binding evidence. They require exact reviewed per-symbol counts and reject
missing/duplicate/misaligned slots, unknown relocation types, malformed or
duplicate records, incomplete counts and providers inappropriate for the
selected shared/embedded experiment.

All four device variants (ARM32/ARM64, shared/embedded) pass the same
1197504-frame matrices and additionally inspect **105 ARM32 / 31 ARM64**
loaded relocation slots, covering eight/five reviewed C++ ABI symbols.
All observed providers are the platform libc++ image. This is measured from
the actual relocation targets, not inferred from loaded-library names.
Inspection verifies readable ELF segment bounds and consistent providers
across repeated references. No engine memory is written by this inspection.

Current total: **54 tests** with private inputs; public-only runs pass 48 and
skip six. Device XML hashes, existing ZIPs, DAX-only service state and exact
temporary-file cleanup remain separate required checks. None of these tests
activates SoundBooster or establishes service-namespace compatibility.

### Installed vendor C++ runtime verification

The ARM32 embedded-runtime harness also passes with the installed,
hash-pinned `/vendor/lib/libc++.so` preloaded only into its test process.
All 105 checked engine C++ slots must point to `vendor_cpp`; system fallback
is a failure, even if PCM processing otherwise succeeds. Runtime maps must
show vendor libc++ present, system libc++ absent and no NDK shared runtime.
The same 1197504-frame comparisons, buffer checks, configuration/lifecycle
tests and original AOSP assertions pass in this mode.

The embedded adapter now exports **only `AELI`**. Both default embedded ABIs
and the vendor-runtime experiment pass with all C++ exports hidden, avoiding
an additional public C++ ABI surface alongside the other effects. Existing
shared-runtime tests remain covered separately.

One new public test requires the exact installed vendor-runtime hash and path,
rejecting absent/incorrect hashes, substituted system paths and multiple
results. Expanded existing tests reject vendor-map absence, system-map
presence, wrong experiment mode and mixed/fallback engine providers.
Including the offline checks below, current total: **77 tests** with private inputs;
public-only runs pass 71 and
explicitly skip six. This remains a shell-process compatibility experiment,
not actual HIDL service activation.

The complete private 75-test suite passes after the HIDL correction. Native
ARM32 vendor-runtime and ARM64 harnesses cover masks `0x1e`/`0x1f`, invalid
masks, PCM16/float accumulation, and validated DUMP diagnostics/counters.
The first device installation attached SoundBooster but returned status `-22`:
HIDL omits the obsolete buffer mask bit. Its `-38` diagnostic was the unhandled
`EFFECT_CMD_DUMP`, not proof of an engine processing failure.
The corrected migration installs with recovery status 0 and independently
verified whole-vendor hash
`35472c09cae0800bf611cf690a35687625fc8c03db91a89c742fc854f64f9d1c`.
Android boots, audioserver runs, and -11 dB policies plus original Dolby hashes
remain correct. The user is still `RUNNING_LOCKED` with no active music session;
increasing real-service processing counters remained unverified until unlock/playback.

The subsequent active Spotify session 105 still returns effect status `-22`:
both consecutive dumps report `configured=0 enabled=0 processed_frames=0`.
Real vendor-service logs identify the next failure as `dlopen` refusing the
original engine because `__cxa_call_unexpected` cannot be resolved. The successful
shell vendor-runtime harness therefore does not prove service linker-namespace
compatibility. The HIDL mask correction is installed but processing is not working.

The runtime-linked candidate now passes an isolated Android vendor-namespace
regression without preload or search-path overrides in that loader process:
1024 float frames processed, zero bypass, HIDL mask 30. The same regression
rejects the unlinked bridge with the observed unresolved-symbol error. A
separate full ARM32 matrix uses vendor library search paths, no preload, and
verifies all 105 engine C++ relocation slots bind to the installed vendor runtime,
with no system or NDK shared runtime mappings. Its bridge exports only `AELI`.
The 76-test private suite passes, including exact dependency-group and migration
pins. These tests do not yet establish processing in the running audio service.

After sideloading `runtime-fix`, the user rebooted before recovery log/raw vendor
read-back could be captured. Android boots with audioserver running. Actual
Spotify speaker session 121 now reports status 0, configured/enabled, route
`0x2`, stereo float 48000 Hz, masks `0x1e`. Consecutive dumps show
`processed_frames` increasing from **1287360 to 1532160** (244800 frames),
with `bypassed_frames=0` in both. Dolby is concurrently status 0, float 48 kHz.
The -11 dB policy and original Dolby hashes match; crash and bridge-error logs
are empty at the check. This verifies real service processing, not acoustic
equivalence, all-route behavior, or the latest whole-partition identity.
Evidence is saved locally in `build/samsung/lineage/soundbooster-runtime-fix-active-{1,2}.txt`
and `soundbooster-runtime-fix-deployment.json`.

The separate -9 dB candidate passes the full private 77-test suite. Its complete
filesystem manifest differs from working `runtime-fix` only in the two volume
policy files: every other decoded file and its metadata, including bridge,
engine, parameters, effects XML and Dolby, is unchanged. Exact curves validate
against reference with 900 millibels attenuation; the synthetic test checks a
200-millibel increase from -11 dB and unchanged non-speaker endpoints.
Original AVB/FEC regeneration and verification pass at unchanged partition size.
Full-size native tests verify both `minus9` and `return-minus11` install targets,
idempotence, exact-reference restore, known mixed-block restore and unknown-block
refusal without writes. ZIP hashes are independently checked. This -9 dB version
has now been installed: recovery status 0 and independent whole-vendor read-back
match `f88c8b012381b10e86cb94333fc4b223287946c956483255fef0119646a2c943`.
Android boot completes with audioserver running, the two -9 dB policy hashes
match the audited image and original Dolby is unchanged. Crash and bridge-error
logs are empty at the check. Subsequent active Spotify speaker session 113
verifies status 0, configured/enabled, stereo float 48 kHz, processing frames
1456320 -> 1701120 (244800 additional), and zero bypass. The active track reports
-9 dB port volume; concurrent Dolby status is 0 and policy hashes still match.
This confirms live processing with -9 dB policies, not absence of acoustic
distortion or equivalence to Samsung stock audio.

The further -7 dB candidate passes the same 77-test suite with explicit
700/900/1100-millibel coverage. The complete filesystem comparison against -9 dB
changes only the two policy files; all SoundBooster/Dolby payloads and unrelated
metadata are unchanged. Exact 700-millibel curves and original AVB/FEC policy
validate. Full-size native tests verify `minus7` and `return-minus9` install
targets, idempotence, exact-reference restore, known mixtures and unknown-block
refusal. ZIP hashes match. The -7 dB image is now installed: recovery status 0
and independent full vendor SHA256 match
`20eb8ae447797bbb386127c2010aa0610a698f2bd2271d15bf69ce93345674c8`.
Android boot completes with audioserver running, both -7 dB policy hashes match
the audited image and original Dolby is unchanged. No crash/bridge errors at
the check. Later speaker playback verified 6772800 -> 6970560 processed frames,
zero bypass, configured/enabled, status 0, stereo float 48 kHz. The user selected
this -7 dB configuration as final after listening.

### Offline EROFS integration audit

`tests/test_soundbooster_stage.py` checks exact allowed file changes, payload
hashes/sizes, donor security labels and permissions, original hardlink topology,
unsafe/duplicate paths and malformed filesystem geometry. Its synthetic
full-archive round trip uses the host EROFS tools, including decoded symlink
contents, hardlinks, uid/gid, modes, timestamps and SELinux xattrs. Invalid images
must produce an audit failure, not a partial successful manifest.

The private reference audit preserves all 951 original entries and adds exactly
three ARM32 SoundBooster files. All original contents and metadata remain exact
except the reviewed effects XML, two -11 dB speaker policies and directory
sizes/inode locations. Original Dolby configuration and EROFS feature flags
remain unchanged. The stripped persistent-path bridge exports only `AELI`.
The 159,551,488-byte filesystem passes full decoding/fsck but exceeds the original
data region by 176,128 bytes. Staging therefore fails its conservative capacity
gate after saving the audit; it creates no deployable partition image.

Incremental staging was rejected: it appended after the partition image and
changed original directory ownership, timestamps and labels. Full reconstruction
from a metadata-preserving tar fixes those filesystem invariants. The optional
AVB/FEC follow-up below resolves the data-region overlap without changing
partition size or verification policy.
No partition writes, reboot, SELinux changes or new ZIP installation were made.

### AVB/FEC regeneration and offline reversible-block proof

Seven new tests cover:

- Independent Reed-Solomon syndrome checks for both original field roots,
  including the 253-to-254-block round boundary; exact FEC sizes/footer/hash.
- Rejection of malformed, unaligned, oversized, aliased or symlinked inputs,
  unsupported roots and decoding, without truncating the source.
- Local block-delta application, restoration, mixed whole-block restoration,
  idempotence, and unknown unchanged-block refusal before writes.
- Corrupt delta payloads, untrusted whole-image identities, geometry and symlinks.
- Independent hashtree and FEC corruption failures, pinned AVB source identity,
  and rejection of verification-disable flags.

The private run reproduced the complete 162,500,608-byte reference partition
byte-for-byte, SHA256
`278862bb89de2057e6fb78b9fd19bb5840762369ad7752cc02a0b49960d9beea`.
The candidate is also 162,500,608 bytes, with original AVB settings and verified
tree/parity. Its filesystem remains byte-identical to the audited EROFS output.
The AVB maximum data size is 159,854,592 bytes, 303,104 more than the candidate.

The local reversible bundle covers 39,547 changed 4096-byte blocks. It restores
the exact reference hash after a full apply and after simulated interruption
between whole-block writes. Unknown/torn blocks are refused without writes.
This proves only the host regular-file mechanism, not recovery execution,
power-loss safety, or compatibility with the actual installed custom vendor.
This offline block archive is not the separately generated recovery ZIP set.
Real SoundBooster service activation is still unverified.

### Guarded native recovery block engine and package checks

Seven new synthetic tests exercise all three accepted whole-image states,
preflight without writes, apply/reapply, restore to reference, mixed-state
install refusal and mixed-state restore. Corrupt payloads/bundle digests,
incorrect full-image hashes, unknown/torn changed or unchanged blocks, boot
AVB flags, missing acknowledgement, wrong target type, symlinks, size mismatch
and trailing data must fail before writes. Package scripts must select the
logical vendor mapping, the correct operation, explicit warnings and no reboot.
Unreviewed source images cannot create package output.

The full-size native host experiment applies the reviewed candidate from the
actual recovery-read vendor, verifies idempotence, restores the exact original
reference hash, and restores from a known mixture of live/candidate blocks.
The same ARM64 static native executable also passes preflight/apply/reapply/
restore in real recovery using tiny synthetic regular files under `/tmp` only.
Transfers and resulting hashes are checked and the fixture is removed.
These RAM-only writes are not vendor partition installation tests.

The recovery read-only vendor image SHA256 is
`3bd323725791252e71451d815bab10f6ecbd27abcecf009c5c63640f4bc041e7`;
it differs from reference only at 4096-byte blocks 2721, 2722 and 11501,
the known two speaker-policy XMLs and experimental Dolby XML. Both LP metadata
copies and their geometry/header/table checksums agree. Device read-stream and
host hashes match. The real boot passes the existing logical-vendor/no-AVB-fstab
guard. No partition writes or actual effect activation follow from these checks.

The generated preflight ZIP's exact Edify script was executed with the reference
ROM update-binary in real Lineage Recovery. It checked the read-only mounted
system/product build properties, created the logical vendor mapping, passed the
boot guard and complete three-state native preflight, and reported
`SOUNDBOOSTER PREFLIGHT VERIFIED`. Afterwards the full mapped vendor SHA256
remained identical to the inspected live state above. The ZIP, extracted tools
and empty temporary mount points were removed from RAM; system/product/vendor
were not left mounted. This invocation does not test the recovery sideload
signature-confirmation UI. Install/restore partition writes were not invoked.

## Optional private reference-image test

After local ROM preparation, tool compilation and packaging:

```sh
python3 tools/check_reference.py
```

This runs the same native core against the privately extracted original vendor
and boot. It verifies all three patched XML files, no-op reapplication, and
byte-exact restoration. It neither uploads firmware nor accesses a block device.

## Reports

Include model, exact ROM/recovery version, whether vendor was untouched,
operation and exact failure. Redact personal/device data. Do not attach
vendor images, proprietary templates, cache backups or entire unredacted logs.
Before adding another model or template, document its layout, boot-chain
checks, rollback and listening evidence; do not simply loosen existing guards.

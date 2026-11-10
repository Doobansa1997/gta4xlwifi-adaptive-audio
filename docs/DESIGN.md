# Design and preset

## Selected final architecture

The final selected preset is native SoundBooster + original Dolby with
**-7 dB speaker policies**. Build and install defaults are documented at the
top of [BUILD](BUILD.md) and [INSTALL](INSTALL.md). The first pipeline below
is the retained historical XML-only implementation, not the current distribution.

The final build reconstructs an audited EROFS vendor and regenerates the original
AVB hashtree/FEC without changing partition size or verification policy.
The streaming recovery engine checks three complete pinned image states
(reference, previous -9 dB, final -7 dB) before changed-block writes.
Restore targets the full reference vendor. The final bridge uses the unchanged
ARM32 Samsung engine plus existing vendor libc++ in an explicit local dependency
group, accepts HIDL mask 30/31, and exposes processing/bypass counters.
Real speaker music processing, installation/read-back and boot are verified.
This is an exact-image deployment, **not an OTA-adaptive XML patch**.

## Pipeline

The Edify wrapper is run by the official legacy updater extracted locally
from the reference full OTA. It checks recovery device identity and installed
system/product properties, reads ext4 with `ro,noload`, unmounts vendor and
recreates its logical mapping. It never writes the super metadata.

Preflight/apply also inspect the current boot ramdisk's vendor fstab entries.
They require a supported legacy boot/gzip/newc layout and reject vendor AVB
or verify flags. This narrow check is not a full verification of every
possible bootloader/DT/device-mapper arrangement.

The native tool:

1. Checks target type, bounded size/alignment, mount state and exclusive lock.
2. Copies vendor to a temporary regular file, leaving the device unchanged.
3. Uses pinned EROFS tools to verify encoding, extract the three files and
   discover their single-cluster layouts.
4. Requires byte-exact recognized original XML, previous -6/-9 dB presets, or all three patched XMLs.
   Mixed or unknown configuration is refused. Already-patched is a no-op.
5. Independently decodes each source cluster with LZ4, recompresses its
   replacement into the same 4 KiB space and verifies a round-trip.
6. Writes the three changes to the staging image and checks it again with
   EROFS tools and exact replacement-template comparison.
7. Verifies that its complete SHA256 equals the current vendor with only the
   intended cluster substitutions. Checks that source vendor did not change.
8. Rechecks the source identity before real writes. ZIPs do not create backups.
9. Writes only the three clusters, fsyncs, rereads them and hashes all vendor.

The filesystem metadata and the decoded XML sizes are not rebuilt. The
algorithm depends on the checked single 4 KiB pcluster layout. It deliberately
does not try to grow files, move extents or repair unknown layouts.

## Restore format

The current recovery ZIP uses `replace` for installation and `reset` for
restoration. Both use the same staged validation; reset targets original XML
templates. No backup or cache mount is used. Unknown/partial configurations
are refused, including interrupted writes that no longer match templates.

The native `apply`/`restore` commands retain the legacy backup-based workflow
for existing backups and file-image tests. Its format is described below.

`AUDADP01`, little-endian uint64 image size, original SHA256 hex, patched
SHA256 hex, three records (offset, original 4096-byte cluster, patched
4096-byte cluster), followed by SHA256 hex of the preceding backup bytes.

Restore validates the backup and computes the current whole-image identity
with saved original clusters substituted. This must equal the backup's
original image identity, even if some current audio clusters contain an
interrupted write. Substituting saved patched clusters must also yield the
recorded patched identity. Exactly one backup must match.

This prevents blindly copying an old vendor onto a new nightly. It does
not recover corruption outside the saved clusters, a lost backup, device
failure or every possible power-loss scenario.

## Preset

All configured speaker curve points are reduced by **1100 millibels**.
Referenced curves are expanded into speaker-only nodes; shared definitions
and non-speaker nodes are unchanged. Both legacy (13 speaker streams) and
engine (12 speaker groups) XML representations are handled.

Dolby optimizer gain uses the Q4 dB reference scale (16 raw units/dB), same
left/right values:

| Frequency (Hz) | Gain (dB) |
|---|---|
| 47 | -3 |
| 141, 234 | +2 |
| 328 | +1.5 |
| 469 | +1 |
| 656, 844, 1031 | +0.5 |
| 1313 | -1 |
| 1688 | -1.5 |
| 2250, 3000 | -2 |
| 3750 | -1.5 |
| 4688 | -1 |
| 5813 | -0.5 |
| 7125 | -1 |
| 9000, 11250 | -1.5 |
| 13875 | -2 |
| 19688 | -2.5 |

This bass revision adds 1 dB at 141/234 Hz and 0.5 dB at 328 Hz relative to
the restored-treble -11 dB preset. All other bands and policy attenuation
are unchanged. Both earlier -11 dB presets are accepted for direct replacement/reset.

These are project-chosen experimental gains, **not Samsung's stock EQ**.
Unlike the earlier cuts-only presets, this revision permits up to +2 dB
at 141/234 Hz, +1.5 dB at 328 Hz and +1 dB elsewhere. Policy attenuation
does not prove internal DSP headroom or prevent speaker distortion.
The actual proprietary engine response and profile bypass behavior have
not been acoustically measured. Existing regulator/protection parameters,
complex EQ and hardware gains are preserved.

Only original template hashes and project-authored transformations are public.
Full original/patched firmware XML templates are generated locally and excluded
from Git. Changing template hashes to accept a new tuning requires a deliberate
review and new tests, not automatic inheritance.

## Samsung firmware investigation and separate baseline

Local extraction of Samsung SM-P610/ITV `P610XXS7FYD1` found that
`vendor/etc/dolby/dax-default.xml` is byte-identical to the original Lineage
reference (SHA256 `e867897cbf1ba05a372833c0ac77d6c28598bbd3218636665492fdb278ede20e`).
All 20 speaker optimizer gains are zero in that file; other Dolby processing
and runtime profiles still exist.

Samsung also provides `SoundBoosterParam.txt` and a SoundBooster wrapper/engine,
not present in the inspected Lineage effect setup. The wrapper references that
file and `lib_SoundBooster_ver1050.so`. Read-only binary inspection identifies
`SoundBooster_Interface::LoadParameter`, separate Legacy/Music AMF filter
setters, `Filter::BQcoeff_compute`, volume-dependent parameter tables and
orientation handling. It does **not** establish the active stock runtime mode,
all field semantics or a complete portable signal chain. Raw numeric triples
must not be treated as a verified EQ preset or guessed into the Dolby bands.

Samsung mixer includes were resolved before comparison. Both mixer variants
have the same 901 named paths as their flattened Lineage counterparts.
The observed differing paths concern microphone/recording/loopback paths;
the inspected speaker playback paths match. Missing standalone gain files on
Lineage are therefore not evidence that speaker gains were lost.

The optional `samsung-dolby-baseline` build installs the verified original
Dolby file without serialization changes and retains -11 dB speaker curves.
It is a conservative comparison/reset of the project's custom EQ, **not an
exact SoundBooster/One UI port**. No proprietary executable is added to the
ZIP. Exact prior custom and baseline states are recognized as complete sets;
unknown/mixed sets remain refused. The existing custom profile is unchanged.

### Verified static SoundBooster AMF model

The read-only analysis in `tools/soundbooster.py` accepts only the reviewed
parameter-file SHA256. It checks all 157 records and generates a local JSON
report, not a recovery preset. No firmware data or proprietary executable
is committed with the analysis tools.

The engine parser dispatches on groups A/B/C/D and banks A/C; rows ending
A-H hold eight triples, M holds eight filter types and U the bank enable.
In the reviewed parameter file, AA/AC and BA/BC are paired identical banks,
enabled with eight type-1 filters each. CA/CC/DA/DC are disabled.
These are parameter-file settings, **not proof that any bank is active
on a stock playback route**.

`SoundBooster_Music::SetPar_AMF` at `0x11e7c` checks the enable at offset
`0x80`, reads triples at stride 12, reads the type array at `0x60`, and
passes a 48000 Hz sample rate to coefficient generation. In the reviewed
ARM32 engine, `Filter::BQcoeff_compute` at `0x188a0` maps type 1 to
peaking filters: frequency in Hz, width in Hz (`Q = frequency / width`)
and signed gain in dB. The model uses `tan(pi * frequency / 48000)` and
`10^(abs(gain)/20)`, with separate boost/cut normalization. The resulting
transfer has unity DC/Nyquist gain and the requested gain at its center.

`tools/verify_soundbooster.py` checks this interpretation against the
original ARM instructions with bounded emulation of **only** that coefficient
routine. It requires the reviewed engine SHA256, maps executable input
read-only, permits only the coefficient address range and two intercepted
math imports, and limits instruction count and execution time. It does not
load an Android linker, initialize the engine, permit syscalls or access
the tablet. The math imports use host math rounded to float32 rather than
claiming bit-exact Android libm behavior. Original output coefficients are
decoded as Q30 with negated feedback terms.

The wrapper default constructor requests engine mode 2; the base constructor
resolves mode 0 to Lite, 1 to Music and 2 to Legacy through its PLT relocations.
This corrects the earlier swapped interpretation of the mode-1/mode-2 branches.
`SB_init` also defaults to 2, but valid initialization data of at least
`0x1c` bytes can override it with the mode at offset `0x18` (accepted range
0-2). The default therefore does not prove which mode One UI actually uses.
The wrapper maps rotation values 1 and 3 to engine values 3 and 1, respectively,
and forwards the other values. This establishes API behavior only, not stock
framework call sequences, physical channel assignment or bank selection.
The inspected effects XML declares SoundBooster but does not automatically
attach it in its music postprocess section (that section attaches `sa3d`).
A declaration alone therefore cannot establish the running stock chain.

The generated responses intentionally exclude HPF, pre-DRC, multiband DRC,
volume scaling, channel reconfiguration and motion switching. They must not
be sampled into Dolby's 20 bands and advertised as Samsung's complete EQ.
The remaining port is blocked on reconstructing those stages and validating
the stock runtime control sequence; no new SoundBooster ZIP is produced.

### Verified conditional control dispatch and HPF

`tools/trace_soundbooster.py` adds bounded execution of the reviewed ARM
Interface/Base/Music/Legacy parameter routines. Both firmware hashes are
required. Original code is RX, writable objects/stack are separate, and each
stage permits only explicit instruction ranges and intercepted dependencies.
Unknown calls, oversized memory operations and instruction/time exhaustion
fail explicitly. No Android library loading, syscalls, playback or device writes
are involved.

For the reviewed input and two supplied base objects, Interface dispatch
forwards groups A and B. Base mode 1 forwards the H/M tables and first AMF
bank to Music; mode 2 forwards H/L and the second AMF bank to Legacy.
Tests use deliberately distinct synthetic bank markers to distinguish this
selection even though the reviewed A/C bank pairs have identical values.
These conditional calls do not identify physical left/right speakers, prove
the initial One UI mode, or exclude subsequent orientation/motion changes.

Both traced modes forward HPF values `[1, 75, 0]`; the FFT setter receives
`[1, 75, 8, 0]`. **8 is not the HPF order.** Its coefficient call uses
48000 Hz; `Filter::GetHPFcoeffs` at `0x1821c` produces two Q30 biquads.
Executing that coefficient routine with intercepted double-precision
`cos`, `sin` and `pow` verifies the fourth-order Butterworth HPF magnitude
at the reviewed 75/100 Hz cutoffs. The analytic magnitude is
`-10*log10(1+(tan(pi*cutoff/fs)/tan(pi*frequency/fs))^8)`.
This verifies a conditional coefficient response, not bit-exact IIR playback
or the complete acoustic transfer. At 75 Hz cutoff the original coefficients
give about -16.34 dB at 47 Hz, -3.01 dB at 75 Hz and -0.028 dB at 141 Hz.
The static AMF report intentionally remains AMF-only.

The original volume setters clamp stored gain controls to [-100, 0].
The reviewed Legacy input produces `[0, 0, 0]` (normal gain control,
motion flag, alternate gain control); Music produces `[-100, 0, ..., 0]`
for its 16 level slots. Synthetic boundary tests exercise both clamps.
Gain-scaler objects are null in this trace: neither control values nor the
synthetic zero format passed to FFT initialization establish effective
playback gain, runtime bit depth or actual volume-level selection.

Legacy DRC setup at `0xfbd4` is executed through its range validation and
downstream FFT calls: multiband processing is enabled, four arrays of 12
integers are forwarded, and the band-count argument is 12. Its other FFT
control calls are `[1,3,-4,100,500,0,2,0]` and `[1,0]`; pre-DRC setup is
intercepted with `[4,2,0]`. The Music trace captures all 16 level-dependent
DRC parameter sets without executing its DRC setup. These are control traces,
not verified dynamics: FFT band placement, effective envelope behavior,
limiting, pre-DRC processing and fixed-point audio processing remain unresolved.
Out-of-range Legacy array fields reset to zero rather than saturating;
synthetic original-instruction tests cover that distinction.

### Compression backend and mode-2 curve reconstruction

The trace now follows `SoundBooster_FFT_MB::SetPar_MBDRC` at `0x1ce28`,
the two parameter backends and `CalcGainCurveTable` at `0x201d4`.
For the reviewed final argument -1, each 12-element input array becomes
**11 FILX slots** `[0, source[2], ..., source[11]]` and **3 EMQF slots**
`[source[0], source[1], 0]`. The padding must not be interpreted as two
additional independently tuned acoustic bands. Other split modes are not
accepted by this reconstruction.

In the executed backend routines, gain controls are converted using
`10^(gain/20)` to Q15. Threshold controls use `10^(threshold/20)` to Q15
for FILX and Q23 for EMQF. This establishes dB-to-amplitude control conversion,
not the complete frequency-dependent transfer.
Both timing arrays use the Q15 coefficient
`trunc(32768 * exp(-2.2 * (frame_size >> 1) / sample_rate / (time * 0.001)))`.
Thus time controls are in milliseconds in this conversion. A zero time
produces zero through the original floating-point divide-by-zero/exp path;
the model handles that case explicitly. Host math imports are rounded to
float32, not claimed bit-identical to Android libm.

The **curve mode 2** here is a compression selector, not the previously
discussed engine mode 2. Original generation produces 44-byte records:
five first coordinates `[-96,-50,-35,-20,0]`, five second coordinates
and point count 5. For gain `g`, threshold `t`,
`s=min(g-50,t-10)` and `q=(t-s)/4`, the second coordinates are:
`[min(g-96,-91), s, min(g-35,s+2*q), min(g-20,s+3*q), t]`.
`compression_curve_mode2` reconstructs this record and the trace requires
exact equality against original generated records. For `g=3,t=-12`, the
second coordinates are `[-93,-47,-32,-20.75,-12]`.
This verifies curve construction, **not how the audio loop interpolates,
detects levels, combines bands or limits transients**.

Backend conversion is run with an explicitly synthetic 1024-frame/48000-Hz
context; tests also exercise 512 frames. No full FFT initialization or actual
stock frame configuration has been established. Curves and conversion are
no longer stubbed; audio processing, pre-DRC and gain-scaler objects still are.

### Native integration feasibility on the inspected Lineage setup

Local Samsung vendor-image inspection also found genuine AArch64 variants.
The locally extracted 64-bit wrapper SHA256 is
`066306cdcace7710d0fb1f37ceee592acb5021c11853b665d2327c71c07e2096`;
engine SHA256 is
`b221f73f65aeae13b10200b90d05f493c178ced1e8f6441291bda81eaa6cc3c0`.
These are separate binaries, not covered by the ARM32 emulator's hash or
instruction-address verification. Their presence removes a 32-bit-only
obstacle but does not establish loadability.

The stock wrapper has a `DT_NEEDED` entry for `libsecaudioinfo.so` even
though no undefined named symbol in its inspected dynamic symbol table
refers to that API. The dependency itself requires `libfloatingfeature.so`,
`libsecnativefeature.so`, Binder and private Android utility APIs. A dependency
cannot simply be omitted because its direct symbols appear unused: loading
and constructors may have side effects and the loader still resolves it.

Read-only inspection of the connected Lineage tablet found the engine,
`libsecaudioinfo.so` and `libfloatingfeature.so` absent at their vendor library
paths. The reference vendor contains `libsecnativefeature.so`; access to the
live file was denied, so its live ABI was not verified. AudioFlinger reports
DAX3 but no SoundBooster in the inspected active chain. No effect was added,
enabled, loaded or played in this check. Direct stock-wrapper copying is
therefore **not a standalone integration**, and installing more Samsung
framework libraries or editing ELF dependencies has not been validated.
A minimal compatible wrapper around the original engine remains a possible
alternative, not an implemented or tested solution.

### Native engine processing experiment (not a system effect)

`tools/probe_soundbooster.py` and its C++ probe now test the unmodified
reviewed AArch64 engine in a separate shell process on Lineage. The launcher
requires exact engine/parameter hashes, uses the installed NDK, validates
device transfer hashes and removes its unique temporary files. The process
uses only memory buffers: no AudioTrack, ALSA, effect registration, audio
service injection or speaker playback. This is native execution, not a
security sandbox or a memory-safety proof of the proprietary library.

The ABI was verified against the 64-bit wrapper instructions and engine
relocations: factory creation selects mode explicitly; vtable slots 0/1
initialize PCM16 and 48000 Hz; slot 3 receives the complete S/zero-THC/four
group aggregates with the M-array pointers; slot 8 is the float-volume
processing call. Its return value is the input **frame count**, not zero
status. The stock file loader is bypassed: inspection showed that an
unrecognized filename is replaced with the stock vendor path. Direct
parameter passing avoids changing that path or installing a vendor file.

Each of Music and Legacy processes silence and stereo-identical sine tones
at 157, 340, 1000 and 7400 Hz, at -36/-18/-6 dBFS peak levels. Each of the
30 cases creates/destroys its own engine. It processes 49152 frames in
256-frame calls and measures the second half (49152 interleaved samples).
Canaries check that each call stays within its expected PCM16 stereo output
buffer; frame counts, silence, nonzero tone output, PCM bounds, absence of
clipped samples and low-frequency level dependence are required.

On the inspected Lineage tablet both modes completed this matrix. At
157 Hz the measured total RMS gain was approximately +11.3 dB at -36 dBFS,
+5.7 dB at -18 dBFS and -1.2 dB at -6 dBFS. These are aggregate measurements
of a synthetic in-memory signal chain, not acoustic measurements, pure EQ
gain, full spectral/distortion analysis or stock-runtime equivalence.
The level dependence confirms that a static EQ alone is insufficient.

This removes a major feasibility uncertainty: the engine can actually load
and process PCM on Lineage without loading the incompatible stock wrapper.
It does **not** verify the audio-service linker namespace, automatic
speaker-only routing, volume callbacks, orientation/motion behavior, latency,
real-time safety, all sample formats/rates or compatibility with Dolby.
A production effect wrapper, integration/rollback mechanism and broader
waveform/route validation remain unimplemented; no SoundBooster install ZIP
is produced by this probe.

### Experimental Android effect bridge

`src/soundbooster_effect.cpp` now implements an **experimental**, separately
tested legacy Android effect-library entry point (`AELI`, library API 3.0 /
control API 2.0). It uses the shared `soundbooster_engine.h` ABI implementation,
also used by the direct native probe. It does not depend on Samsung's original
wrapper, `libsecaudioinfo` or floating-feature libraries. The default test build depends
on the shared NDK C++ runtime, libc, libm, libdl and liblog; an optional embedded
runtime variant removes the direct shared C++ dependency. Proprietary input is still
local, hash-checked and never included in the repository.

The bridge deliberately accepts only direct-buffer **48000-Hz PCM16 or float stereo**,
READ input and WRITE or ACCUMULATE output, with complete configuration masks. Mixed formats,
mono, other rates, provider buffers and live reconfiguration
while enabled fail explicitly. Each process call requires matching buffer
frame counts from 1 through 4096; tested block sizes are 1/48/96/256/1024/4096.
Float processing uses native engine bit-depth value 3, established by the stock
64-bit wrapper's `SoundBoosterInit` format branch at `0x2178` through `0x219c`
(Android format 5 maps to engine value 3). No project-authored float-to-int16 conversion
is used. Speaker float input must be finite and normalized to [-1,1]; NaN,
infinity and out-of-range samples fail before touching output. Float headroom
outside that interval is not yet verified. Configuration constructs a fresh
engine with the selected bit depth after validating both buffer descriptions
and rechecking the engine hash; failed configuration preserves the old state.
Configuration, lifecycle and status replies follow the legacy command
interface, unsupported commands return `-ENOSYS`, and invalid requests log an
error. Processing uses a nonblocking mutex attempt, returning `-EAGAIN` if a
command is concurrent; real-time behavior has not been validated.

Lineage 23.2's
[AudioFlinger configuration](https://github.com/LineageOS/android_frameworks_av/blob/lineage-23.2/services/audioflinger/Effects.cpp)
requests float first and uses ACCUMULATE for the last insert in a non-global
session with distinct input/output buffers; global/in-place chains use WRITE.
Registering an effect library alone does not automatically attach it to playback.
The live vendor configuration declares DAP but has no active music postprocess
or speaker device-effect attachment for this bridge.

ACCUMULATE processes into fixed per-instance scratch arrays (8192 samples per
format), then adds to the existing destination. No scratch allocation occurs
in the process callback. PCM16 sums saturate to [-32768,32767]; float sums retain
headroom outside [-1,1], rejecting nonfinite buffers or overflow before any
destination modification. The normalized input restriction applies to float
speaker processing, not the existing accumulation destination. Bypass and
disabled accumulation add input rather than overwriting existing audio;
disabled calls still return `-ENODATA`. Exact in-place aliasing is tested with
scratch preserving the original destination during native processing.

The adapter uses explicit **Legacy engine mode 2**, not a claim about One UI's
actual selection. It processes only the exact speaker device mask `0x2`.
Unknown, wired, Bluetooth, USB and combined-device masks copy samples unchanged.
Disable clears the engine and bypasses with `-ENODATA`; reset and route changes
clear buffered state. `VOLUME_IND` receives two unsigned Q8.24 values in [0,1]
and supplies their minimum to the engine's float-volume selector. It does not
claim volume-control ownership or attenuate the signal a second time.
Stereo-volume policy and the engine's internal response remain experimental.

The bridge and harness share a narrow ARM32/ARM64 wire-layout header rather than
vendoring platform headers. Optional compile-time checks against original
Android 16 AOSP headers independently verify descriptor/config/interface
sizes, relevant member offsets, command IDs, formats, flags and device masks.
The three core effect headers are hash-pinned by the launcher. The descriptor
uses new project-specific UUIDs, not the Samsung implementation UUID.

The opt-in device harness loads this library **only in a separate shell
process**, not the audio service. Tests verify command errors and statuses,
factory hash refusal with a deliberately modified temporary payload,
descriptor/factory UUID checks, configuration readback, lifecycle, unknown/
non-speaker/mixed routing, in-place bypass and processing, zero/quarter/unity
volume indications and output canaries. Across 137472 processed frames,
adapter output must equal direct engine output **sample for sample**.
Both formats are tested, including changing formats while disabled and
rejecting invalid float samples without modifying output. The harness measures
192 processing calls per format against their respective audio periods;
these WRITE-mode shell-process measurements are not proof of audio-service deadlines.
An additional 1060032 frames test ACCUMULATE against an independent engine plus
the initial destination, across both formats, exact in-place/distinct buffers,
three volume indications and all six block sizes. Saturation, float headroom,
non-speaker/disabled mixing, invalid floats, overflow and canaries are checked.
No effect is registered and no test audio is played.

Build paths deliberately refer to the launcher's temporary test directory;
the generated shared object is **not a deployable vendor effect or ZIP**.
The real tablet currently reports a PCM16 main processing thread and a
separate float processing thread. Both formats now work in the harness, but
the prototype cannot yet be advertised as generally compatible. Audio-service
loading/linker namespaces, automatic speaker routing, all runtime controls,
real-time/latency behavior, protection and interaction with Dolby still require
integration validation and a reversible deployment mechanism.
The current ADB shell is unprivileged (`uid=2000`), with no accessible `su`
and `ro.debuggable=0`; vendor is mounted read-only EROFS. An unlocked bootloader
does not grant shell access to install the effect. Do not equate rootless shell
loading with permission or linker compatibility in the audio service, or use
the existing three-XML cluster patcher to add libraries to the vendor image.

### Actual audio-service architecture and attachment candidate

Architecture checks against the hash-verified reference vendor image found:

| File in vendor | ELF class/machine | SHA256 |
|---|---|---|
| `bin/hw/android.hardware.audio.service` | ELF32 / ARM (40) | `00ed3b948732bb7c74e2088e89f9a6af7ecb199c84d8e0a3009782e44752ed72` |
| `lib/hw/android.hardware.audio.effect@7.0-impl.so` | ELF32 / ARM (40) | `cc29d9769946d1f502999fd14300b3529e47827c8b69a1f415cc8aa469b69d8f` |
| `lib/soundfx/libswdap.so` | ELF32 / ARM (40) | `4e7bc822c516ecb86f4f8668516b104b45a6ee6dd63194e172519c6dabc0faf9` |

Live init declares that service path, HIDL lists effect factory 7.0, and the
effect implementation/DAP paths are present under `lib`, not `lib64`.
Reading the running process executable is denied to shell, so reference-image
ELF identity must not be presented as a live executable hash verification.

The adapter now also builds for `armeabi-v7a` and uses the separately pinned
original ARM32 engine. AOSP assertions validate the 32-bit layouts (buffer
config 32 bytes, config 64 bytes, library API 3.0 prefix 28 bytes) as well as
the earlier ARM64 layouts. Both native matrices pass on the tablet at each ABI,
but that still does not activate or prove loading inside the HIDL service.

`tools/configure_soundbooster.py` accepts only effects XML SHA256
`ed6a693adae5c0e28170c48956f02f5f0e7cfba77d690c5fe40da163ed1d3ea0`,
verified against the live tablet. It preserves original bytes except for
adding the project library/effect declarations and a single music postprocess
attachment. Speaker routing remains enforced by the bridge. It does not attach
to calls, alarms or notifications or remove DAP. Processing order/coexistence
with DAP and a listening comparison remain unverified.

Generation saves the exact original XML and a manifest, refuses overwrites,
and explicitly marks service integration/deployment/coexistence as unverified.
This only prepares configuration: a safe deployment still needs ARM32 binaries,
persistent engine/payload paths, a verified C++ dependency resolution and
reversible recovery/ROM integration on read-only EROFS.

### Embedded runtime and loading-evidence limits

The optional `--static-runtime` build links libc++ into both the adapter and
the test executable. `soundbooster_static.map` limits the adapter's public
symbols to `AELI` only. Embedded C++ ABI symbols are private rather than
exposed to the other audio effects. The harness hides its runtime exports.
Build-time ELF inspection enforces this exact export set for both ABIs and allows
only libc/libm/libdl/liblog direct dependencies; the recorded harness export
set must be empty. This guards against the test executable accidentally
supplying symbols that would not be available in the service.

The same native adapter matrices pass for ARM32 and ARM64 without copying
`libc++_shared.so` or adding the temporary path to `LD_LIBRARY_PATH`.
Process maps are inspected before loading and after processing to reject an
NDK shared-runtime mapping and report existing platform libc++ mappings.
The observed platform `libc++.so` remains present. Do not equate statically
linking the adapter with complete process isolation or proof of engine symbol
provenance: platform C++ ABI interposition/coexistence still needs validation
in the real HIDL service. The bridge remains loaded only in a shell process
and still embeds temporary engine/payload paths.

The harness now checks actual loaded relocation-slot providers for the reviewed
C++ ABI imports, rather than relying on `dlsym` (which can return a different
lookup result from the address already stored in a relocation). Fixtures are
generated from the hash-pinned engine ELF and must match complete reviewed
per-symbol counts. ARM32 has 105 slots: 14 for each RTTI vtable, 71 pure-virtual
references, two unexpected-handler references and one each for new/delete,
cleanup and personality. ARM64 has 31 slots: 14 for each RTTI vtable and one
each for new/delete and personality. ARM64 does not import the ARM32
pure-virtual/unexpected handlers. The static export map no longer exposes
engine runtime imports; the engine uses the external system/vendor runtime.

`dl_iterate_phdr` locates the unique engine mapping. Every fixture slot must
fall entirely within a readable PT_LOAD segment before the harness reads its
resolved pointer. `dladdr` attributes that pointer to a known runtime image;
multiple slots for one symbol must agree. Python validates the provider list,
unique symbols and exact slot counts against the generated fixture.
This examines the ABI bindings in use, including RTTI pointers with relocation
addends, without modifying engine code or relocation memory.

All checked engine C++ slots in the default experiments bind to **platform libc++**, in both the
shared and embedded test variants and both ABIs. The embedded build therefore
removes the adapter's direct NDK runtime dependency but does not make the
Samsung engine independent of the platform runtime. Unrelated libc callbacks
(`__cxa_atexit`/`__cxa_finalize`), weak imports and symbols not in this reviewed
C++ ABI set are outside the provenance check. These findings do not establish
HIDL service binding, exception-unwinding correctness under faults, all possible
load orders or vendor/system C++ runtime interchangeability.

### Vendor-runtime compatibility without system modification

The live `[vendor]` linker configuration searches `/odm/${LIB}` and
`/vendor/${LIB}` before other vendor paths, and does not share libc++ through
its system namespace link. The reference audio service declares a direct
`libc++.so` dependency. The installed `/vendor/lib/libc++.so` SHA256 is
`05b594f7ce7f249e743f2e170ebe844e157d9a5e016ffbadf657d6d6d59ed663`,
byte-identical to the hash-verified reference vendor image's runtime.

The opt-in ARM32 `--vendor-runtime` test preloads that exact installed file
into the separate embedded-runtime harness process, after verifying the live
hash. No extra runtime is transferred, the temporary library search path is
not used, and no global environment or service configuration changes occur.
All reviewed engine C++ relocation providers must then be `vendor_cpp`,
the vendor mapping must be present and system libc++ must be absent.
The 1197504-frame PCM matrix passes these checks, including all 105 slots.
Other shared/embedded experiments explicitly clear the preload variable.

This verifies the actual installed vendor runtime can support the engine's
reviewed native processing/control paths with the adapter's private embedded
runtime. It does not simulate the vendor linker namespace or SELinux domain,
validate audio-service thread behavior, attach the effect or test concurrency
with Dolby. Engine factory/process/destroy remain paired in the engine;
POD parameter tables and PCM buffers cross the project boundary, not STL
objects. Cross-runtime exceptions on untested fault paths remain unverified.

### Offline filesystem integration and remaining deployment gates

The host `erofs-manifest` auditor walks and decodes the complete filesystem,
including xattrs and symlink contents. The offline staging tool constructs a
metadata-preserving tar and clean LZ4 EROFS image instead of using incremental
imports, which changed original directory metadata and appended beyond the
partition boundary. Hardlink topology is compared independently of inode
numbers. No new EROFS feature bits are accepted.

The reviewed filesystem contains the persistent-path ARM32 bridge, original
engine, binary parameters and music attachment. It preserves -11 dB speaker
attenuation and reference-original Dolby tuning, not the experimental EQ.
The clean reconstruction passes fsck and the complete 951-to-954-entry audit.
It is a filesystem experiment, not a live vendor snapshot or an install image.

The reference partition tail contains AVB hashtree/FEC data and a footer, not
reusable zero padding. Even after stripping the bridge and increasing logical
compression extents without changing kernel features, the candidate overlaps
that original region by 176,128 bytes. Default staging saves the audit and fails
explicitly rather than overwriting the old tree. Optional `--prepare-partition`
regenerates AVB/FEC only after the filesystem audit. A host encode-only frontend
uses the original pinned Android Reed-Solomon implementation. Before accepting
it, canonical AVB generation plus this frontend must reproduce the complete
reference partition byte-for-byte, including all FEC bytes. This check passes.

The regenerated candidate fits the unchanged partition: its filesystem is below
the 159,854,592-byte conservative AVB maximum by 303,104 bytes. The original
`NONE` algorithm, zero flags, salt, version, properties and rollback indices
are preserved. The tool separately checks FEC parity because canonical
`verify_image` verifies the hashtree but not parity.

A clean rebuild changes block placement throughout the image. The existing
three-XML-cluster installer cannot deploy it. A future installer needs a
recovery-time identity check of the actual installed partition, boot verification
guards, and a tested exact apply/restore path. A reference-derived candidate
does not establish the live partition's full identity.

An offline ZIP of changed blocks carries both reference and candidate bytes,
all block hashes, and both whole-image hashes. A regular-file-only simulator
preflights every block and both reconstructed whole-image identities before
writing. It verifies exact apply/restore and restoration of known mixtures
after interruption between whole-block writes; unknown/torn blocks are refused.
The bundle is not a recovery ZIP and cannot be passed to the existing installer.
No device backup is created. Recovery implementation, boot-chain checks,
the real installed-vendor identity, and actual service activation remain gates.

The native recovery engine now shares the existing file I/O, boot, size and
unmounted-device guards. A streaming three-state bundle includes original,
inspected live and candidate block hashes, unique changed block payloads and
all three whole-image identities. It preflights every record and reconstructed
image before writes. Device mode additionally requires recovery and the
logical mapper name `vendor`, never the physical super partition.

Separate private preflight/install/restore packages pin the complete three
input images. Restore targets the exact reference vendor without a device
backup, including from known mixed states; arbitrary/torn blocks are refused.
The exact preflight ZIP updater script passes in real recovery, with the live
vendor hash unchanged. Native apply/restore also passes on host full-size
images and recovery RAM fixtures, not on the vendor block device. These broad
reconstruction packages must not be confused with the default XML-only ZIPs
or reused after an OTA.

Subsequent authorized installation verified actual vendor writes and independent
whole-partition read-back, followed by a successful Android boot. The initial
bridge attached but rejected the HIDL PCM configuration: HIDL drops the obsolete
buffer bit, passing mask 30 rather than 31. The corrected bridge accepts exactly
30/31 without relaxing PCM geometry/provider validation. It handles
`EFFECT_CMD_DUMP` (21), reporting configuration and separate successful-processing
and bypass frame counters under the existing mutex.

A separately pinned `hidl-fix` bundle migrates the initial SoundBooster image
to the corrected image, retaining exact-reference restore. Its real recovery
write/read-back and Android boot pass. Actual service processing remains gated
on unlocked speaker playback and increasing processing counters; enabled state
alone is insufficient evidence.

Active playback then identified the engine's missing C++ dependency as a second
service-only failure. The runtime-linked candidate makes both the unmodified
engine and the existing, hash-checked vendor libc++ explicit `DT_NEEDED`
dependencies of the bridge. They load in the same local group; no symbols are
exported from the bridge's private C++ runtime beyond `AELI`, and no global
preloading or linker/SELinux configuration change is needed. Engine loading is
now eager with the bridge, under the installer's byte-exact image/payload checks.
The existing command-time engine hash check is retained but no longer precedes
initial ELF loading. Link-only import stubs are build artifacts, not deployed
libraries. Isolated namespace tests reproduce the original failure and verify
processing after the fix; real audio-service counters remain the final gate.

The runtime-linked bridge subsequently passed the real-service speaker gate:
active Spotify session 121, status 0, stereo float 48 kHz, HIDL masks 30,
processed frames 1287360 then 1532160 with zero bypass. Original Dolby runs
concurrently with status 0 and -11 dB policy hashes are unchanged. Latest full
vendor read-back was missed because the user rebooted immediately after sideload;
the live processing evidence does not establish that whole-image identity,
all-route validation or acoustic equivalence.

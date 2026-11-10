#!/usr/bin/env python3
"""Build private experimental recovery ZIPs for the exact reviewed vendor states."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

import package
import prepare_rom
from preset import digest

ROOT = Path(__file__).resolve().parents[1]
LIVE_SHA256 = "3bd323725791252e71451d815bab10f6ecbd27abcecf009c5c63640f4bc041e7"
CANDIDATE_SHA256 = "7c96ea2e500ff7af56fee4870ce9cc2494f1addb5050d2b5e51532c5d44e444a"
HIDL_FIXED_SHA256 = "35472c09cae0800bf611cf690a35687625fc8c03db91a89c742fc854f64f9d1c"
RUNTIME_FIXED_SHA256 = "529c2a3e0559854b567f75f2e934407ad74d7ea0aeab0521ad690b9a00ff2a36"
MINUS9_SHA256 = "f88c8b012381b10e86cb94333fc4b223287946c956483255fef0119646a2c943"
MINUS7_SHA256 = "20eb8ae447797bbb386127c2010aa0610a698f2bd2271d15bf69ce93345674c8"
REVIEWED_TRANSITIONS = {
    "final": (MINUS9_SHA256, MINUS7_SHA256),
    "initial": (LIVE_SHA256, CANDIDATE_SHA256),
    "hidl-fix": (CANDIDATE_SHA256, HIDL_FIXED_SHA256),
    "runtime-fix": (HIDL_FIXED_SHA256, RUNTIME_FIXED_SHA256),
    "minus9": (RUNTIME_FIXED_SHA256, MINUS9_SHA256),
    "return-minus11": (MINUS9_SHA256, RUNTIME_FIXED_SHA256),
    "minus7": (MINUS9_SHA256, MINUS7_SHA256),
    "return-minus9": (MINUS7_SHA256, MINUS9_SHA256),
}
BLOCK = 4096
SIZE = 162500608
RUNTIME = "/tmp/soundbooster-recovery"


def block_bundle(original, live, candidate, destination):
    paths = (original, live, candidate)
    identities = [digest(path) for path in paths]
    sizes = [path.stat().st_size for path in paths]
    if len(set(sizes)) != 1 or not 0 < sizes[0] <= 2 * 1024**3 or sizes[0] % BLOCK:
        raise ValueError("Block bundle requires equal bounded 4096-aligned image sizes")
    changed = 0
    with original.open("rb") as first, live.open("rb") as second, candidate.open("rb") as third:
        streams = (first, second, third)
        with destination.open("xb") as output:
            output.write(b"SB3BLK01" + struct.pack("<Q", sizes[0]) +
                         "".join(identities).encode("ascii"))
            for _ in range(sizes[0] // BLOCK):
                blocks = [source.read(BLOCK) for source in streams]
                if any(len(block) != BLOCK for block in blocks):
                    raise ValueError("Source image truncated during bundle creation")
                hashes = [hashlib.sha256(block).hexdigest() for block in blocks]
                output.write("".join(hashes).encode("ascii"))
                if len(set(hashes)) != 1:
                    changed += 1
                    seen = set()
                    for checksum, block in zip(hashes, blocks):
                        if checksum not in seen:
                            output.write(block)
                            seen.add(checksum)
    if identities != [digest(path) for path in paths]:
        raise ValueError("Source image changed during bundle creation")
    return {"image_bytes": sizes[0], "state_sha256": identities, "changed_blocks": changed,
            "bundle_sha256": digest(destination), "bundle_bytes": destination.stat().st_size}


def script(mode, bundle_hash):
    if mode not in ("preflight", "apply", "restore"):
        raise ValueError("Unknown package operation")
    return package.version_checks() + f'''
ui_print("EXPERIMENTAL SoundBooster: broad vendor block reconstruction, not XML-only.");
ui_print("RESTORE resets the entire exact vendor to the reference ROM, no device backup.");
ui_print("Unknown/torn blocks are refused. Keep recovery, power and RESTORE available.");
package_extract_dir("tools", "{RUNTIME}") ||
  abort("E9601: Cannot extract SoundBooster tools.");
set_metadata_recursive("{RUNTIME}/bin", "uid", 0, "gid", 0, "fmode", 0755, "dmode", 0755);
ifelse(is_mounted("/vendor"), unmount("/vendor"));
!is_mounted("/vendor") || abort("E9602: Vendor is mounted.");
unmap_partition("vendor") || abort("E9603: Cannot recreate vendor mapping safely.");
run_program("{RUNTIME}/bin/audio-adaptive", "blocks-{mode}", "--device",
  map_partition("vendor"), "{RUNTIME}/blocks.bin", "{bundle_hash}",
  "/dev/block/platform/13520000.ufs/by-name/boot",
  "--confirmed-offline-or-recovery") == "0" ||
  abort("E9604: SoundBooster refused or failed. If writes started, STAY IN RECOVERY and apply SoundBooster RESTORE; unknown/torn blocks require manual recovery.");
ui_print("SOUNDBOOSTER {mode.upper()} VERIFIED.");
'''


def build(original, live, candidate, output, profile="final"):
    if profile not in REVIEWED_TRANSITIONS:
        raise ValueError("Unknown reviewed SoundBooster transition")
    for path, expected in zip((original, live, candidate),
                              (prepare_rom.REFERENCE_VENDOR_SHA256, *REVIEWED_TRANSITIONS[profile])):
        if path.is_symlink() or not path.is_file() or path.stat().st_size != SIZE or digest(path) != expected:
            raise ValueError("Only exact reviewed reference/live/candidate regular vendor images are accepted")
    native = ROOT / "build/bin/audio-adaptive"
    updater = ROOT / "build/update-binary"
    if not native.is_file() or not updater.is_file():
        raise ValueError("Build Android tools and prepare reference ROM first")
    output.mkdir(parents=True, exist_ok=False)
    bundle = output / "blocks.bin"
    manifest = block_bundle(original, live, candidate, bundle)
    artifacts = []
    for mode, name in (("preflight", "preflight"), ("apply", "install"), ("restore", "restore")):
        target = output / f"audio-soundbooster-{name}-gta4xlwifi-los23.2.zip"
        with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(updater, "META-INF/com/google/android/update-binary")
            archive.writestr("META-INF/com/google/android/updater-script",
                             script(mode, manifest["bundle_sha256"]))
            archive.write(native, "tools/bin/audio-adaptive")
            archive.write(bundle, "tools/blocks.bin")
            for source in (ROOT / "src/adaptive.cpp", ROOT / "src/soundbooster_blocks.h",
                           ROOT / "tools/package_soundbooster.py"):
                archive.write(source, "SOURCES/" + source.name)
            for source in sorted((ROOT / "build/licenses").rglob("*")):
                if source.is_file():
                    archive.write(source, "LICENSES/" + str(source.relative_to(ROOT / "build/licenses")))
            for name in ("erofs.tar.gz", "lz4.tar.gz", "picosha2.h"):
                archive.write(ROOT / "third-party" / name, "SOURCES/" + name)
            archive.write(ROOT / "docs/INSTALL.md", "INSTALL.md")
        with zipfile.ZipFile(target) as archive:
            if archive.testzip() is not None:
                raise ValueError("Recovery ZIP CRC verification failed")
        artifacts.append({"file": target.name, "bytes": target.stat().st_size, "sha256": digest(target)})
    manifest.update({
        "format": 1, "profile": profile,
        "status": "EXPERIMENTAL; package generation does not establish installation or service activation",
        "scope": "Private broad vendor block replacement for exact reviewed states only; not a public release",
        "recovery_target": "Logical vendor mapping only, correct size, unmounted, boot fstab guard",
        "restore": "Exact full reference vendor, not previous custom tuning; no device-side backup",
        "partial_restore": "Known original/live/candidate whole-block mixtures only; unknown/torn blocks refused",
        "native_sha256": digest(native), "packages": artifacts,
        "real_audio_service_verified": False, "device_partition_writes_verified": False,
    })
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "SHA256SUMS").write_text("".join(f"{item['sha256']}  {item['file']}\n" for item in artifacts))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--live", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New nonexistent private local directory")
    parser.add_argument("--profile", choices=REVIEWED_TRANSITIONS, default="final",
                        help="Exact pinned previous/desired vendor transition; never accepts arbitrary hashes")
    args = parser.parse_args()
    result = build(args.original, args.live, args.candidate, args.output, args.profile)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

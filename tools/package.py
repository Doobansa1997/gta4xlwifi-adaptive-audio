#!/usr/bin/env python3
"""Package a guarded, file-based installer; never embed an old vendor image."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import preset

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "build/stage"
OUTPUT = ROOT / "dist"
MOUNT = "/tmp/audio-adaptive-system"
PRODUCT = "/tmp/audio-adaptive-product"
RUNTIME = "/tmp/audio-adaptive"


def version_checks():
    return f'''ui_print("Adaptive audio: SM-P610 / LineageOS 23.2 only.");
getprop("ro.product.device") == "gta4xlwifi" ||
  abort("E9501: Wrong device. No vendor writes.");
!is_mounted("{MOUNT}") && !is_mounted("{PRODUCT}") ||
  abort("E9502: Temporary mount point already in use.");
mount("ext4", "EMMC", map_partition("system"), "{MOUNT}", "ro,noload,noatime,nodev,nosuid") ||
  abort("E9503: Cannot read system safely. Unsupported layout.");
file_getprop("{MOUNT}/system/build.prop", "ro.lineage.device") == "gta4xlwifi" &&
file_getprop("{MOUNT}/system/build.prop", "ro.build.version.sdk") == "36" &&
file_getprop("{MOUNT}/system/build.prop", "ro.build.version.release") == "16" ||
  abort("E9504: Wrong Android/device build. No vendor writes.");
mount("ext4", "EMMC", map_partition("product"), "{PRODUCT}", "ro,noload,noatime,nodev,nosuid") ||
  abort("E9505: Cannot read product safely. Unsupported layout.");
file_getprop("{PRODUCT}/etc/build.prop", "ro.lineage.build.version") == "23.2" ||
  abort("E9506: LineageOS 23.2 required. No vendor writes.");
unmount("{MOUNT}") && unmount("{PRODUCT}") ||
  abort("E9507: Temporary partitions could not be unmounted.");
'''


def script(mode, profile="custom"):
    text = version_checks()
    if profile == "samsung-dolby-baseline":
        text += '''ui_print("Samsung Dolby baseline: exact original Dolby XML, speaker policy -11 dB.");
ui_print("Not full Samsung SoundBooster/One UI audio. No Samsung DSP libraries installed.");
'''
    text += f'''package_extract_dir("tools", "{RUNTIME}") ||
  abort("E9508: Tool extraction failed.");
set_metadata_recursive("{RUNTIME}/bin", "uid", 0, "gid", 0, "fmode", 0755, "dmode", 0755);
ifelse(is_mounted("/vendor"), unmount("/vendor"));
!is_mounted("/vendor") || abort("E9509: Vendor is mounted.");
unmap_partition("vendor") || abort("E9510: Cannot recreate vendor mapping safely.");
'''
    text += f'''run_program("{RUNTIME}/bin/audio-adaptive", "checkboot",
  "/dev/block/platform/13520000.ufs/by-name/boot") == "0" ||
  abort("E9511: Boot fstab is unsupported or vendor AVB is enabled. No vendor writes.");
'''
    operation = {"apply": "replace", "restore": "reset", "preflight": "preflight"}[mode]
    text += f'''ui_print("Adaptive audio: {mode}; checking configuration and image...");
run_program("{RUNTIME}/bin/audio-adaptive", "{operation}", "--device", map_partition("vendor"),
  "-", "{RUNTIME}", "/tmp") == "0" ||
  abort("E9513: Adaptive tool refused or failed. Check recovery log. If writes started, use adaptive RESTORE before booting.");
ui_print("ADAPTIVE {mode.upper()} OK: vendor operation completed and verified.");
'''
    return text


def verified_samsung_dolby(vendor):
    source = vendor / "etc/dolby/dax-default.xml"
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != preset.ORIGINAL_HASHES[2]:
        raise ValueError("Samsung Dolby XML does not match the reviewed SM-P610 firmware")
    return payload


def templates(stage=STAGE, samsung_dolby=None):
    directory = stage / "templates"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, name in enumerate(preset.FILES):
        original = (preset.VENDOR_TREE / name).read_bytes()
        if hashlib.sha256(original).hexdigest() != preset.ORIGINAL_HASHES[index]:
            raise ValueError(f"Unsupported original XML: {name}; run prepare_rom.py")
        if name.endswith("dax-default.xml"):
            patched = preset.equalize_speakers(original)
            previous = preset.equalize_speakers(original, preset.PREVIOUS_EQ_Q4)
            previous9 = preset.equalize_speakers(original, preset.PREVIOUS9_EQ_Q4)
            previous11 = preset.equalize_speakers(original, preset.PREVIOUS11_EQ_Q4)
            previous_treble = preset.equalize_speakers(original, preset.PREVIOUS_TREBLE_EQ_Q4)
        else:
            defaults = ("audio_policy_engine_default_stream_volumes.xml"
                        if "engine" in name else "default_volume_tables.xml")
            patched = preset.attenuate_speakers(
                original, (preset.VENDOR_TREE / "etc" / defaults).read_bytes()
            )
            previous = preset.attenuate_speakers(
                original, (preset.VENDOR_TREE / "etc" / defaults).read_bytes(), 600
            )
            previous9 = preset.attenuate_speakers(
                original, (preset.VENDOR_TREE / "etc" / defaults).read_bytes(), 900
            )
            previous11 = preset.attenuate_speakers(
                original, (preset.VENDOR_TREE / "etc" / defaults).read_bytes(), 1100
            )
            previous_treble = previous11
        if hashlib.sha256(previous).hexdigest() != preset.PREVIOUS_HASHES[index]:
            raise ValueError(f"Previous preset does not match reviewed hash: {name}")
        if hashlib.sha256(previous9).hexdigest() != preset.PREVIOUS9_HASHES[index]:
            raise ValueError(f"Previous -9 dB preset does not match reviewed hash: {name}")
        if hashlib.sha256(previous11).hexdigest() != preset.PREVIOUS11_HASHES[index]:
            raise ValueError(f"Previous -11 dB preset does not match reviewed hash: {name}")
        if hashlib.sha256(previous_treble).hexdigest() != preset.PREVIOUS_TREBLE_HASHES[index]:
            raise ValueError(f"Previous treble preset does not match reviewed hash: {name}")
        if hashlib.sha256(patched).hexdigest() != preset.PREVIOUS_BASS_HASHES[index]:
            raise ValueError(f"Current bass preset does not match reviewed hash: {name}")
        previous_bass = patched
        baseline = original if name.endswith("dax-default.xml") else patched
        if samsung_dolby is not None:
            if name.endswith("dax-default.xml") and samsung_dolby != original:
                raise ValueError("Samsung and Lineage original Dolby XML differ")
            patched = baseline
        for kind, data in (("original", original), ("patched", patched),
                           ("previous", previous), ("previous9", previous9),
                           ("previous11", previous11), ("previous_treble", previous_treble),
                           ("previous_bass", previous_bass), ("baseline", baseline)):
            (directory / f"{index}.{kind}").write_bytes(data)
        manifest.append({
            "path": name,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "patched_sha256": hashlib.sha256(patched).hexdigest(),
            "previous_sha256": preset.PREVIOUS_HASHES[index],
            "previous9_sha256": preset.PREVIOUS9_HASHES[index],
            "previous11_sha256": preset.PREVIOUS11_HASHES[index],
            "previous_treble_sha256": preset.PREVIOUS_TREBLE_HASHES[index],
            "previous_bass_sha256": preset.PREVIOUS_BASS_HASHES[index],
            "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
            "decoded_bytes": len(original),
        })
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("custom", "samsung-dolby-baseline"), default="custom")
    parser.add_argument("--samsung-vendor", type=Path,
                        help="Locally extracted Samsung vendor directory, required for baseline")
    args = parser.parse_args()
    baseline = args.profile == "samsung-dolby-baseline"
    if baseline and args.samsung_vendor is None:
        parser.error("--samsung-vendor is required for samsung-dolby-baseline")
    if not baseline and args.samsung_vendor is not None:
        parser.error("--samsung-vendor applies only to samsung-dolby-baseline")
    samsung_dolby = verified_samsung_dolby(args.samsung_vendor) if baseline else None
    stage = ROOT / "build/stage-samsung-baseline" if baseline else STAGE
    output = OUTPUT / "samsung-dolby-baseline" if baseline else OUTPUT
    prefix = "audio-samsung-baseline" if baseline else "audio-adaptive"
    output.mkdir(parents=True, exist_ok=True)
    (stage / "bin").mkdir(parents=True, exist_ok=True)
    for name in ("audio-adaptive", "dump.erofs", "fsck.erofs"):
        shutil.copyfile(ROOT / "build/bin" / name, stage / "bin" / name)
        (stage / "bin" / name).chmod(0o755)
    files = templates(stage, samsung_dolby)
    packages = []
    for mode, name in (("preflight", "preflight"), ("apply", "install"), ("restore", "restore")):
        destination = output / f"{prefix}-{name}-gta4xlwifi-los23.2.zip"
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(ROOT / "build/update-binary",
                          "META-INF/com/google/android/update-binary")
            archive.writestr("META-INF/com/google/android/updater-script", script(mode, args.profile))
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, "tools/" + str(path.relative_to(stage)))
            for path in sorted((ROOT / "build/licenses").rglob("*")):
                if path.is_file():
                    archive.write(path, "LICENSES/" + str(path.relative_to(ROOT / "build/licenses")))
            for name in ("erofs.tar.gz", "lz4.tar.gz", "picosha2.h"):
                archive.write(ROOT / "third-party" / name, "SOURCES/" + name)
            archive.write(ROOT / "src/adaptive.cpp", "SOURCES/adaptive.cpp")
            archive.write(ROOT / "src/soundbooster_blocks.h", "SOURCES/soundbooster_blocks.h")
            for name in ("build_tools.py", "fetch_sources.py", "preset.py", "package.py", "prepare_rom.py"):
                archive.write(ROOT / "tools" / name, "SOURCES/tools/" + name)
            archive.write(ROOT / "docs/INSTALL.md", "INSTALL.md")
        with zipfile.ZipFile(destination) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP CRC check failed")
        packages.append({
            "file": destination.name, "sha256": preset.digest(destination),
            "bytes": destination.stat().st_size,
        })
    manifest = {
        "format": 1, "device": "gta4xlwifi / SM-P610", "lineage": "23.2",
        "android_sdk": 36,
        "profile": args.profile,
        "speaker_policy_attenuation_mb": preset.ATTENUATION_MB,
        "samsung_dolby_sha256": hashlib.sha256(samsung_dolby).hexdigest() if baseline else None,
        "soundbooster_included": False,
        "scope": ("Exact reviewed Samsung Dolby XML with -11 dB speaker policy; "
                  "not a complete One UI audio reproduction." if baseline else
                  "Experimental project EQ; not Samsung stock tuning."),
        "status": "EXPERIMENTAL local build; see docs/TESTING.md for tested scope",
        "compatibility": "Recognized original/previous/patched XML only; single 4KiB LZ4 pcluster per file; "
                         "EROFS 4KiB and no unknown incompatible features; ext4 system/product; "
                         "legacy boot v0-v2 with gzip/newc ramdisk and vendor fstab without AVB.",
        "backup": None,
        "restore": "Reset recognized audio XML to the reference ROM originals; no backup required.",
        "templates": files, "packages": packages,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "SHA256SUMS").write_text("".join(
        f"{item['sha256']}  {item['file']}\n" for item in packages
    ))
    for package in packages:
        print(f"{package['file']}: {package['bytes']} bytes; {package['sha256']}")


if __name__ == "__main__":
    main()

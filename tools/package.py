#!/usr/bin/env python3
"""Package a guarded, file-based installer; never embed an old vendor image."""

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


def script(mode):
    text = version_checks()
    text += f'''package_extract_dir("tools", "{RUNTIME}") ||
  abort("E9508: Tool extraction failed.");
set_metadata_recursive("{RUNTIME}/bin", "uid", 0, "gid", 0, "fmode", 0755, "dmode", 0755);
ifelse(is_mounted("/vendor"), unmount("/vendor"));
!is_mounted("/vendor") || abort("E9509: Vendor is mounted.");
unmap_partition("vendor") || abort("E9510: Cannot recreate vendor mapping safely.");
'''
    if mode != "restore":
        text += f'''run_program("{RUNTIME}/bin/audio-adaptive", "checkboot",
  "/dev/block/platform/13520000.ufs/by-name/boot") == "0" ||
  abort("E9511: Boot fstab is unsupported or vendor AVB is enabled. No vendor writes.");
'''
    if mode in {"apply", "restore"}:
        text += '''ifelse(!is_mounted("/cache"),
  mount("ext4", "EMMC", "/dev/block/platform/13520000.ufs/by-name/cache", "/cache", "noatime,nodev,nosuid"));
is_mounted("/cache") || abort("E9512: Persistent cache unavailable. No vendor writes.");
'''
    text += f'''ui_print("Adaptive audio: {mode}; checking configuration and image...");
run_program("{RUNTIME}/bin/audio-adaptive", "{mode}", "--device", map_partition("vendor"),
  "/cache/lineage-audio-adaptive", "{RUNTIME}", "/tmp") == "0" ||
  abort("E9513: Adaptive tool refused or failed. Check recovery log. If writes started, use adaptive RESTORE before booting.");
ui_print("ADAPTIVE {mode.upper()} OK: vendor operation completed and verified.");
'''
    return text


def templates():
    directory = STAGE / "templates"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, name in enumerate(preset.FILES):
        original = (preset.VENDOR_TREE / name).read_bytes()
        if hashlib.sha256(original).hexdigest() != preset.ORIGINAL_HASHES[index]:
            raise ValueError(f"Unsupported original XML: {name}; run prepare_rom.py")
        if name.endswith("dax-default.xml"):
            patched = preset.equalize_speakers(original)
        else:
            defaults = ("audio_policy_engine_default_stream_volumes.xml"
                        if "engine" in name else "default_volume_tables.xml")
            patched = preset.attenuate_speakers(
                original, (preset.VENDOR_TREE / "etc" / defaults).read_bytes()
            )
        for kind, data in (("original", original), ("patched", patched)):
            (directory / f"{index}.{kind}").write_bytes(data)
        manifest.append({
            "path": name,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "patched_sha256": hashlib.sha256(patched).hexdigest(),
            "decoded_bytes": len(original),
        })
    return manifest


def main():
    OUTPUT.mkdir(exist_ok=True)
    (STAGE / "bin").mkdir(parents=True, exist_ok=True)
    for name in ("audio-adaptive", "dump.erofs", "fsck.erofs"):
        shutil.copyfile(ROOT / "build/bin" / name, STAGE / "bin" / name)
        (STAGE / "bin" / name).chmod(0o755)
    files = templates()
    packages = []
    for mode, name in (("preflight", "preflight"), ("apply", "install"), ("restore", "restore")):
        destination = OUTPUT / f"audio-adaptive-{name}-gta4xlwifi-los23.2.zip"
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(ROOT / "build/update-binary",
                          "META-INF/com/google/android/update-binary")
            archive.writestr("META-INF/com/google/android/updater-script", script(mode))
            for path in sorted(STAGE.rglob("*")):
                if path.is_file():
                    archive.write(path, "tools/" + str(path.relative_to(STAGE)))
            for path in sorted((ROOT / "build/licenses").rglob("*")):
                if path.is_file():
                    archive.write(path, "LICENSES/" + str(path.relative_to(ROOT / "build/licenses")))
            for name in ("erofs.tar.gz", "lz4.tar.gz", "picosha2.h"):
                archive.write(ROOT / "third-party" / name, "SOURCES/" + name)
            archive.write(ROOT / "src/adaptive.cpp", "SOURCES/adaptive.cpp")
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
        "status": "EXPERIMENTAL local build; see docs/TESTING.md for tested scope",
        "compatibility": "Recognized original/patched XML only; single 4KiB LZ4 pcluster per file; "
                         "EROFS 4KiB and no unknown incompatible features; ext4 system/product; "
                         "legacy boot v0-v2 with gzip/newc ramdisk and vendor fstab without AVB.",
        "backup": "/cache/lineage-audio-adaptive/<original-whole-vendor-sha256>.bak",
        "templates": files, "packages": packages,
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (OUTPUT / "SHA256SUMS").write_text("".join(
        f"{item['sha256']}  {item['file']}\n" for item in packages
    ))
    for package in packages:
        print(f"{package['file']}: {package['bytes']} bytes; {package['sha256']}")


if __name__ == "__main__":
    main()

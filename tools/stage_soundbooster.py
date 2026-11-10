#!/usr/bin/env python3
"""Build and audit an offline EROFS integration candidate. Never access a device."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import stat
import struct
import subprocess
import tarfile
import tempfile

import configure_soundbooster as configuration
import prepare_rom
import probe_soundbooster as probe
from preset import FILES, ORIGINAL_HASHES, attenuate_speakers, validate_curves

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = "/lib/soundfx/lib_SoundBooster_ver1050.so"
BRIDGE_PATH = "/lib/soundfx/libadaptive_soundbooster.so"
PARAMETER_PATH = "/etc/adaptive-soundbooster.bin"
EFFECTS_PATH = "/etc/audio_effects.xml"
NEW_PATHS = {ENGINE_PATH, BRIDGE_PATH, PARAMETER_PATH}


def run(*arguments):
    result = subprocess.run([str(value) for value in arguments], capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"Command failed: {arguments}\n"
                           f"{result.stdout.decode(errors='replace')}\n"
                           f"{result.stderr.decode(errors='replace')}")
    return result.stdout


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def audit(tool, image):
    result = {}
    for line in run(tool, image).decode("ascii").splitlines():
        record = json.loads(line)
        path = bytes.fromhex(record.pop("path_hex")).decode("utf-8")
        if path in result or (path and (not path.startswith("/") or ".." in path.split("/"))):
            raise ValueError("Invalid or duplicate audited path")
        result[path] = record
    if "" not in result:
        raise ValueError("Missing audited root directory")
    return result


def verify_delta(original, candidate, payloads, donors):
    if set(candidate) != set(original) | NEW_PATHS or NEW_PATHS & set(original):
        raise ValueError("Unexpected filesystem path additions/removals")
    for path, before in original.items():
        after = candidate[path]
        ignored = {"nid"}
        if stat.S_ISDIR(before["mode"]):
            ignored.add("size")
        if path in payloads:
            ignored |= {"size", "sha256"}
        if {key: value for key, value in before.items() if key not in ignored} != {
                key: value for key, value in after.items() if key not in ignored}:
            raise ValueError(f"Unintended content or metadata change: {path or '/'}")
    for path, payload in payloads.items():
        after = candidate[path]
        if after["sha256"] != hashlib.sha256(payload).hexdigest() or after["size"] != len(payload):
            raise ValueError(f"Incorrect staged payload: {path}")
        if path in NEW_PATHS:
            donor = original[donors[path]]
            if any(after[key] != donor[key] for key in ("mode", "uid", "gid", "mtime", "mtime_nsec", "xattrs")):
                raise ValueError(f"Incorrect new file permissions/security label: {path}")
            if after["nlink"] != 1:
                raise ValueError("Unexpected new hardlink")
    groups = {}
    for path, record in original.items():
        if not stat.S_ISDIR(record["mode"]):
            groups.setdefault(record["nid"], set()).add(path)
    candidate_groups = {}
    for path, record in candidate.items():
        if not stat.S_ISDIR(record["mode"]):
            candidate_groups.setdefault(record["nid"], set()).add(path)
    if {frozenset(paths) for paths in groups.values()} != {
            frozenset(paths) for paths in candidate_groups.values() if not paths & NEW_PATHS}:
        raise ValueError("Original hardlink topology changed")


def filesystem_layout(image):
    with image.open("rb") as source:
        source.seek(1024)
        superblock = source.read(128)
    if len(superblock) != 128 or superblock[:4] != b"\xe2\xe1\xf5\xe0" or superblock[12] != 12:
        raise ValueError("Unsupported EROFS geometry")
    layout = {
        "compatible_features": struct.unpack_from("<I", superblock, 8)[0],
        "incompatible_features": struct.unpack_from("<I", superblock, 80)[0],
        "data_bytes": struct.unpack_from("<I", superblock, 36)[0] * 4096,
    }
    if not 4096 <= layout["data_bytes"] <= image.stat().st_size:
        raise ValueError("Invalid EROFS data extent")
    return layout


def make_full_archive(target, payloads, original, donors, dump_tool, image):
    seen = {}
    with tarfile.open(target, "x", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(set(original) | set(payloads)):
            metadata = original[donors.get(path, path)]
            if metadata["mtime_nsec"]:
                raise ValueError("Fractional timestamps require explicit review")
            info = tarfile.TarInfo(path.lstrip("/") or ".")
            info.mode = stat.S_IMODE(metadata["mode"])
            info.uid, info.gid, info.mtime = metadata["uid"], metadata["gid"], metadata["mtime"]
            info.pax_headers = {
                "SCHILY.xattr." + bytes.fromhex(name).decode("ascii"):
                bytes.fromhex(value).decode("utf-8")
                for name, value in metadata["xattrs"].items()
            }
            if stat.S_ISDIR(metadata["mode"]):
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
                continue
            if path not in payloads and metadata["nid"] in seen:
                info.type = tarfile.LNKTYPE
                info.linkname = seen[metadata["nid"]]
                archive.addfile(info)
                continue
            payload = payloads.get(path)
            if payload is None:
                payload = run(dump_tool, "--cat", "--path=" + path, image)
                if hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
                    raise ValueError("Decoded source changed during archival")
            if stat.S_ISLNK(metadata["mode"]):
                info.type = tarfile.SYMTYPE
                info.linkname = payload.decode("utf-8")
                archive.addfile(info)
            elif stat.S_ISREG(metadata["mode"]):
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            else:
                raise ValueError("Unsupported archive inode type")
            if path not in NEW_PATHS:
                seen[metadata["nid"]] = info.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True, help="Exact reference vendor regular image")
    parser.add_argument("--vendor", type=Path, required=True, help="Locally extracted Samsung vendor")
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--host-tools", type=Path, default=ROOT / "build/host-bin")
    parser.add_argument("--output", type=Path, required=True, help="New nonexistent local output directory")
    parser.add_argument("--prepare-partition", action="store_true",
                        help="After filesystem audit, regenerate original AVB/FEC locally; not an installer")
    parser.add_argument("--speaker-attenuation-mb", type=int, choices=(700, 900, 1100),
                        default=700, help="Reviewed speaker policy reduction; final default 700")
    args = parser.parse_args()
    if args.image.is_symlink() or not args.image.is_file() or sha256(args.image) != prepare_rom.REFERENCE_VENDOR_SHA256:
        raise ValueError("Only the exact reference vendor regular file is accepted")
    engine = args.vendor / "lib/lib_SoundBooster_ver1050.so"
    if sha256(engine) != probe.ENGINE32_SHA256:
        raise ValueError("Unreviewed ARM32 engine")
    parameters = probe.parameter_payload((args.vendor / "etc/SoundBoosterParam.txt").read_bytes())
    original = audit(args.host_tools / "erofs-manifest", args.image)
    original_layout = filesystem_layout(args.image)
    original_effects = run(args.host_tools / "dump.erofs", "--cat", "--path=" + EFFECTS_PATH, args.image)
    modified_effects = configuration.candidate(original_effects)
    host = {"Darwin": "darwin-x86_64", "Linux": "linux-x86_64"}[platform.system()]
    toolchain = args.ndk / "toolchains/llvm/prebuilt" / host
    args.output.mkdir(parents=True, exist_ok=False)
    bridge = args.output / "libadaptive_soundbooster.so"
    vendor_runtime = args.output / "libc++.so"
    vendor_runtime.write_bytes(run(args.host_tools / "dump.erofs", "--cat",
                                   "--path=/lib/libc++.so", args.image))
    vendor_link = probe.vendor_runtime_import(
        toolchain, "armv7a-linux-androideabi29", vendor_runtime,
        args.output / "vendor-runtime-import.so", "/vendor" + ENGINE_PATH)
    run(toolchain / "bin/armv7a-linux-androideabi29-clang++", "-std=c++17", "-O2",
        "-Wall", "-Wextra", "-Werror", "-fstack-protector-strong", "-fPIC", "-shared",
        "-fvisibility=hidden", "-static-libstdc++", "-Wl,-z,relro,-z,now",
        "-Wl,--version-script=" + str(ROOT / "src/soundbooster_static.map"),
        "-Wl,--strip-all,--gc-sections",
        '-DSB_ENGINE_PATH="/vendor' + ENGINE_PATH + '"',
        '-DSB_ENGINE_HASH="' + probe.ENGINE32_SHA256 + '"',
        '-DSB_PARAMETER_PATH="/vendor' + PARAMETER_PATH + '"',
        '-DSB_PARAMETER_HASH="' + hashlib.sha256(parameters).hexdigest() + '"',
        ROOT / "src/soundbooster_effect.cpp", "-o", bridge, "-ldl", "-lm", "-llog", *vendor_link)
    dependencies = run(toolchain / "bin/llvm-readelf", "--dynamic", bridge).decode()
    for path in (probe.VENDOR_RUNTIME_PATH, "/vendor" + ENGINE_PATH):
        if dependencies.count("[" + path + "]") != 1:
            raise ValueError("Missing pinned local-group dependency: " + path)
    payloads = {ENGINE_PATH: engine.read_bytes(), BRIDGE_PATH: bridge.read_bytes(),
                PARAMETER_PATH: parameters, EFFECTS_PATH: modified_effects}
    for path, expected in zip(FILES[:2], ORIGINAL_HASHES[:2]):
        default_name = ("audio_policy_engine_default_stream_volumes.xml"
                        if "engine" in path else "default_volume_tables.xml")
        defaults = run(args.host_tools / "dump.erofs", "--cat",
                       "--path=/etc/" + default_name, args.image)
        original_policy = run(args.host_tools / "dump.erofs", "--cat", "--path=/" + path, args.image)
        if hashlib.sha256(original_policy).hexdigest() != expected:
            raise ValueError("Unexpected original speaker volume policy")
        payloads["/" + path] = attenuate_speakers(original_policy, defaults, args.speaker_attenuation_mb)
        validate_curves(original_policy, payloads["/" + path], defaults, args.speaker_attenuation_mb)
    donors = {ENGINE_PATH: "/lib/soundfx/libswdap.so", BRIDGE_PATH: "/lib/soundfx/libswdap.so",
              PARAMETER_PATH: EFFECTS_PATH}
    if {(record["mtime"], record["mtime_nsec"]) for record in original.values()} != {(1230768000, 0)}:
        raise ValueError("Unreviewed reference timestamps")
    filesystem = args.output / "filesystem-candidate.erofs"
    with tempfile.TemporaryDirectory(prefix="archive-", dir=args.output) as temporary:
        archive = Path(temporary) / "filesystem.tar"
        make_full_archive(archive, payloads, original, donors, args.host_tools / "dump.erofs", args.image)
        run(args.host_tools / "mkfs.erofs", "-b4096", "--tar=f",
            "-T1230768000",
            "-z", "lz4hc,level=12", "-C4096", "--max-extent-bytes=1048576",
            filesystem, archive)
    run(args.host_tools / "fsck.erofs", "--extract", filesystem)
    after = audit(args.host_tools / "erofs-manifest", filesystem)
    verify_delta(original, after, payloads, donors)
    candidate_layout = filesystem_layout(filesystem)
    for key in ("compatible_features", "incompatible_features"):
        if original_layout[key] != candidate_layout[key]:
            raise ValueError("EROFS feature set changed; kernel compatibility not established")
    for name, records in (("original", original), ("candidate", after)):
        (args.output / (name + "-manifest.json")).write_text(json.dumps(records, indent=2) + "\n")
    (args.output / "result.json").write_text(json.dumps({
        "format": 1, "scope": "Offline filesystem audit only; not a vendor image or installation package",
        "original_sha256": sha256(args.image), "candidate_filesystem_sha256": sha256(filesystem),
        "original_entries": len(original), "candidate_entries": len(after),
        "payload_paths": sorted(payloads), "unrelated_contents_and_metadata_preserved": True,
        "service_activation_verified": False, "device_installation_verified": False,
        "avb_regeneration_required_before_installation": True,
        "original_partition_bytes": args.image.stat().st_size,
        "original_filesystem_bytes": original_layout["data_bytes"],
        "candidate_filesystem_bytes": candidate_layout["data_bytes"],
        "fits_original_data_region": candidate_layout["data_bytes"] <= original_layout["data_bytes"],
        "rollback_verified": False,
        "speaker_attenuation_mb": args.speaker_attenuation_mb,
        "dolby_configuration": "byte-identical to reference; experimental EQ not included",
    }, indent=2) + "\n")
    if args.prepare_partition:
        import soundbooster_avb
        soundbooster_avb.prepare(args.image, filesystem, args.output / "partition", args.host_tools)
        print("Offline partition AVB/FEC verified. Recovery rollback and real-service tests still required.")
        return
    elif candidate_layout["data_bytes"] > original_layout["data_bytes"]:
        raise ValueError("Filesystem audit passed, but candidate exceeds original data region by "
                         f"{candidate_layout['data_bytes'] - original_layout['data_bytes']} bytes. "
                         "See result.json. No vendor image created; AVB area must not be overwritten.")
    print("Offline filesystem audit passed. AVB regeneration, rollback and service tests still required.")


if __name__ == "__main__":
    main()

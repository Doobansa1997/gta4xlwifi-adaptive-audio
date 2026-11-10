"""Offline AVB/FEC regeneration for the exact reviewed vendor; never touch devices."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import prepare_rom
import image_delta
from preset import digest as sha256

ROOT = Path(__file__).resolve().parents[1]
AVB_SHA256 = "fc5332131a907ae22978e16a84fa12a14d277a60d8e2ad77c31a0097dafeb657"


def load_avb(path):
    if path.is_symlink() or not path.is_file() or sha256(path) != AVB_SHA256:
        raise ValueError("Unreviewed avbtool source")
    spec = importlib.util.spec_from_file_location("pinned_avbtool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata(module, path):
    image = module.ImageHandler(str(path), read_only=True)
    try:
        footer, header, descriptors, size = module.Avb()._parse_image(image)
        if footer is None:
            raise ValueError("Missing partition AVB footer")
        trees = [item for item in descriptors if isinstance(item, module.AvbHashtreeDescriptor)]
        properties = [item for item in descriptors if isinstance(item, module.AvbPropertyDescriptor)]
        if len(trees) != 1 or len(trees) + len(properties) != len(descriptors):
            raise ValueError("Unreviewed AVB descriptor layout")
        tree = trees[0]
        result = {
            "partition_bytes": size,
            "original_image_size": footer.original_image_size,
            "vbmeta_offset": footer.vbmeta_offset,
            "vbmeta_size": footer.vbmeta_size,
            "algorithm_type": header.algorithm_type,
            "flags": header.flags,
            "rollback_index": header.rollback_index,
            "rollback_index_location": header.rollback_index_location,
            "release_string": header.release_string,
            "required_version": [header.required_libavb_version_major, header.required_libavb_version_minor],
            "properties": [[item.key, item.value.decode("utf-8")] for item in properties],
        }
        for key in ("dm_verity_version", "image_size", "tree_offset", "tree_size",
                    "data_block_size", "hash_block_size", "fec_num_roots", "fec_offset",
                    "fec_size", "hash_algorithm", "partition_name", "flags"):
            result["tree_" + key] = getattr(tree, key)
        result["tree_salt"] = tree.salt.hex()
        result["tree_root_digest"] = tree.root_digest.hex()
        if (result["algorithm_type"] != 0 or result["flags"] != 0 or
                result["tree_flags"] != 0 or result["tree_fec_num_roots"] != 2 or
                result["tree_hash_algorithm"] != "sha1" or result["tree_partition_name"] != "vendor" or
                result["tree_data_block_size"] != 4096 or result["tree_hash_block_size"] != 4096 or
                result["tree_dm_verity_version"] != 1):
            raise ValueError("Unsupported AVB policy; signing/verification settings will not be changed")
        if not (result["original_image_size"] == result["tree_image_size"] == result["tree_tree_offset"] and
                result["tree_tree_offset"] + result["tree_tree_size"] == result["tree_fec_offset"] and
                result["tree_fec_offset"] + result["tree_fec_size"] <= result["vbmeta_offset"] and
                result["vbmeta_offset"] + result["vbmeta_size"] <= size - 64):
            raise ValueError("Invalid AVB region bounds")
        return result
    finally:
        image._image.close()


def command(avb_path, tools, *arguments):
    env = os.environ.copy()
    env["PATH"] = str(tools.resolve()) + os.pathsep + env.get("PATH", "")
    result = subprocess.run([sys.executable, str(avb_path), *map(str, arguments)],
                            env=env, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"AVB command failed: {arguments}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def footer_arguments(reference):
    arguments = [
        "--partition_size", str(reference["partition_bytes"]), "--partition_name", "vendor",
        "--hash_algorithm", reference["tree_hash_algorithm"], "--salt", reference["tree_salt"],
        "--block_size", str(reference["tree_data_block_size"]), "--fec_num_roots", "2",
        "--algorithm", "NONE", "--rollback_index", str(reference["rollback_index"]),
        "--rollback_index_location", str(reference["rollback_index_location"]),
    ]
    for key, value in reference["properties"]:
        arguments += ["--prop", key + ":" + value]
    return arguments


def copy_prefix(source, target, size):
    with source.open("rb") as reader, target.open("xb") as writer:
        remaining = size
        while remaining:
            chunk = reader.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("Short source image")
            writer.write(chunk)
            remaining -= len(chunk)


def verify_fec(image, description, tools, temporary):
    prefix, parity = temporary / "protected.raw", temporary / "parity.raw"
    copy_prefix(image, prefix, description["tree_fec_offset"])
    result = subprocess.run([str((tools / "fec").resolve()), "--encode", "--roots", "2",
                             str(prefix), str(parity)], capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError("FEC regeneration failed: " + result.stderr.decode(errors="replace"))
    data = parity.read_bytes()
    size = description["tree_fec_size"]
    if len(data) != size + 4096:
        raise ValueError("Incorrect regenerated FEC size")
    with image.open("rb") as source:
        source.seek(description["tree_fec_offset"])
        if source.read(size) != data[:size]:
            raise ValueError("FEC parity mismatch")
    prefix.unlink()
    parity.unlink()


def prepare(reference, filesystem, output, tools, avb_path=ROOT / "third-party/avbtool.py"):
    for path in (reference, filesystem):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Offline images must be regular, non-symlink files")
    if sha256(reference) != prepare_rom.REFERENCE_VENDOR_SHA256:
        raise ValueError("Only exact reference vendor AVB settings are accepted")
    module = load_avb(avb_path)
    original = metadata(module, reference)
    arguments = footer_arguments(original)
    maximum = int(command(avb_path, tools, "add_hashtree_footer", *arguments, "--calc_max_image_size"))
    if filesystem.stat().st_size > maximum or filesystem.stat().st_size % 4096:
        raise ValueError("Candidate filesystem does not fit unchanged partition with AVB/FEC")
    output.mkdir(exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="reference-proof-", dir=output) as temporary:
        proof = Path(temporary) / "vendor.img"
        copy_prefix(reference, proof, original["original_image_size"])
        command(avb_path, tools, "add_hashtree_footer", "--image", proof, *arguments)
        if sha256(proof) != sha256(reference):
            raise ValueError("AVB/FEC generator did not reproduce exact original partition bytes")
        command(avb_path, tools, "verify_image", "--image", proof)
    candidate = output / "vendor.img"
    shutil.copyfile(filesystem, candidate)
    command(avb_path, tools, "add_hashtree_footer", "--image", candidate, *arguments)
    verified = command(avb_path, tools, "verify_image", "--image", candidate)
    updated = metadata(module, candidate)
    variable = {"original_image_size", "vbmeta_offset", "tree_image_size", "tree_tree_offset",
                "tree_tree_size", "tree_fec_offset", "tree_fec_size", "tree_root_digest"}
    if {key: value for key, value in original.items() if key not in variable} != {
            key: value for key, value in updated.items() if key not in variable}:
        raise ValueError("Unexpected AVB security-policy/metadata change")
    if updated["original_image_size"] != filesystem.stat().st_size:
        raise ValueError("Candidate AVB protects an unexpected data extent")
    with tempfile.TemporaryDirectory(prefix="fec-proof-", dir=output) as temporary:
        verify_fec(candidate, updated, tools, Path(temporary))
    with candidate.open("rb") as source:
        digest = hashlib.sha256()
        remaining = filesystem.stat().st_size
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("Truncated generated candidate")
            digest.update(chunk)
            remaining -= len(chunk)
    if digest.hexdigest() != sha256(filesystem):
        raise ValueError("AVB generation changed filesystem contents")
    rollback = image_delta.prove(reference, candidate, output / "offline-reversible-blocks.zip")
    report = {
        "format": 1, "scope": "Offline partition experiment only; not a recovery installer",
        "reference_sha256": sha256(reference), "candidate_sha256": sha256(candidate),
        "candidate_filesystem_sha256": sha256(filesystem),
        "original_avb": original, "candidate_avb": updated,
        "maximum_filesystem_bytes": maximum,
        "reference_regeneration_byte_exact": True,
        "avb_hashtree_verified": True, "fec_parity_verified": True,
        "filesystem_bytes_preserved": True,
        "rollback_verified": False, "actual_audio_service_verified": False,
        "local_rollback": rollback,
        "device_writes_performed": False,
    }
    (output / "avb-verification.txt").write_text(verified)
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report

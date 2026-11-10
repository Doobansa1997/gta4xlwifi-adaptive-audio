"""Reversible block experiments on local regular files only, not a recovery installer."""

import fcntl
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
import zipfile
from preset import digest as file_hash

BLOCK = 4096
MAXIMUM = 1024 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path, writable=False):
    fd = os.open(path, (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAXIMUM or info.st_size % BLOCK:
            raise ValueError("Only bounded, block-aligned regular image files are accepted")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return os.fdopen(fd, "r+b" if writable else "rb")
    except BaseException:
        os.close(fd)
        raise


def create(original, candidate, bundle):
    records = []
    original_hash, candidate_hash = hashlib.sha256(), hashlib.sha256()
    with regular(original) as before, regular(candidate) as after:
        if os.fstat(before.fileno()).st_size != os.fstat(after.fileno()).st_size:
            raise ValueError("Partition size changes are not allowed")
        with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            # Separate streams avoid retaining firmware-sized payloads in memory.
            with archive.open("before.bin", "w") as payload:
                while True:
                    old, new = before.read(BLOCK), after.read(BLOCK)
                    if not old and not new:
                        break
                    if len(old) != BLOCK or len(new) != BLOCK:
                        raise ValueError("Image changed during delta creation")
                    original_hash.update(old)
                    candidate_hash.update(new)
                    records.append([digest(old), digest(new)])
                    if old != new:
                        payload.write(old)
            after.seek(0)
            with archive.open("after.bin", "w") as payload:
                for old_hash, new_hash in records:
                    new = after.read(BLOCK)
                    if digest(new) != new_hash:
                        raise ValueError("Candidate changed during delta creation")
                    if old_hash != new_hash:
                        payload.write(new)
            if not any(old != new for old, new in records):
                raise ValueError("No changed blocks")
            manifest = {
                "format": 1, "scope": "Offline reversible blocks only; not flashable",
                "block_bytes": BLOCK, "image_bytes": len(records) * BLOCK,
                "before_sha256": original_hash.hexdigest(), "after_sha256": candidate_hash.hexdigest(),
                "blocks": records,
            }
            archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")) + "\n")
    return manifest


def apply(bundle, target, restore=False):
    with zipfile.ZipFile(bundle) as archive:
        if sorted(archive.namelist()) != ["after.bin", "before.bin", "manifest.json"]:
            raise ValueError("Invalid offline delta members")
        if archive.getinfo("manifest.json").file_size > 40 * 1024 * 1024:
            raise ValueError("Oversized delta manifest")
        manifest = json.loads(archive.read("manifest.json"))
        size = manifest.get("image_bytes")
        if (manifest.get("format") != 1 or manifest.get("block_bytes") != BLOCK or
                type(size) is not int or not 0 < size <= MAXIMUM or size % BLOCK):
            raise ValueError("Invalid delta geometry")
        records = manifest.get("blocks")
        if not isinstance(records, list) or len(records) != size // BLOCK:
            raise ValueError("Invalid delta block count")
        for pair in records:
            if (not isinstance(pair, list) or len(pair) != 2 or any(
                    not isinstance(value, str) or len(value) != 64 or
                    any(char not in "0123456789abcdef" for char in value) for value in pair)):
                raise ValueError("Invalid block hashes")
        payload_bytes = sum(old != new for old, new in records) * BLOCK
        if any(archive.getinfo(name).file_size != payload_bytes for name in ("before.bin", "after.bin")):
            raise ValueError("Invalid delta payload lengths")
        with regular(target, writable=True) as image:
            if os.fstat(image.fileno()).st_size != size:
                raise ValueError("Target image size differs")
            before_hash, after_hash = hashlib.sha256(), hashlib.sha256()
            with archive.open("before.bin") as before, archive.open("after.bin") as after:
                for old_hash, new_hash in records:
                    current = image.read(BLOCK)
                    if digest(current) not in (old_hash, new_hash):
                        raise ValueError("Unknown block state; no image writes performed")
                    if old_hash != new_hash:
                        old, new = before.read(BLOCK), after.read(BLOCK)
                        if digest(old) != old_hash or digest(new) != new_hash:
                            raise ValueError("Corrupt delta payload; no image writes performed")
                    else:
                        old = new = current
                    before_hash.update(old)
                    after_hash.update(new)
            if (before_hash.hexdigest() != manifest.get("before_sha256") or
                    after_hash.hexdigest() != manifest.get("after_sha256")):
                raise ValueError("Invalid whole-image identities; no image writes performed")
            image.seek(0)
            desired_name = "before.bin" if restore else "after.bin"
            with archive.open(desired_name) as desired:
                for index, (old_hash, new_hash) in enumerate(records):
                    if old_hash != new_hash:
                        payload = desired.read(BLOCK)
                        expected = old_hash if restore else new_hash
                        if digest(payload) != expected:
                            raise ValueError("Delta changed after preflight; restoration is required")
                        image.seek(index * BLOCK)
                        if image.write(payload) != BLOCK:
                            raise OSError("Short image write; restoration is required")
            image.flush()
            os.fsync(image.fileno())
            image.seek(0)
            actual = hashlib.file_digest(image, "sha256").hexdigest()
            expected = manifest["before_sha256" if restore else "after_sha256"]
            if actual != expected:
                raise ValueError("Post-write identity mismatch; restoration is required")
            return actual


def prove(original, candidate, bundle):
    manifest = create(original, candidate, bundle)
    with tempfile.TemporaryDirectory(prefix="rollback-proof-", dir=bundle.parent) as temporary:
        image = Path(temporary) / "simulation.img"
        shutil.copyfile(original, image)
        apply(bundle, image)
        apply(bundle, image)
        apply(bundle, image, restore=True)
        with regular(image, writable=True) as mixed, regular(candidate) as after:
            for index, (old_hash, new_hash) in enumerate(manifest["blocks"]):
                if index % 2 == 0 and old_hash != new_hash:
                    after.seek(index * BLOCK)
                    mixed.seek(index * BLOCK)
                    mixed.write(after.read(BLOCK))
        apply(bundle, image, restore=True)
        with regular(image, writable=True) as unknown:
            changed = bytearray(unknown.read(BLOCK))
            changed[0] ^= 0x80
            if digest(changed) in manifest["blocks"][0]:
                raise ValueError("Corruption fixture unexpectedly matches known block")
            unknown.seek(0)
            unknown.write(changed)
        before_rejection = file_hash(image)
        try:
            apply(bundle, image, restore=True)
        except ValueError as error:
            if "Unknown block state" not in str(error):
                raise
        else:
            raise ValueError("Unknown image was not rejected")
        if file_hash(image) != before_rejection:
            raise ValueError("Unknown image was changed before refusal")
    return {
        "bundle_sha256": file_hash(bundle),
        "changed_blocks": sum(old != new for old, new in manifest["blocks"]),
        "block_bytes": BLOCK, "image_bytes": manifest["image_bytes"],
        "reference_sha256": manifest["before_sha256"], "candidate_sha256": manifest["after_sha256"],
        "local_apply_and_exact_restore_verified": True,
        "idempotent_apply_verified": True,
        "mixed_original_candidate_block_restore_verified": True,
        "unknown_block_rejected_without_writes": True,
        "recovery_execution_verified": False,
    }

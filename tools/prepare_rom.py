#!/usr/bin/env python3
"""Prepare private build inputs from a locally supplied, verified official full OTA."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from preset import BUILD, FILES, ORIGINAL_HASHES, VENDOR_TREE, digest

REFERENCE_ROM_SHA256 = "3c8fffba1139086d931cfcdb7936ecdec309056747ae28ee93765352b77da96a"
REFERENCE_VENDOR_SHA256 = "278862bb89de2057e6fb78b9fd19bb5840762369ad7752cc02a0b49960d9beea"
BLOCK = 4096
MAX_BLOCKS = 2 * 1024 * 1024 * 1024 // BLOCK


def extract_vendor(archive, directory):
    lines = archive.read("vendor.transfer.list").decode("ascii").splitlines()
    if len(lines) < 5 or lines[0] != "4" or lines[2:4] != ["0", "0"]:
        raise ValueError("Only stash-free full-OTA transfer lists v4 are supported")
    total_blocks = int(lines[1])
    if not 0 < total_blocks <= MAX_BLOCKS:
        raise ValueError("Vendor block count out of bounds")
    compressed = directory / "vendor.new.dat.br"
    with archive.open("vendor.new.dat.br") as source, compressed.open("wb") as target:
        shutil.copyfileobj(source, target)
    data = directory / "vendor.new.dat"
    with data.open("wb") as target:
        subprocess.run(["brotli", "-d", "-c", str(compressed)], stdout=target, check=True)
    if data.stat().st_size != total_blocks * BLOCK:
        raise ValueError("Vendor data size mismatch")
    image = directory / "vendor.img"
    written = set()
    with data.open("rb") as source, image.open("w+b") as target:
        for line in lines[4:]:
            operation, ranges = line.split()
            if operation != "new":
                raise ValueError("Reference vendor must contain only new blocks")
            numbers = [int(value) for value in ranges.split(",")]
            if numbers[0] != len(numbers) - 1 or numbers[0] % 2:
                raise ValueError("Invalid transfer range set")
            for start, end in zip(numbers[1::2], numbers[2::2]):
                if not 0 <= start < end <= MAX_BLOCKS:
                    raise ValueError("Transfer range out of bounds")
                blocks = set(range(start, end))
                if blocks & written:
                    raise ValueError("Overlapping vendor ranges")
                written.update(blocks)
                target.seek(start * BLOCK)
                length = (end - start) * BLOCK
                payload = source.read(length)
                if len(payload) != length:
                    raise ValueError("Truncated vendor data")
                target.write(payload)
        if source.read(1) or written != set(range(total_blocks)):
            raise ValueError("Incomplete/noncontiguous reference vendor")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True, help="Local official 20261107 full OTA ZIP")
    args = parser.parse_args()
    if digest(args.rom) != REFERENCE_ROM_SHA256:
        raise ValueError("Use the documented official reference ROM; SHA256 mismatch")
    BUILD.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=BUILD) as temporary:
        directory = Path(temporary)
        with zipfile.ZipFile(args.rom) as archive:
            image = extract_vendor(archive, directory)
            if digest(image) != REFERENCE_VENDOR_SHA256:
                raise ValueError("Reconstructed vendor checksum mismatch")
            subprocess.run(["fsck.erofs", "--extract", str(image)], check=True)
            inputs = directory / "inputs"
            inputs.mkdir()
            for name in (*FILES, "etc/default_volume_tables.xml",
                         "etc/audio_policy_engine_default_stream_volumes.xml"):
                destination = inputs / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output:
                    subprocess.run(["dump.erofs", "--cat", f"--path=/{name}", str(image)],
                                   stdout=output, check=True)
            for name, expected in zip(FILES, ORIGINAL_HASHES):
                if digest(inputs / name) != expected:
                    raise ValueError(f"Unsupported original XML: {name}")
            shutil.copytree(inputs, VENDOR_TREE, dirs_exist_ok=True)
            shutil.copyfile(image, BUILD / "reference-vendor.img")
            for entry, name in (
                ("boot.img", "reference-boot.img"),
                ("META-INF/com/google/android/update-binary", "update-binary"),
            ):
                with archive.open(entry) as source, (BUILD / name).open("wb") as target:
                    shutil.copyfileobj(source, target)
    metadata = {
        "rom_sha256": REFERENCE_ROM_SHA256,
        "vendor_sha256": REFERENCE_VENDOR_SHA256,
        "updater_sha256": digest(BUILD / "update-binary"),
    }
    (BUILD / "inputs.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("Private local inputs verified. Do not commit build/ or distribute vendor templates.")


if __name__ == "__main__":
    main()

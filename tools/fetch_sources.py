#!/usr/bin/env python3
"""Download pinned public build dependencies; never download firmware."""

import hashlib
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
THIRD = ROOT / "third-party"
SOURCES = {
    "erofs.tar.gz": (
        "https://api.github.com/repos/erofs/erofs-utils/tarball/f36cadb5c563995ab3aa8572a60ed6b721b9557d",
        "2e105d4b0798d76b713ba2d315992c82980c842acb228b42fcec4ffe28710a97",
    ),
    "lz4.tar.gz": (
        "https://api.github.com/repos/lz4/lz4/tarball/ebb370ca83af193212df4dcbadcc5d87bc0de2f0",
        "235f3d43bebb0a471c428030bdc847fe39a408af73e0e63562bce7950dc60a65",
    ),
    "picosha2.h": (
        "https://raw.githubusercontent.com/okdshin/PicoSHA2/161cb3fc4170fa7a3eca9e582cebd27cc4d1fe29/picosha2.h",
        "b13c180161ffac8d0adc81e033e493c409457c4d1258ab9781ac80579ba3bdd8",
    ),
}


def main():
    THIRD.mkdir(exist_ok=True)
    for name, (url, checksum) in SOURCES.items():
        target = THIRD / name
        if not target.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "gta4xlwifi-adaptive-audio"})
            with urllib.request.urlopen(request, timeout=60) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != checksum:
                raise ValueError(f"Downloaded source checksum mismatch: {name}")
            target.write_bytes(content)
        if hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Source checksum mismatch: {name}; remove only that file and retry")
        if name.endswith(".tar.gz"):
            directory = "erofs-erofs-utils-f36cadb" if name.startswith("erofs") else "lz4-lz4-ebb370c"
            if not (THIRD / directory).exists():
                with tarfile.open(target) as archive:
                    archive.extractall(THIRD, filter="data")
        print(f"Verified {name}")


if __name__ == "__main__":
    main()

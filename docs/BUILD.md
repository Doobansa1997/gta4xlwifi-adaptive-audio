# Build locally

## Requirements

Tested development host: macOS Apple Silicon, Python 3.15 and Android NDK
`28.2.13676358`. Python **3.11+** is required. Linux host tests also run in CI;
Linux NDK cross-building is supported by the script but not device-validated.
Windows is not supported directly.

Install only missing tools. Example package lists:

```sh
# macOS
brew install python erofs-utils brotli autoconf automake libtool pkgconf

# Debian/Ubuntu
sudo apt-get install build-essential python3 erofs-utils brotli \
    autoconf automake libtool pkg-config zlib1g-dev
```

Install Android NDK 28.2 through your normal Android SDK setup, then set:

```sh
export ANDROID_NDK_HOME="/absolute/path/to/ndk/28.2.13676358"
```

No root privileges are needed for compilation or host tests.

## 1. Download public source dependencies

```sh
python3 tools/fetch_sources.py
```

This fetches pinned erofs-utils 1.9.4, LZ4 1.10.0 and PicoSHA2, verifies
SHA256 and extracts them using Python's restricted tar-data filter.
No firmware is downloaded. Sources go into ignored `third-party/`.

If GitHub regenerates a source archive with different bytes, the build will
stop. Review the upstream commit/archive before updating its checksum;
do not bypass verification.

## 2. Run public synthetic tests

```sh
python3 tools/build_tools.py --host-only
python3 -m unittest discover -s tests -v
```

These tests build synthetic EROFS and boot fixtures, then check file-image
apply/restore and failures without requiring or redistributing firmware.

## 3. Supply the official reference ROM locally

Obtain `lineage-23.2-20261107-nightly-gta4xlwifi-signed.zip` through the
[official device download page](https://download.lineageos.org/devices/gta4xlwifi/builds).
Verify its SHA256 against the official listing:

```text
3c8fffba1139086d931cfcdb7936ecdec309056747ae28ee93765352b77da96a
```

Place it outside Git or in ignored `inputs/`. The project does not mirror
that ROM. If the build is no longer available officially, do not substitute
an untrusted download or disable the checksum guard.

```sh
python3 tools/prepare_rom.py --rom /absolute/path/to/reference-ROM.zip
```

The script reconstructs **only vendor**, checks its SHA256, reads five
configuration files, and extracts the official boot and update-binary.
It supports the reference full-OTA v4 `new` transfer format, not incremental
or A/B payload packages. Inputs stay in ignored `build/`.

Expected original vendor SHA256:

```text
278862bb89de2057e6fb78b9fd19bb5840762369ad7752cc02a0b49960d9beea
```

## 4. Compile Android ARM64 tools

```sh
python3 tools/build_tools.py
```

The tools are built statically for ARM64 Android API 28. NDK paths are supplied
via the environment, not embedded in source. `configure` is generated locally
with autotools. LZ4 support is explicitly required: a build without it fails
rather than producing an unusable filesystem checker.

## 5. Generate local packages

```sh
python3 tools/package.py
cd dist
shasum -a 256 -c SHA256SUMS     # macOS; Linux: sha256sum -c SHA256SUMS
```

Outputs:

- `audio-adaptive-preflight-gta4xlwifi-los23.2.zip`
- `audio-adaptive-install-gta4xlwifi-los23.2.zip`
- `audio-adaptive-restore-gta4xlwifi-los23.2.zip`
- `manifest.json` and `SHA256SUMS`

These generated packages contain locally extracted templates and the official
updater executable. They are **not covered wholesale by this project's MIT
license**. Do not commit `build/`, `dist/` or redistribute proprietary firmware
material without appropriate permission. This repository's release is source-only.

Before flashing, run the additional local reference-image test:

```sh
cd ..
python3 tools/check_reference.py
```

That test operates on a temporary copy, compares the resulting three XML
files to generated templates, checks idempotency, and restores the exact
original image. It does not test the raw block-device path or future OTAs.

Read [INSTALL.md](INSTALL.md) before touching the tablet.

## Reproducibility limits

Dependency revisions, source/archive checksums, ROM and XML identities are
pinned. This is not a claim of byte-for-byte reproducible ZIPs across hosts:
ZIP timestamps, compiler versions and compression implementations may differ.
Trust comes from input checks, tests and read-back verification, not a universal
prepublished hash for everyone's locally generated build.

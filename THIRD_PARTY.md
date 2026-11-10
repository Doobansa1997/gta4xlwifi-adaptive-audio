# Third-party components and firmware inputs

The project license applies to project-authored source and documentation,
not every byte of a locally generated recovery ZIP.

| Component | Pinned revision | License / source |
|---|---|---|
| erofs-utils | `f36cadb5c563995ab3aa8572a60ed6b721b9557d` (1.9.4) | Primarily MIT, liberofs files dual GPL-2.0-or-later OR MIT where stated; respect per-file notices. [Upstream](https://github.com/erofs/erofs-utils), `COPYING` and `LICENSES/` |
| LZ4 | `ebb370ca83af193212df4dcbadcc5d87bc0de2f0` (1.10.0) | Library BSD-2-Clause; [upstream](https://github.com/lz4/lz4), `lib/LICENSE` |
| PicoSHA2 | `161cb3fc4170fa7a3eca9e582cebd27cc4d1fe29` | MIT; [upstream](https://github.com/okdshin/PicoSHA2), header license |
| Android NDK | Tested with 28.2.13676358 | Multiple licenses; installed NDK `NOTICE` / `NOTICE.toolchain` copied into local output |
| Lineage legacy updater | Executable extracted locally from the reference official full OTA | [Source](https://github.com/LineageOS/android_bootable_deprecated-ota/tree/lineage-23.2); executable/dependencies retain their licenses, not relicensed MIT |
| Vendor XML / boot / vendor image | Extracted locally from user-supplied reference ROM | Firmware/configuration rights remain with their respective owners; not hosted here |

Pinned source archives/headers are downloaded only during a build into
ignored `third-party/`. Local packages include dependency source archives,
build scripts and applicable notices. The NDK itself is not redistributed.

The public repository deliberately excludes proprietary Dolby tuning,
firmware images, updater binaries, generated flashable packages, cache
backups and device logs. Possession of a ROM or a matching checksum is not
proof that every component may be redistributed.

Reference links used in implementation:

- [LineageOS recovery installer](https://github.com/LineageOS/android_bootable_recovery/blob/lineage-23.2/install/install.cpp)
- [LineageOS dynamic-partition updater](https://github.com/LineageOS/android_bootable_deprecated-ota/blob/lineage-23.2/updater/dynamic_partitions.cpp)
- [gta4xl-common device sources](https://github.com/LineageOS/android_device_samsung_gta4xl-common/tree/lineage-23.2)
- [Lineage Samsung Dolby controller](https://github.com/LineageOS/android_hardware_samsung/blob/lineage-23.2/packages/Dap/src/org/lineageos/dap/DolbyCore.kt)
- [EROFS documentation](https://erofs.docs.kernel.org/)

The optimizer's Q4 dB scale is an implementation reference, not a measured
guarantee of this proprietary engine's transfer function. Do not include
proprietary headers or implementation code in contributions.

# Evidence and test limits

## Initial device observation

One SM-P610 / gta4xlwifi running official
`23.2-20261107-NIGHTLY-gta4xlwifi`. The user reported louder, poorer speaker
audio and crackling. The exact cause and stock signal chain were not proven.
The preset is experimental, not extracted/verified stock Samsung calibration.

## Validation matrix

| Surface | Evidence | Limitation |
|---|---|---|
| First full-image prototype | Actual vendor install, read-back, Android boot, three XML hashes | Old build-specific installer, not the public adaptive write path |
| Runtime policy after prototype | 12 configured speaker groups exactly -600 millibels, 63 remaining curves unchanged | Internal groups excluded; not an acoustic dB measurement |
| Listening | User reported improved sound, lower volume, no crackling on tested material | One listener/device; no calibrated measurement or universal protection |
| Global effects | Wavelet force-stopped, Dynamics Processing absent, DAX3 present | Effective Dolby EQ transfer function/profile behavior not measured |
| Adaptive native tests | Regular-file apply/restore, idempotency, different offsets, invalid inputs, backup failures | Synthetic layout variants are not real future nightlies |
| Adaptive ARM64 tool | File-image preflight/apply/reapply/restore on tablet, exact original SHA256 restored | No raw-device writes in this test |
| Adaptive recovery ZIP | Preflight and apply accepted, preset already present, boot and hashes/curves unchanged | Real-device write/restore from an untouched vendor not performed |
| Future OTA | Compatibility logic and image-identity tests | No actual later nightly installed as part of testing |
| Other routes | Non-speaker XML/runtime curves preserved | No complete physical headphone/Bluetooth/profile test matrix |

Do not describe the adaptive installer as fully OTA-validated or promise
stock-identical volume/EQ.

## Public tests

```sh
python3 tools/fetch_sources.py
python3 tools/build_tools.py --host-only
python3 -m unittest discover -s tests -v
```

All fixtures are generated locally from project-authored synthetic XML/cpio,
without firmware. Tests operate only on temporary regular files. Cases include:

- No writes/backups in preflight.
- Exact patched template contents and idempotent reapplication.
- Full-image identity preserved by restore, including unrelated changes.
- Dynamic offsets on newly generated EROFS.
- Refusal to restore onto a different image.
- Recovery of an interrupted write within a saved cluster.
- Unknown XML, bad backup, missing backup storage, non-EROFS, wrong target type.
- Known-answer SHA256 and LZ4 round-trip.
- Boot parsing and refusal of a vendor AVB-enabled fixture.
- Edify wrapper device/version/read-only-mount guards.

## Optional private reference-image test

After local ROM preparation, tool compilation and packaging:

```sh
python3 tools/check_reference.py
```

This runs the same native core against the privately extracted original vendor
and boot. It verifies all three patched XML files, no-op reapplication, and
byte-exact restoration. It neither uploads firmware nor accesses a block device.

## Reports

Include model, exact ROM/recovery version, whether vendor was untouched,
operation and exact failure. Redact personal/device data. Do not attach
vendor images, proprietary templates, cache backups or entire unredacted logs.
Before adding another model or template, document its layout, boot-chain
checks, rollback and listening evidence; do not simply loosen existing guards.

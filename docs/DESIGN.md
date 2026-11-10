# Design and preset

## Pipeline

The Edify wrapper is run by the official legacy updater extracted locally
from the reference full OTA. It checks recovery device identity and installed
system/product properties, reads ext4 with `ro,noload`, unmounts vendor and
recreates its logical mapping. It never writes the super metadata.

Preflight/apply also inspect the current boot ramdisk's vendor fstab entries.
They require a supported legacy boot/gzip/newc layout and reject vendor AVB
or verify flags. This narrow check is not a full verification of every
possible bootloader/DT/device-mapper arrangement.

The native tool:

1. Checks target type, bounded size/alignment, mount state and exclusive lock.
2. Copies vendor to a temporary regular file, leaving the device unchanged.
3. Uses pinned EROFS tools to verify encoding, extract the three files and
   discover their single-cluster layouts.
4. Requires byte-exact recognized original XML, or all three patched XMLs.
   Mixed or unknown configuration is refused. Already-patched is a no-op.
5. Independently decodes each source cluster with LZ4, recompresses its
   replacement into the same 4 KiB space and verifies a round-trip.
6. Writes the three changes to the staging image and checks it again with
   EROFS tools and exact replacement-template comparison.
7. Verifies that its complete SHA256 equals the current vendor with only the
   intended cluster substitutions. Checks that source vendor did not change.
8. Before real writes, persists, fsyncs and rereads the identity-bound backup.
9. Writes only the three clusters, fsyncs, rereads them and hashes all vendor.

The filesystem metadata and the decoded XML sizes are not rebuilt. The
algorithm depends on the checked single 4 KiB pcluster layout. It deliberately
does not try to grow files, move extents or repair unknown layouts.

## Restore format

`AUDADP01`, little-endian uint64 image size, original SHA256 hex, patched
SHA256 hex, three records (offset, original 4096-byte cluster, patched
4096-byte cluster), followed by SHA256 hex of the preceding backup bytes.

Restore validates the backup and computes the current whole-image identity
with saved original clusters substituted. This must equal the backup's
original image identity, even if some current audio clusters contain an
interrupted write. Substituting saved patched clusters must also yield the
recorded patched identity. Exactly one backup must match.

This prevents blindly copying an old vendor onto a new nightly. It does
not recover corruption outside the saved clusters, a lost backup, device
failure or every possible power-loss scenario.

## Preset

All configured speaker curve points are reduced by **600 millibels**.
Referenced curves are expanded into speaker-only nodes; shared definitions
and non-speaker nodes are unchanged. Both legacy (13 speaker streams) and
engine (12 speaker groups) XML representations are handled.

Dolby optimizer gain uses the Q4 dB reference scale (16 raw units/dB), same
left/right values:

| Frequency (Hz) | Gain (dB) |
|---|---|
| 47 | -6 |
| 141 | -3 |
| 234 | -1.5 |
| 328 | -1 |
| 469 | -0.5 |
| 656, 844, 1031 | 0 |
| 1313 | -0.5 |
| 1688 | -1 |
| 2250, 3000 | -1.5 |
| 3750 | -1 |
| 4688 | -0.5 |
| 5813 | 0 |
| 7125 | -0.5 |
| 9000, 11250 | -1 |
| 13875 | -1.5 |
| 19688 | -2 |

These are project-chosen conservative cuts, **not Samsung's stock EQ**.
The actual proprietary engine response and profile bypass behavior have
not been acoustically measured. Existing regulator/protection parameters,
complex EQ and hardware gains are preserved.

Only original template hashes and project-authored transformations are public.
Full original/patched firmware XML templates are generated locally and excluded
from Git. Changing template hashes to accept a new tuning requires a deliberate
review and new tests, not automatic inheritance.

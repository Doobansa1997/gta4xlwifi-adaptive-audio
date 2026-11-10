import copy
import hashlib
import io
from pathlib import Path
import stat
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import stage_soundbooster as stage

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "build/host-bin"


def record(nid, payload=b"source", mode=stat.S_IFREG | 0o644, nlink=1):
    result = {
        "nid": nid, "mode": mode, "uid": 0, "gid": 0, "nlink": nlink,
        "size": len(payload), "mtime": 1230768000, "mtime_nsec": 0,
        "xattrs": {b"security.selinux".hex(): b"u:object_r:vendor_file:s0".hex()},
    }
    if not stat.S_ISDIR(mode):
        result["sha256"] = hashlib.sha256(payload).hexdigest()
    return result


class SoundBoosterStageTests(unittest.TestCase):
    def setUp(self):
        self.before = {
            "": record(1, mode=stat.S_IFDIR | 0o755, nlink=2),
            stage.EFFECTS_PATH: record(2),
            "/lib/soundfx/libswdap.so": record(3),
            "/untouched": record(4),
        }
        self.payloads = {path: b"new:" + path.encode() for path in stage.NEW_PATHS | {stage.EFFECTS_PATH}}
        self.donors = {path: "/lib/soundfx/libswdap.so" for path in stage.NEW_PATHS}
        self.after = copy.deepcopy(self.before)
        for nid, (path, payload) in enumerate(sorted(self.payloads.items()), 10):
            self.after[path] = record(nid, payload)

    def test_only_reviewed_delta_is_accepted(self):
        stage.verify_delta(self.before, self.after, self.payloads, self.donors)
        changes = (
            ("/untouched", "sha256", "0" * 64),
            ("/untouched", "mode", stat.S_IFREG | 0o666),
            ("/untouched", "uid", 2000),
            (stage.BRIDGE_PATH, "xattrs", {}),
            (stage.BRIDGE_PATH, "nlink", 2),
            (stage.EFFECTS_PATH, "sha256", "0" * 64),
            (stage.EFFECTS_PATH, "size", 0),
            ("", "mtime", 1),
        )
        for path, key, value in changes:
            with self.subTest(path=path, key=key):
                changed = copy.deepcopy(self.after)
                changed[path][key] = value
                with self.assertRaises(ValueError):
                    stage.verify_delta(self.before, changed, self.payloads, self.donors)
        for changed in (
            {key: value for key, value in self.after.items() if key != "/untouched"},
            {**self.after, "/extra": record(100)},
        ):
            with self.assertRaises(ValueError):
                stage.verify_delta(self.before, changed, self.payloads, self.donors)

    def test_split_or_merged_hardlinks_are_refused(self):
        for records in (self.before, self.after):
            records["/untouched"]["nlink"] = 2
            records["/alias"] = copy.deepcopy(records["/untouched"])
        stage.verify_delta(self.before, self.after, self.payloads, self.donors)
        self.after["/alias"]["nid"] = 999
        with self.assertRaisesRegex(ValueError, "hardlink topology"):
            stage.verify_delta(self.before, self.after, self.payloads, self.donors)

    def test_geometry_and_data_extent_are_guarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "image"
            payload = bytearray(8192)
            payload[1024:1028] = b"\xe2\xe1\xf5\xe0"
            payload[1036] = 12
            struct.pack_into("<I", payload, 1060, 2)
            image.write_bytes(payload)
            self.assertEqual(stage.filesystem_layout(image)["data_bytes"], 8192)
            struct.pack_into("<I", payload, 1060, 3)
            image.write_bytes(payload)
            with self.assertRaisesRegex(ValueError, "data extent"):
                stage.filesystem_layout(image)
            image.write_bytes(b"short")
            with self.assertRaisesRegex(ValueError, "geometry"):
                stage.filesystem_layout(image)

    def test_duplicate_and_unsafe_manifest_paths_are_refused(self):
        for output in (b'{"path_hex":""}\n{"path_hex":""}\n',
                       b'{"path_hex":"2f2e2e2f666f6f"}\n', b'{"path_hex":"666f6f"}\n', b""):
            with self.subTest(output=output), mock.patch.object(stage, "run", return_value=output):
                with self.assertRaises(ValueError):
                    stage.audit("tool", "image")

    @unittest.skipUnless((TOOLS / "erofs-manifest").is_file(), "Build host EROFS tools first")
    def test_full_archive_roundtrip_preserves_links_metadata_and_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original.tar"
            with tarfile.open(original, "w", format=tarfile.PAX_FORMAT) as archive:
                for name in (".", "etc", "lib", "lib/soundfx", "etc/audio_effects.xml",
                             "lib/soundfx/libswdap.so", "lib/soundfx/alias.so", "lib/shortcut"):
                    info = tarfile.TarInfo(name)
                    info.uid, info.gid, info.mtime = 0, 2000, 1230768000
                    info.mode = 0o644
                    info.pax_headers = {"SCHILY.xattr.security.selinux": "u:object_r:vendor_file:s0"}
                    payload = b"original-data"
                    if name in (".", "etc", "lib", "lib/soundfx"):
                        info.type, info.mode = tarfile.DIRTYPE, 0o755
                    elif name.endswith("alias.so"):
                        info.type, info.linkname = tarfile.LNKTYPE, "lib/soundfx/libswdap.so"
                    elif name == "lib/shortcut":
                        info.type, info.mode, info.linkname = tarfile.SYMTYPE, 0o777, "soundfx/libswdap.so"
                    else:
                        info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload) if info.isreg() else None)
            image = root / "original.img"
            stage.run(TOOLS / "mkfs.erofs", "-b4096", "-T1230768000", "--tar=f", image, original)
            before = stage.audit(TOOLS / "erofs-manifest", image)
            self.assertEqual(before["/lib/soundfx/libswdap.so"]["nid"],
                             before["/lib/soundfx/alias.so"]["nid"])
            full = root / "full.tar"
            stage.make_full_archive(full, self.payloads, before, self.donors,
                                    TOOLS / "dump.erofs", image)
            candidate = root / "candidate.img"
            stage.run(TOOLS / "mkfs.erofs", "-b4096", "-T1230768000", "--tar=f",
                      "-z", "lz4hc,level=12", candidate, full)
            stage.run(TOOLS / "fsck.erofs", "--extract", candidate)
            after = stage.audit(TOOLS / "erofs-manifest", candidate)
            stage.verify_delta(before, after, self.payloads, self.donors)
            with tarfile.open(full) as archive:
                self.assertEqual(archive.getmember("lib/shortcut").linkname, "soundfx/libswdap.so")
            invalid = root / "invalid.img"
            invalid.write_bytes(b"not EROFS")
            with self.assertRaises(RuntimeError):
                stage.audit(TOOLS / "erofs-manifest", invalid)

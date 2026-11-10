import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import image_delta
import soundbooster_avb as avb

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "build/host-bin"
AVB = ROOT / "third-party/avbtool.py"


@unittest.skipUnless((TOOLS / "fec").is_file(), "Build host FEC tool first")
class FecEncoderTests(unittest.TestCase):
    def run_fec(self, *args, success=True):
        result = subprocess.run([str(TOOLS / "fec"), *map(str, args)], capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result.stdout

    def test_sizes_and_independent_rs_syndromes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for blocks in (1, 253, 254):
                source, encoded = root / "input", root / "fec"
                payload = bytes(range(256)) * (blocks * 16)
                source.write_bytes(payload)
                rounds = (blocks + 252) // 253
                size = rounds * 2 * 4096
                self.assertEqual(int(self.run_fec("--print-fec-size", len(payload), "--roots", 2)), size + 4096)
                self.run_fec("--encode", "--roots", 2, source, encoded)
                data = encoded.read_bytes()
                header = struct.unpack("<IIIIIQ32s", data[-60:])
                self.assertEqual(header[:6], (0xFECFECFE, 0, 60, 2, size, len(payload)))
                self.assertEqual(header[6], hashlib.sha256(data[:size]).digest())
                self.assertEqual(data[size:size + 60], data[-60:])
                self.assertEqual(data[size + 60:-60], bytes(4096 - 120))
                stride = rounds * 4096
                for index in (0, 1, 17, 255, stride - 1):
                    word = [payload[offset] if offset < len(payload) else 0
                            for offset in (index + symbol * stride for symbol in range(253))]
                    word += data[index * 2:index * 2 + 2]
                    # The systematic codeword must vanish at both roots of (x+1)(x+2).
                    for root_value in (1, 2):
                        syndrome = 0
                        for value in word:
                            if root_value == 2:
                                syndrome <<= 1
                                if syndrome & 256:
                                    syndrome ^= 0x11d
                            syndrome ^= value
                        self.assertEqual(syndrome, 0)

    def test_invalid_inputs_and_aliases_do_not_truncate_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, alias, target = root / "source", root / "alias", root / "target"
            original = b"a" * 4096
            source.write_bytes(original)
            os.link(source, alias)
            for output in (source, alias):
                self.run_fec("--encode", "--roots", 2, source, output, success=False)
                self.assertEqual(source.read_bytes(), original)
            target.symlink_to(source)
            self.run_fec("--encode", "--roots", 2, source, target, success=False)
            self.run_fec("--encode", "--roots", 2, target, root / "new", success=False)
            self.assertEqual(source.read_bytes(), original)
            for size in ("0", "1", "-4096", "4096junk", str(2**64), str(2**30 + 4096)):
                self.run_fec("--print-fec-size", size, "--roots", 2, success=False)
            self.run_fec("--encode", "--roots", 3, source, root / "new", success=False)
            self.run_fec("--decode", "--roots", 2, source, root / "new", success=False)
            source.write_bytes(b"short")
            self.run_fec("--encode", "--roots", 2, source, root / "new", success=False)
            self.assertFalse((root / "new").exists())


class ImageDeltaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = self.root / "original.img"
        self.candidate = self.root / "candidate.img"
        self.bundle = self.root / "blocks.zip"
        self.before = b"a" * 4096 + b"b" * 4096 + b"c" * 4096
        self.after = b"d" * 4096 + b"b" * 4096 + b"e" * 4096
        self.original.write_bytes(self.before)
        self.candidate.write_bytes(self.after)

    def test_apply_restore_partial_and_unknown_image_proofs(self):
        report = image_delta.prove(self.original, self.candidate, self.bundle)
        self.assertEqual(report["changed_blocks"], 2)
        self.assertTrue(report["local_apply_and_exact_restore_verified"])
        self.assertTrue(report["mixed_original_candidate_block_restore_verified"])
        self.assertTrue(report["unknown_block_rejected_without_writes"])
        self.assertFalse(report["recovery_execution_verified"])
        self.assertEqual(self.original.read_bytes(), self.before)
        self.assertEqual(self.candidate.read_bytes(), self.after)

    def test_unknown_unchanged_block_and_corrupt_payload_refuse_before_all_writes(self):
        image_delta.create(self.original, self.candidate, self.bundle)
        target = self.root / "target.img"
        unknown = self.before[:4096] + b"x" * 4096 + self.before[8192:]
        target.write_bytes(unknown)
        with self.assertRaisesRegex(ValueError, "Unknown block state"):
            image_delta.apply(self.bundle, target)
        self.assertEqual(target.read_bytes(), unknown)
        with zipfile.ZipFile(self.bundle) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        contents["after.bin"] = b"x" + contents["after.bin"][1:]
        corrupted = self.root / "corrupted.zip"
        with zipfile.ZipFile(corrupted, "w") as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
        target.write_bytes(self.before)
        with self.assertRaisesRegex(ValueError, "Corrupt delta payload"):
            image_delta.apply(corrupted, target)
        self.assertEqual(target.read_bytes(), self.before)

    def test_untrusted_whole_image_hashes_and_geometries_are_rejected(self):
        image_delta.create(self.original, self.candidate, self.bundle)
        with zipfile.ZipFile(self.bundle) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(contents["manifest.json"])
        for field, value in (("after_sha256", "0" * 64), ("image_bytes", 0), ("blocks", [])):
            changed = dict(manifest, **{field: value})
            corrupted = self.root / ("bad-" + field + ".zip")
            with zipfile.ZipFile(corrupted, "w") as archive:
                for name, data in contents.items():
                    archive.writestr(name, json.dumps(changed) if name == "manifest.json" else data)
            with self.assertRaises(ValueError):
                image_delta.apply(corrupted, self.original)
            self.assertEqual(self.original.read_bytes(), self.before)
        symlink = self.root / "link"
        symlink.symlink_to(self.original)
        with self.assertRaises(OSError):
            image_delta.apply(self.bundle, symlink)
        self.candidate.write_bytes(b"short")
        with self.assertRaises(ValueError):
            image_delta.create(self.original, self.candidate, self.root / "bad.zip")
        self.assertFalse((self.root / "bad.zip").exists())


@unittest.skipUnless(AVB.is_file() and (TOOLS / "fec").is_file(), "Fetch/build pinned AVB/FEC tools first")
class AvbTests(unittest.TestCase):
    def test_avb_and_fec_corruption_are_independently_rejected(self):
        module = avb.load_avb(AVB)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "vendor.img"
            image.write_bytes(bytes(range(256)) * 256)
            avb.command(AVB, TOOLS, "add_hashtree_footer", "--image", image,
                        "--partition_size", 1024 * 1024, "--partition_name", "vendor",
                        "--hash_algorithm", "sha1", "--salt", "00" * 32, "--fec_num_roots", 2)
            description = avb.metadata(module, image)
            avb.command(AVB, TOOLS, "verify_image", "--image", image)
            avb.verify_fec(image, description, TOOLS, root)
            with image.open("r+b") as output:
                output.seek(description["tree_fec_offset"])
                value = output.read(1)
                output.seek(description["tree_fec_offset"])
                output.write(bytes([value[0] ^ 1]))
            # avbtool verifies hashtrees, not parity; the separate FEC check must fail.
            avb.command(AVB, TOOLS, "verify_image", "--image", image)
            with self.assertRaisesRegex(ValueError, "FEC parity mismatch"):
                avb.verify_fec(image, description, TOOLS, root)
            with image.open("r+b") as output:
                output.seek(0)
                output.write(b"corrupt")
            with self.assertRaises(RuntimeError):
                avb.command(AVB, TOOLS, "verify_image", "--image", image)
            untrusted = root / "untrusted.py"
            untrusted.write_text("raise AssertionError('must not execute')")
            with self.assertRaisesRegex(ValueError, "Unreviewed"):
                avb.load_avb(untrusted)

    def test_enabled_disable_flags_are_not_accepted(self):
        module = avb.load_avb(AVB)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "vendor.img"
            image.write_bytes(b"a" * 4096)
            avb.command(AVB, TOOLS, "add_hashtree_footer", "--image", image,
                        "--partition_size", 1024 * 1024, "--partition_name", "vendor",
                        "--hash_algorithm", "sha1", "--salt", "00" * 32, "--fec_num_roots", 2,
                        "--flags", 2)
            with self.assertRaisesRegex(ValueError, "Unsupported AVB policy"):
                avb.metadata(module, image)

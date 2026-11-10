import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import package_soundbooster as package
from test_adaptive import boot_image

NATIVE = ROOT / "build/audio-adaptive-host"


@unittest.skipUnless(NATIVE.is_file(), "Build native host tools first")
class SoundBoosterRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = self.root / "original.img"
        self.live = self.root / "live.img"
        self.candidate = self.root / "candidate.img"
        self.target = self.root / "target.img"
        self.bundle = self.root / "blocks.bin"
        self.boot = self.root / "boot.img"
        self.states = (b"a" * 4096 + b"b" * 4096 + b"c" * 4096,
                       b"d" * 4096 + b"b" * 4096 + b"c" * 4096,
                       b"e" * 4096 + b"b" * 4096 + b"f" * 4096)
        for path, state in zip((self.original, self.live, self.candidate), self.states):
            path.write_bytes(state)
        self.info = package.block_bundle(self.original, self.live, self.candidate, self.bundle)
        self.boot.write_bytes(boot_image(b"vendor /vendor erofs ro wait,logical,first_stage_mount\n"))
        self.target.write_bytes(self.states[1])

    def run_native(self, operation, success=True, checksum=None, acknowledgement="--confirmed-offline-or-recovery",
                   kind="--file"):
        result = subprocess.run([str(NATIVE), "blocks-" + operation, kind, str(self.target),
                                 str(self.bundle), checksum or self.info["bundle_sha256"],
                                 str(self.boot), acknowledgement], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_preflight_apply_reapply_and_reference_restore_all_three_states(self):
        for state in self.states:
            with self.subTest(state=state[:1]):
                self.target.write_bytes(state)
                self.assertIn("PREFLIGHT OK", self.run_native("preflight"))
                self.assertEqual(self.target.read_bytes(), state)
                self.assertIn("INSTALL VERIFIED" if state != self.states[2] else "ALREADY APPLIED",
                              self.run_native("apply"))
                self.assertEqual(self.target.read_bytes(), self.states[2])
                self.assertIn("ALREADY APPLIED", self.run_native("apply"))
                self.run_native("restore")
                self.assertEqual(self.target.read_bytes(), self.states[0])

    def test_known_mixed_blocks_restore_but_never_install(self):
        mixed = self.states[1][:4096] + self.states[0][4096:8192] + self.states[2][8192:]
        self.target.write_bytes(mixed)
        self.assertIn("Mixed/partial", self.run_native("apply", success=False))
        self.assertEqual(self.target.read_bytes(), mixed)
        self.run_native("restore")
        self.assertEqual(self.target.read_bytes(), self.states[0])

    def test_unknown_changed_and_unchanged_blocks_refused_without_writes(self):
        for offset in (0, 4096, 8192):
            altered = bytearray(self.states[1])
            altered[offset] ^= 0x80
            for operation in ("preflight", "apply", "restore"):
                self.target.write_bytes(altered)
                self.assertIn("Unknown/torn", self.run_native(operation, success=False))
                self.assertEqual(self.target.read_bytes(), altered)

    def test_corrupt_bundle_wrong_boot_and_missing_acknowledgement_never_write(self):
        state = self.target.read_bytes()
        self.run_native("apply", success=False, checksum="0" * 64)
        self.run_native("apply", success=False, acknowledgement="no")
        self.run_native("apply", success=False, kind="--device")
        self.assertEqual(self.target.read_bytes(), state)
        altered = bytearray(self.bundle.read_bytes())
        altered[-1] ^= 0x80
        self.bundle.write_bytes(altered)
        self.run_native("apply", success=False, checksum=hashlib.sha256(altered).hexdigest())
        self.assertEqual(self.target.read_bytes(), state)
        self.bundle.unlink()
        self.info = package.block_bundle(self.original, self.live, self.candidate, self.bundle)
        self.boot.write_bytes(boot_image(b"vendor /vendor erofs ro wait,logical,first_stage_mount,avb\n"))
        self.run_native("apply", success=False)
        self.assertEqual(self.target.read_bytes(), state)

    def test_symlink_size_and_trailing_bundle_refused_without_writes(self):
        self.target.unlink()
        self.target.symlink_to(self.live)
        self.run_native("apply", success=False)
        self.assertEqual(self.live.read_bytes(), self.states[1])
        self.target.unlink()
        self.target.write_bytes(b"a" * 4096)
        self.run_native("apply", success=False)
        self.assertEqual(self.target.read_bytes(), b"a" * 4096)
        self.target.write_bytes(self.states[1])
        altered = self.bundle.read_bytes() + b"extra"
        self.bundle.write_bytes(altered)
        self.run_native("apply", success=False, checksum=hashlib.sha256(altered).hexdigest())
        self.assertEqual(self.target.read_bytes(), self.states[1])

    def test_corrupt_whole_image_hashes_refused_even_when_outer_hash_is_correct(self):
        altered = bytearray(self.bundle.read_bytes())
        altered[16:80] = b"0" * 64
        self.bundle.write_bytes(altered)
        self.run_native("apply", success=False, checksum=hashlib.sha256(altered).hexdigest())
        self.assertEqual(self.target.read_bytes(), self.states[1])

    def test_package_operations_and_scope(self):
        for mode in ("preflight", "apply", "restore"):
            script = package.script(mode, "0" * 64)
            self.assertIn("blocks-" + mode, script)
            self.assertIn('map_partition("vendor")', script)
            self.assertIn("no device backup", script)
            self.assertIn("broad vendor block", script)
            self.assertNotIn("reboot(", script)
            self.assertIn("STAY IN RECOVERY", script)
        with self.assertRaises(ValueError):
            package.script("unknown", "0" * 64)
        with self.assertRaises(ValueError):
            package.build(self.original, self.live, self.candidate, self.root / "packages")
        self.assertFalse((self.root / "packages").exists())

    def test_hidl_transition_pins_installed_and_fixed_images_without_relaxing_guards(self):
        self.assertEqual(package.REVIEWED_TRANSITIONS["final"],
                         (package.MINUS9_SHA256, package.MINUS7_SHA256))
        self.assertEqual(package.REVIEWED_TRANSITIONS["initial"],
                         (package.LIVE_SHA256, package.CANDIDATE_SHA256))
        self.assertEqual(package.REVIEWED_TRANSITIONS["hidl-fix"],
                         (package.CANDIDATE_SHA256, package.HIDL_FIXED_SHA256))
        self.assertEqual(package.REVIEWED_TRANSITIONS["runtime-fix"],
                         (package.HIDL_FIXED_SHA256, package.RUNTIME_FIXED_SHA256))
        self.assertEqual(package.REVIEWED_TRANSITIONS["minus9"],
                         (package.RUNTIME_FIXED_SHA256, package.MINUS9_SHA256))
        self.assertEqual(package.REVIEWED_TRANSITIONS["return-minus11"],
                         (package.MINUS9_SHA256, package.RUNTIME_FIXED_SHA256))
        self.assertEqual(package.REVIEWED_TRANSITIONS["minus7"],
                         (package.MINUS9_SHA256, package.MINUS7_SHA256))
        self.assertEqual(package.REVIEWED_TRANSITIONS["return-minus9"],
                         (package.MINUS7_SHA256, package.MINUS9_SHA256))
        for profile in ("hidl-fix", "runtime-fix", "minus9", "return-minus11",
                        "minus7", "return-minus9", "unknown"):
            with self.assertRaises(ValueError):
                package.build(self.original, self.live, self.candidate, self.root / "packages",
                              profile=profile)
            self.assertFalse((self.root / "packages").exists())

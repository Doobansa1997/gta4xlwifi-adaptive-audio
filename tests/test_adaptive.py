import gzip
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import preset
import package

TOOL = ROOT / "build/audio-adaptive-host"


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def boot_image(fstab):
    def member(name, content):
        fields = [1, 0o100644, 0, 0, 1, 0, len(content), 0, 0, 0, 0, len(name) + 1, 0]
        record = b"070701" + "".join(f"{n:08x}" for n in fields).encode() + name.encode() + b"\0"
        record += bytes(-len(record) % 4)
        return record + content + bytes(-len(content) % 4)
    ramdisk = gzip.compress(member("fstab.test", fstab) + member("TRAILER!!!", b""))
    header = bytearray(4096)
    header[:8] = b"ANDROID!"
    struct.pack_into("<I", header, 16, len(ramdisk))
    struct.pack_into("<I", header, 36, 4096)
    struct.pack_into("<I", header, 40, 2)
    return header + ramdisk


class AdaptiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.root = Path(cls.fixture.name)
        cls.tools = cls.root / "tools"
        (cls.tools / "templates").mkdir(parents=True)
        (cls.tools / "bin").mkdir()
        for name in ("dump.erofs", "fsck.erofs"):
            executable = shutil.which(name)
            if executable is None:
                raise RuntimeError(f"Missing test dependency: {name}")
            (cls.tools / "bin" / name).symlink_to(executable)
        defaults = b'<volumes><reference name="media"><point>1,-5800</point><point>100,0</point></reference></volumes>'
        originals = []
        for count in (13, 12):
            text = '<volumes>' + "".join(
                f'<volume stream="stream{i}" deviceCategory="DEVICE_CATEGORY_SPEAKER" ref="media"/>'
                f'<volume stream="stream{i}" deviceCategory="DEVICE_CATEGORY_HEADSET" ref="media"/>'
                for i in range(count)
            ) + '</volumes>'
            originals.append((text + "\n" + " " * (15999 - len(text))).encode())
        text = '<device_data><tuning name="speaker"><data><audio-optimizer-bands>' + "".join(
            f'<band_optimizer frequency="{frequency}" gain_left="0" gain_right="0"/>'
            for frequency in preset.EQ_Q4
        ) + '</audio-optimizer-bands></data></tuning></device_data>'
        originals.append((text + "\n" + " " * (15999 - len(text))).encode())
        for index, original in enumerate(originals):
            patched = (preset.equalize_speakers(original) if index == 2 else
                       preset.attenuate_speakers(original, defaults))
            previous = (preset.equalize_speakers(original, preset.PREVIOUS_EQ_Q4) if index == 2 else
                        preset.attenuate_speakers(original, defaults, 600))
            previous9 = (preset.equalize_speakers(original, preset.PREVIOUS9_EQ_Q4) if index == 2 else
                         preset.attenuate_speakers(original, defaults, 900))
            previous11 = (preset.equalize_speakers(original, preset.PREVIOUS11_EQ_Q4) if index == 2 else
                          preset.attenuate_speakers(original, defaults, 1100))
            previous_treble = (preset.equalize_speakers(original, preset.PREVIOUS_TREBLE_EQ_Q4)
                               if index == 2 else previous11)
            for kind, data in (("original", original), ("patched", patched),
                               ("previous", previous), ("previous9", previous9),
                               ("previous11", previous11), ("previous_treble", previous_treble),
                               ("previous_bass", patched),
                               ("baseline", original if index == 2 else patched)):
                (cls.tools / "templates" / f"{index}.{kind}").write_bytes(data)
        tree = cls.root / "tree"
        for index, name in enumerate((
            "etc/audio_policy_volumes.xml",
            "etc/audio_policy_engine_stream_volumes.xml",
            "etc/dolby/dax-default.xml",
        )):
            path = tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cls.tools / "templates" / f"{index}.original", path)
        # A rebuilt EROFS fixture proves offsets/sizes need not match the ROM.
        cls.relocated = cls.root / "relocated.img"
        subprocess.run(["mkfs.erofs", "-b4096", "-z", "lz4hc,level=12", "-C4096",
                        "--max-extent-bytes=131072", str(cls.relocated), str(tree)],
                       check=True, stdout=subprocess.DEVNULL)
        with cls.relocated.open("ab") as output:
            output.write(bytes(4096))
        cls.boot = cls.root / "boot.img"
        cls.boot.write_bytes(boot_image(b"vendor /vendor erofs ro wait,logical,first_stage_mount\n"))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.image = self.directory / "vendor.img"
        self.backups = self.directory / "backups"
        shutil.copyfile(self.relocated, self.image)

    def tearDown(self):
        self.temporary.cleanup()

    def run_tool(self, mode, success=True, image=None, backups=None, tools=None):
        result = subprocess.run([
            str(TOOL), mode, "--file", str(image or self.image),
            str(backups or self.backups), str(tools or self.tools), str(self.directory),
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout + result.stderr

    def test_selftest_and_boot_validation(self):
        subprocess.run([str(TOOL), "selftest"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(TOOL), "checkboot", str(self.boot)],
                       check=True, stdout=subprocess.DEVNULL)

    def test_preflight_has_no_image_or_backup_writes(self):
        before = sha256(self.image)
        result = self.run_tool("preflight")
        self.assertIn("PREFLIGHT OK", result)
        self.assertEqual(sha256(self.image), before)
        self.assertFalse(self.backups.exists())
        self.assertFalse(list(self.directory.glob("audio-image-*")))

    def test_apply_uses_exact_preset_and_is_idempotent(self):
        self.run_tool("apply")
        for index, name in enumerate(preset.FILES):
            content = subprocess.check_output([
                "dump.erofs", "--cat", f"--path=/{name}", str(self.image)
            ])
            self.assertEqual(content, (self.tools / "templates" / f"{index}.patched").read_bytes())
        backups = list(self.backups.glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertLess(backups[0].stat().st_size, 30000)
        first = sha256(self.image)
        self.assertIn("ALREADY APPLIED", self.run_tool("apply"))
        self.assertEqual(sha256(self.image), first)
        self.assertEqual(len(list(self.backups.glob("*.bak"))), 1)
        self.run_tool("restore")
        self.assertEqual(sha256(self.image), sha256(self.relocated))

    def test_different_image_identity_does_not_restore_old_vendor(self):
        with self.image.open("r+b") as output:
            output.seek(-4096, 2)
            output.write(b"NEW-NIGHTLY-SIMULATION")
        before = sha256(self.image)
        self.run_tool("apply")
        self.run_tool("restore")
        self.assertEqual(sha256(self.image), before)
        self.assertNotEqual(before, sha256(self.relocated))

    def test_previous_preset_migration_and_exact_restore(self):
        self.check_previous_migration("previous")

    def test_previous9_preset_migration_and_exact_restore(self):
        self.check_previous_migration("previous9", backup_free=True)

    def test_previous11_treble_revision_and_reset(self):
        self.check_previous_migration("previous11", backup_free=True)

    def test_previous_treble_bass_revision_and_reset(self):
        self.check_previous_migration("previous_treble", backup_free=True)

    def check_previous_migration(self, suffix, backup_free=False):
        tree = self.directory / "previous-tree"
        shutil.copytree(self.root / "tree", tree)
        for index, name in enumerate(preset.FILES):
            (tree / name).write_bytes((self.tools / "templates" / f"{index}.{suffix}").read_bytes())
        subprocess.run(["mkfs.erofs", "-b4096", "-z", "lz4hc,level=12", "-C4096",
                        "--max-extent-bytes=131072", str(self.image), str(tree)],
                       check=True, stdout=subprocess.DEVNULL)
        before = sha256(self.image)
        self.assertIn("MIGRATION", self.run_tool("preflight"))
        self.assertEqual(sha256(self.image), before)
        self.assertFalse(self.backups.exists())
        operation = "replace" if backup_free else "apply"
        self.assertIn("MIGRATION", self.run_tool(operation))
        for index, name in enumerate(preset.FILES):
            content = subprocess.check_output([
                "dump.erofs", "--cat", f"--path=/{name}", str(self.image)
            ])
            self.assertEqual(content, (self.tools / "templates" / f"{index}.patched").read_bytes())
        after = sha256(self.image)
        self.assertIn("ALREADY APPLIED", self.run_tool(operation))
        self.assertEqual(sha256(self.image), after)
        if backup_free:
            self.assertFalse(self.backups.exists())
            self.run_tool("reset")
            for index, name in enumerate(preset.FILES):
                content = subprocess.check_output([
                    "dump.erofs", "--cat", f"--path=/{name}", str(self.image)
                ])
                self.assertEqual(content, (self.tools / "templates" / f"{index}.original").read_bytes())
        else:
            self.run_tool("restore")
            self.assertEqual(sha256(self.image), before)

    def test_mixed_previous_and_original_refused(self):
        tree = self.directory / "mixed-tree"
        shutil.copytree(self.root / "tree", tree)
        (tree / preset.FILES[0]).write_bytes((self.tools / "templates/0.previous").read_bytes())
        subprocess.run(["mkfs.erofs", "-b4096", "-z", "lz4hc,level=12", "-C4096",
                        "--max-extent-bytes=131072", str(self.image), str(tree)],
                       check=True, stdout=subprocess.DEVNULL)
        before = sha256(self.image)
        self.assertIn("Mixed/partial", self.run_tool("apply", success=False))
        self.assertEqual(sha256(self.image), before)
        self.assertFalse(self.backups.exists())

    def test_backup_free_replace_and_reset(self):
        before = sha256(self.image)
        self.run_tool("replace")
        self.assertFalse(self.backups.exists())
        self.assertIn("ALREADY APPLIED", self.run_tool("replace"))
        self.run_tool("reset")
        self.assertFalse(self.backups.exists())
        for index, name in enumerate(preset.FILES):
            content = subprocess.check_output([
                "dump.erofs", "--cat", f"--path=/{name}", str(self.image)
            ])
            self.assertEqual(content, (self.tools / "templates" / f"{index}.original").read_bytes())
        self.assertIn("ALREADY APPLIED", self.run_tool("reset"))
        self.assertEqual(sha256(self.image), before)

    def test_samsung_baseline_from_custom_and_back(self):
        baseline_tools = self.directory / "baseline-tools"
        shutil.copytree(self.tools, baseline_tools, symlinks=True)
        for index in range(len(preset.FILES)):
            shutil.copyfile(baseline_tools / "templates" / f"{index}.baseline",
                            baseline_tools / "templates" / f"{index}.patched")
        for starting_state in ("original", "custom"):
            with self.subTest(starting_state=starting_state):
                shutil.copyfile(self.relocated, self.image)
                if starting_state == "custom":
                    self.run_tool("replace")
                before = sha256(self.image)
                self.run_tool("preflight", tools=baseline_tools)
                self.assertEqual(sha256(self.image), before)
                self.run_tool("replace", tools=baseline_tools)
                for index, name in enumerate(preset.FILES):
                    content = subprocess.check_output([
                        "dump.erofs", "--cat", f"--path=/{name}", str(self.image)
                    ])
                    suffix = "original" if index == 2 else "patched"
                    self.assertEqual(content, (self.tools / "templates" / f"{index}.{suffix}").read_bytes())
                installed = sha256(self.image)
                self.assertIn("ALREADY APPLIED", self.run_tool("replace", tools=baseline_tools))
                self.assertEqual(sha256(self.image), installed)
                self.assertIn("MIGRATION", self.run_tool("replace"))
                self.run_tool("replace", tools=baseline_tools)
                self.run_tool("reset", tools=baseline_tools)
                for index, name in enumerate(preset.FILES):
                    content = subprocess.check_output([
                        "dump.erofs", "--cat", f"--path=/{name}", str(self.image)
                    ])
                    self.assertEqual(content, (self.tools / "templates" / f"{index}.original").read_bytes())
                self.assertFalse(self.backups.exists())

    def test_samsung_packaging_exact_identity_and_unknown_input(self):
        vendor = self.directory / "samsung-vendor"
        shutil.copytree(self.root / "tree", vendor)
        defaults = b'<volumes><reference name="media"><point>1,-5800</point><point>100,0</point></reference></volumes>'
        for name in ("default_volume_tables.xml", "audio_policy_engine_default_stream_volumes.xml"):
            (vendor / "etc" / name).write_bytes(defaults)
        hashes = {
            key: tuple(sha256(self.tools / "templates" / f"{index}.{suffix}")
                       for index in range(len(preset.FILES)))
            for key, suffix in (
                ("ORIGINAL_HASHES", "original"), ("PREVIOUS_HASHES", "previous"),
                ("PREVIOUS9_HASHES", "previous9"), ("PREVIOUS11_HASHES", "previous11"),
                ("PREVIOUS_TREBLE_HASHES", "previous_treble"), ("PREVIOUS_BASS_HASHES", "patched"),
            )
        }
        with mock.patch.multiple(preset, VENDOR_TREE=vendor, **hashes):
            payload = package.verified_samsung_dolby(vendor)
            stage = self.directory / "baseline-stage"
            manifest = package.templates(stage, payload)
            self.assertEqual((stage / "templates/2.patched").read_bytes(), payload)
            self.assertEqual(manifest[2]["patched_sha256"], hashes["ORIGINAL_HASHES"][2])
            for index in (0, 1):
                self.assertEqual((stage / "templates" / f"{index}.patched").read_bytes(),
                                 (self.tools / "templates" / f"{index}.patched").read_bytes())
            wrong = vendor / preset.FILES[2]
            wrong.write_bytes(payload.replace(b'gain_left="0"', b'gain_left="1"', 1))
            with self.assertRaisesRegex(ValueError, "reviewed SM-P610"):
                package.verified_samsung_dolby(vendor)
            wrong.write_bytes(payload)
            with self.assertRaisesRegex(ValueError, "differ"):
                package.templates(self.directory / "wrong-stage", payload + b" ")

    def test_dynamic_offsets_on_rebuilt_erofs(self):
        before = sha256(self.relocated)
        shutil.copyfile(self.relocated, self.image)
        self.run_tool("preflight")
        self.run_tool("apply")
        self.assertNotEqual(sha256(self.image), before)
        self.run_tool("restore")
        self.assertEqual(sha256(self.image), before)

    def test_mismatched_vendor_after_update_refuses_restore(self):
        self.run_tool("apply")
        with self.image.open("r+b") as output:
            output.seek(-4096, 2)
            output.write(b"DIFFERENT-OTA")
        before = sha256(self.image)
        self.run_tool("restore", success=False)
        self.assertEqual(sha256(self.image), before)

    def test_restore_recovers_interrupted_cluster_write(self):
        self.run_tool("apply")
        backup = next(self.backups.glob("*.bak")).read_bytes()
        offset = struct.unpack_from("<Q", backup, 144)[0]
        with self.image.open("r+b") as output:
            output.seek(offset + 200)
            output.write(b"INTERRUPTED-WRITE")
        self.run_tool("restore")
        self.assertEqual(sha256(self.image), sha256(self.relocated))

    def test_unknown_xml_refused_before_writing(self):
        # A valid EROFS with a different XML configuration is not an allowed preset.
        tree = self.directory / "tree"
        shutil.copytree(self.root / "tree", tree)
        xml = tree / "etc/dolby/dax-default.xml"
        xml.write_bytes(xml.read_bytes().replace(b'gain_left="0"', b'gain_left="1"', 1))
        subprocess.run(["mkfs.erofs", "-b4096", "-z", "lz4hc,level=12", "-C4096",
                        "--max-extent-bytes=131072", str(self.image), str(tree)],
                       check=True, stdout=subprocess.DEVNULL)
        before = sha256(self.image)
        self.run_tool("apply", success=False)
        self.assertEqual(sha256(self.image), before)
        self.assertFalse(self.backups.exists())

    def test_missing_or_unwritable_backup_path_refuses_write(self):
        before = sha256(self.image)
        self.run_tool("apply", success=False, backups=self.directory / "missing/parent/backups")
        self.assertEqual(sha256(self.image), before)

    def test_corrupted_backup_refuses_restore(self):
        self.run_tool("apply")
        backup = next(self.backups.glob("*.bak"))
        with backup.open("r+b") as output:
            output.seek(200)
            output.write(b"BROKEN")
        before = sha256(self.image)
        self.run_tool("restore", success=False)
        self.assertEqual(sha256(self.image), before)

    def test_non_erofs_and_wrong_target_type_refused(self):
        self.image.write_bytes(bytes(4096))
        before = sha256(self.image)
        self.run_tool("apply", success=False)
        self.assertEqual(sha256(self.image), before)
        result = subprocess.run([
            str(TOOL), "apply", "--device", str(self.image), str(self.backups),
            str(self.tools), str(self.directory),
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sha256(self.image), before)

    def test_boot_with_vendor_avb_is_refused(self):
        boot = self.directory / "avb-boot.img"
        boot.write_bytes(boot_image(b"vendor /vendor erofs ro wait,logical,first_stage_mount,avb\n"))
        result = subprocess.run([str(TOOL), "checkboot", str(boot)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Vendor verification enabled", result.stderr)

    def test_partial_preset_is_refused_without_writes(self):
        tree = self.directory / "tree"
        shutil.copytree(self.root / "tree", tree)
        (tree / preset.FILES[0]).write_bytes((self.tools / "templates/0.patched").read_bytes())
        subprocess.run(["mkfs.erofs", "-b4096", "-z", "lz4hc,level=12", "-C4096",
                        "--max-extent-bytes=131072", str(self.image), str(tree)],
                       check=True, stdout=subprocess.DEVNULL)
        before = sha256(self.image)
        self.assertIn("Mixed/partial", self.run_tool("apply", success=False))
        self.assertEqual(sha256(self.image), before)
        self.assertFalse(self.backups.exists())

    def test_package_guards_and_no_old_images(self):
        for mode in ("preflight", "apply", "restore"):
            script = package.script(mode)
            self.assertIn('== "23.2"', script)
            self.assertIn('"ro,noload,noatime,nodev,nosuid"', script)
            self.assertIn("ro.lineage.device", script)
            self.assertNotIn("20261107", script)
            self.assertNotIn("update_dynamic_partitions", script)
            self.assertNotIn("block_image_update", script)
            self.assertNotIn("/cache", script)
            self.assertIn('"-"', script)


if __name__ == "__main__":
    unittest.main()

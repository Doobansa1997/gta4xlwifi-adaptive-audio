import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import configure_soundbooster as config


SOURCE = f'''<?xml version="1.0"?>
<audio_effects_conf version="2.0" xmlns="{config.NAMESPACE}">
    <!-- Preserve existing configuration bytes and comments. -->
    <libraries>
        <library name="dap" path="libswdap.so"/>
    </libraries>
    <effects>
        <effect name="dap" library="dap" uuid="6ab06da4-c516-4611-8166-452799218539"/>
    </effects>
    <preprocess><stream type="voice_communication"><apply effect="dap"/></stream></preprocess>
</audio_effects_conf>
'''.encode("ascii")


class SoundBoosterConfigurationTests(unittest.TestCase):
    def test_exact_structural_delta_and_preserved_existing_nodes(self):
        with mock.patch.object(config, "SOURCE_SHA256", hashlib.sha256(SOURCE).hexdigest()):
            output = config.candidate(SOURCE)
        original, modified = ET.fromstring(SOURCE), ET.fromstring(output)
        ns = {"a": config.NAMESPACE}
        library = modified.find("a:libraries", ns)
        effects = modified.find("a:effects", ns)
        self.assertEqual(library[-1].attrib, {"name": config.LIBRARY, "path": config.LIBRARY_FILE})
        self.assertEqual(effects[-1].attrib, {"name": config.LIBRARY, "library": config.LIBRARY,
                                             "uuid": config.UUID})
        postprocess = modified.find("a:postprocess", ns)
        self.assertEqual(len(postprocess), 1)
        self.assertEqual(postprocess[0].attrib, {"type": "music"})
        self.assertEqual(len(postprocess[0]), 1)
        self.assertEqual(postprocess[0][0].attrib, {"effect": config.LIBRARY})
        restored = copy.deepcopy(modified)
        restored.find("a:libraries", ns).remove(restored.find("a:libraries", ns)[-1])
        restored.find("a:effects", ns).remove(restored.find("a:effects", ns)[-1])
        restored.remove(restored.find("a:postprocess", ns))
        for element in restored.iter():
            element.tail = None
            if element.text and not element.text.strip():
                element.text = None
        for element in original.iter():
            element.tail = None
            if element.text and not element.text.strip():
                element.text = None
        self.assertEqual(ET.tostring(original), ET.tostring(restored))
        self.assertIn(b"<!-- Preserve existing configuration bytes and comments. -->", output)

    def test_unknown_or_already_modified_configuration_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            config.candidate(SOURCE)
        with mock.patch.object(config, "SOURCE_SHA256", hashlib.sha256(SOURCE).hexdigest()):
            generated = config.candidate(SOURCE)
            with self.assertRaisesRegex(ValueError, "Unreviewed"):
                config.candidate(generated)
        for data in (
            SOURCE.replace(b"</audio_effects_conf>", b"<postprocess/></audio_effects_conf>"),
            SOURCE.replace(b'name="dap"', f'name="{config.LIBRARY}"'.encode("ascii")),
            SOURCE.replace(b'version="2.0"', b'version="3.0"'),
        ):
            with self.subTest(data=data), mock.patch.object(
                    config, "SOURCE_SHA256", hashlib.sha256(data).hexdigest()):
                with self.assertRaises(ValueError):
                    config.candidate(data)

    def test_original_rollback_and_manifest_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
                config, "SOURCE_SHA256", hashlib.sha256(SOURCE).hexdigest()):
            root = Path(temporary)
            source = root / "source.xml"
            source.write_bytes(SOURCE)
            target = root / "candidate"
            manifest = config.prepare(source, target)
            self.assertEqual(source.read_bytes(), SOURCE)
            self.assertEqual((target / "audio_effects.original.xml").read_bytes(), SOURCE)
            self.assertEqual(manifest, json.loads((target / "manifest.json").read_text()))
            self.assertEqual(manifest["required_abi"], "armeabi-v7a")
            self.assertEqual(manifest["library_target"], "/vendor/lib/soundfx/libadaptive_soundbooster.so")
            self.assertEqual(manifest["candidate_sha256"],
                             config.digest((target / "audio_effects.xml").read_bytes()))
            for key in ("android_service_integration_verified", "deployment_verified",
                        "dolby_coexistence_verified", "libraries_included"):
                self.assertIs(manifest[key], False)
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            with self.assertRaises(FileExistsError):
                config.prepare(source, target)
            self.assertEqual(before, {path.name: path.read_bytes() for path in target.iterdir()})
            source.write_bytes(b"unknown")
            with self.assertRaisesRegex(ValueError, "Unreviewed"):
                config.prepare(source, root / "rejected")
            self.assertFalse((root / "rejected").exists())

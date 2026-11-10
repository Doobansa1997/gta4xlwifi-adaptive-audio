import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import preset


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.defaults = b'<volumes><reference name="media"><point>1,-5800</point><point>100,0</point></reference></volumes>'
        text = '<volumes>' + "".join(
            f'<volume stream="stream{i}" deviceCategory="DEVICE_CATEGORY_SPEAKER" ref="media"/>'
            f'<volume stream="stream{i}" deviceCategory="DEVICE_CATEGORY_HEADSET" ref="media"/>'
            for i in range(13)
        ) + '</volumes>\n'
        self.original = (text + " " * 12000).encode()

    def test_exact_attenuation_and_unchanged_shared_references(self):
        modified = preset.attenuate_speakers(self.original, self.defaults)
        self.assertEqual(len(modified), len(self.original))
        preset.validate_curves(self.original, modified, self.defaults)
        root = ET.fromstring(modified)
        for node in root.findall('.//volume[@deviceCategory="DEVICE_CATEGORY_SPEAKER"]'):
            self.assertNotIn("ref", node.attrib)
            self.assertEqual([point.text for point in node], ["1,-6400", "100,-600"])
        for node in root.findall('.//volume[@deviceCategory="DEVICE_CATEGORY_HEADSET"]'):
            self.assertEqual(node.attrib["ref"], "media")

    def test_non_speaker_changes_are_rejected(self):
        modified = preset.attenuate_speakers(self.original, self.defaults)
        modified = modified.replace(b'DEVICE_CATEGORY_HEADSET', b'DEVICE_CATEGORY_INVALID', 1)
        with self.assertRaises(ValueError):
            preset.validate_curves(self.original, modified, self.defaults)

    def test_unsupported_curve_count_is_rejected(self):
        with self.assertRaises(ValueError):
            preset.attenuate_speakers(b"<volumes/>", self.defaults)

    def test_invalid_or_oversize_output_is_rejected(self):
        with self.assertRaises(ValueError):
            preset.same_length_xml(b"<a/>", "<long-tag/>")
        with self.assertRaises(ET.ParseError):
            preset.same_length_xml(b"<a/>" + b" " * 20, "<a>")


if __name__ == "__main__":
    unittest.main()

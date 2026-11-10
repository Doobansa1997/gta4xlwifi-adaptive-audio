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
            self.assertEqual([point.text for point in node], ["1,-6900", "100,-1100"])
        for node in root.findall('.//volume[@deviceCategory="DEVICE_CATEGORY_HEADSET"]'):
            self.assertEqual(node.attrib["ref"], "media")

    def test_non_speaker_changes_are_rejected(self):
        modified = preset.attenuate_speakers(self.original, self.defaults)
        modified = modified.replace(b'DEVICE_CATEGORY_HEADSET', b'DEVICE_CATEGORY_INVALID', 1)
        with self.assertRaises(ValueError):
            preset.validate_curves(self.original, modified, self.defaults)

    def test_two_db_steps_preserve_other_endpoints_and_default_attenuation(self):
        for attenuation in (900, 700):
            with self.subTest(attenuation=attenuation):
                previous = preset.attenuate_speakers(self.original, self.defaults, attenuation + 200)
                modified = preset.attenuate_speakers(self.original, self.defaults, attenuation)
                preset.validate_curves(self.original, modified, self.defaults, attenuation)
                self.assertEqual(len(modified), len(self.original))
                before, after = ET.fromstring(previous), ET.fromstring(modified)
                for old, new in zip(before, after):
                    if old.attrib["deviceCategory"] == "DEVICE_CATEGORY_SPEAKER":
                        self.assertEqual([point.text for point in new],
                                         [f"1,{-5800 - attenuation}", f"100,{-attenuation}"])
                        for a, b in zip(old, new):
                            ai, ag = map(int, a.text.split(","))
                            bi, bg = map(int, b.text.split(","))
                            self.assertEqual(ai, bi)
                            self.assertEqual(bg - ag, 200)
                    else:
                        self.assertEqual(preset.canonical(old), preset.canonical(new))
                with self.assertRaisesRegex(ValueError, "Incorrect attenuation"):
                    preset.validate_curves(self.original, modified, self.defaults, attenuation + 200)
        self.assertEqual(preset.ATTENUATION_MB, 1100)

    def test_exact_moderate_boost_and_unchanged_other_tuning(self):
        bands = "".join(
            f'<band_optimizer frequency="{frequency}" gain_left="0" gain_right="0"/>'
            for frequency in preset.EQ_Q4
        )
        original = (
            '<device_data><tuning name="speaker"><data><audio-optimizer-bands>'
            + bands + '</audio-optimizer-bands><regulator-enable value="true"/>'
            '</data></tuning><tuning name="headphone"><data/></tuning></device_data>'
            + "\n" + " " * 4000
        ).encode()
        modified = preset.equalize_speakers(original)
        self.assertEqual(len(modified), len(original))
        root = ET.fromstring(modified)
        actual = {
            int(node.attrib["frequency"]): (int(node.attrib["gain_left"]), int(node.attrib["gain_right"]))
            for node in root.findall('./tuning[@name="speaker"]/data/audio-optimizer-bands/*')
        }
        expected = {
            47: -48, 141: 32, 234: 32, 328: 24, 469: 16,
            656: 8, 844: 8, 1031: 8, 1313: -16, 1688: -24,
            2250: -32, 3000: -32, 3750: -24, 4688: -16, 5813: -8,
            7125: -16, 9000: -24, 11250: -24, 13875: -32, 19688: -40,
        }
        self.assertEqual(actual, {frequency: (gain, gain) for frequency, gain in expected.items()})
        for frequency, gain in preset.EQ_Q4.items():
            self.assertEqual(gain - preset.PREVIOUS_TREBLE_EQ_Q4[frequency],
                             {141: 16, 234: 16, 328: 8}.get(frequency, 0))
        before = ET.fromstring(original)
        for node in (root, before):
            node.find('./tuning[@name="speaker"]/data').remove(
                node.find('./tuning[@name="speaker"]/data/audio-optimizer-bands')
            )
        self.assertEqual(preset.canonical(root), preset.canonical(before))
        excessive = dict(preset.EQ_Q4)
        excessive[141] = 33
        with self.assertRaisesRegex(ValueError, "reviewed"):
            preset.equalize_speakers(original, excessive)
        for frequency, gain in ((328, 25), (469, 17), (141, -97)):
            with self.subTest(frequency=frequency, gain=gain):
                excessive = {**preset.EQ_Q4, frequency: gain}
                with self.assertRaisesRegex(ValueError, "reviewed"):
                    preset.equalize_speakers(original, excessive)

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

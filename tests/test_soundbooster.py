import hashlib
import math
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import soundbooster
import verify_soundbooster
import trace_soundbooster


def parameters():
    rows = ["S," + ",".join(["0"] * 16)]
    for group in "ABCD":
        for category, count in (("H", 3), ("F", 17), ("L", 58)):
            rows.append(group + category + "," + ",".join(["0"] * count))
        for band in "ABCDEFGHIJKLMNOP":
            rows.append(group + "M" + band + "," + ",".join(["0"] * 58))
        for bank in "AC":
            for band in "ABCDEFGH":
                rows.append(group + bank + band + ",1000,250,3")
            rows.append(group + bank + "M,1,1,1,1,1,1,1,1")
            rows.append(group + bank + "U,1")
    return ("\n".join(rows) + "\n").encode()


class SoundBoosterTests(unittest.TestCase):
    def test_exact_record_schema_and_errors(self):
        payload = parameters()
        self.assertEqual(len(soundbooster.parse_rows(payload.decode())), 157)
        for invalid in (
            payload + b"AAA,1000,250,3\n",
            payload.replace(b"AAA,1000,250,3", b"AAA,1000,250"),
            payload.replace(b"AAA,1000,250,3", b"AAA,1000,wat,3"),
            payload.replace(b"AAA,1000,250,3\n", b""),
            payload + b"TA,0\n",
        ):
            with self.subTest(invalid=invalid[-60:]), self.assertRaises(ValueError):
                soundbooster.parse_rows(invalid.decode())

    def test_type_one_center_gain_and_unity_endpoints(self):
        for frequency, bandwidth in ((100, 50), (1000, 250), (10000, 3000)):
            for gain in (-12, -3, 0, 3, 12):
                coefficients = soundbooster.peaking_coefficients(frequency, bandwidth, gain)
                self.assertAlmostEqual(soundbooster.response_db(coefficients, frequency), gain, places=8)
                for endpoint in (0, 24000):
                    self.assertAlmostEqual(soundbooster.response_db(coefficients, endpoint), 0, places=8)
                a1, a2 = coefficients[3:]
                self.assertGreater(1 + a1 + a2, 0)
                self.assertGreater(1 - a1 + a2, 0)
                self.assertLess(abs(a2), 1)

    def test_bandwidth_is_not_q(self):
        narrow = soundbooster.peaking_coefficients(1000, 100, 6)
        wide = soundbooster.peaking_coefficients(1000, 1000, 6)
        self.assertGreater(soundbooster.response_db(wide, 1500),
                           soundbooster.response_db(narrow, 1500))
        for args in ((0, 10, 3), (24000, 10, 3), (1000, 0, 3),
                     (1000, 10, 25), (1000, math.nan, 3), (1000, 10, math.inf)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                soundbooster.peaking_coefficients(*args)
        with self.assertRaises(ValueError):
            soundbooster.response_db(narrow, 25000)

    def test_unknown_firmware_refused(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            soundbooster.analyze(parameters())
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            verify_soundbooster.verify(b"unknown ELF", {})
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            trace_soundbooster.ControlTrace(b"unknown ELF")

    def test_control_aggregate_packing(self):
        rows = soundbooster.parse_rows(parameters().decode())
        values = trace_soundbooster.amf_values(rows, "AA")
        self.assertEqual(values, [1000, 250, 3] * 8 + [1] * 9)
        self.assertEqual(len(trace_soundbooster.packed(values)), 132)
        self.assertEqual(trace_soundbooster.packed([-1]), b"\xff" * 4)

    def test_unreviewed_control_modes_refused(self):
        for mode in (-1, 0, 3):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "mode traces"):
                trace_soundbooster.dispatch_base(b"", {}, mode)
        with self.assertRaisesRegex(ValueError, "reviewed 12-control"):
            trace_soundbooster.trace_mbdrc(b"", {"four_12_value_blocks": [],
                                               "remaining_control_arguments": [12, 2, -1]})
        with self.assertRaisesRegex(ValueError, "Only reviewed backend"):
            trace_soundbooster.trace_backend_parameters(b"", "other", [])

    def test_conditional_fourth_order_highpass(self):
        for cutoff in (75, 100):
            self.assertAlmostEqual(soundbooster.highpass_response_db(cutoff, cutoff),
                                   -10 * math.log10(2))
            self.assertAlmostEqual(soundbooster.highpass_response_db(cutoff, 24000), 0)
            self.assertLess(soundbooster.highpass_response_db(cutoff, cutoff / 2), -24)
            self.assertGreater(soundbooster.highpass_response_db(cutoff, cutoff * 2), -0.02)
        for args in ((0, 75), (75, 0), (24000, 75), (75, 25000), (math.nan, 75),
                     (75, math.inf), (75, 75, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                soundbooster.highpass_response_db(*args)
        with self.assertRaisesRegex(ValueError, "Only reviewed"):
            trace_soundbooster.trace_highpass(b"", 50)

    def test_compression_mode2_curve_model(self):
        unity = soundbooster.compression_curve_mode2(0, 0)
        self.assertEqual(unity["first_five_values"], unity["second_five_values"])
        self.assertEqual(soundbooster.compression_curve_mode2(3, -12)["second_five_values"],
                         [-93, -47, -32, -20.75, -12])
        for gain in range(-30, 31):
            for threshold in range(-30, 1):
                curve = soundbooster.compression_curve_mode2(gain, threshold)
                self.assertEqual(curve["point_count"], 5)
                self.assertEqual(curve["second_five_values"][-1], threshold)
                self.assertEqual(curve["second_five_values"],
                                 sorted(curve["second_five_values"]))
        for args in ((31, 0), (0, 1), (-31, 0), (0, -31), (math.nan, 0), (0, math.inf)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                soundbooster.compression_curve_mode2(*args)

    def test_report_never_claims_complete_dsp(self):
        payload = parameters()
        with mock.patch.object(soundbooster, "PARAMETER_SHA256", hashlib.sha256(payload).hexdigest()):
            report = soundbooster.analyze(payload)
        self.assertFalse(report["runtime_bank_selection_verified"])
        self.assertFalse(report["fixed_point_bit_exact"])
        self.assertIn("multiband DRC", report["excluded"])
        self.assertEqual(len(report["banks"]), 8)
        bank = report["banks"]["AA"]
        response = bank["static_amf_only_response_db"]
        self.assertEqual(len(response), 20)
        expected = 8 * soundbooster.response_db(soundbooster.peaking_coefficients(1000, 250, 3), 1031)
        self.assertAlmostEqual(next(item["gain_db"] for item in response if item["frequency_hz"] == 1031),
                               expected)

    def test_disabled_bank_and_unknown_filter_types(self):
        payload = parameters().replace(b"AAU,1", b"AAU,0").replace(
            b"AAM,1,1,1,1,1,1,1,1", b"AAM,0,0,0,0,0,0,0,0")
        with mock.patch.object(soundbooster, "PARAMETER_SHA256", hashlib.sha256(payload).hexdigest()):
            bank = soundbooster.analyze(payload)["banks"]["AA"]
        self.assertFalse(bank["enabled"])
        self.assertTrue(all(item["coefficients_b0_b1_b2_a1_a2"] is None for item in bank["filters"]))
        self.assertTrue(all(point["gain_db"] == 0 for point in bank["static_amf_only_response_db"]))
        for invalid in (
            payload.replace(b"AAM,0,0,0,0,0,0,0,0", b"AAM,1,0,0,0,0,0,0,0"),
            payload.replace(b"AAU,0", b"AAU,2"),
        ):
            with mock.patch.object(soundbooster, "PARAMETER_SHA256", hashlib.sha256(invalid).hexdigest()):
                with self.assertRaisesRegex(ValueError, "enable/type"):
                    soundbooster.analyze(invalid)


@unittest.skipUnless(os.environ.get("SOUNDBOOSTER_VENDOR"), "Optional local reviewed firmware and Unicorn required")
class PrivateSoundBoosterControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        vendor = Path(os.environ["SOUNDBOOSTER_VENDOR"])
        cls.engine = (vendor / "lib/lib_SoundBooster_ver1050.so").read_bytes()
        payload = (vendor / "etc/SoundBoosterParam.txt").read_bytes()
        cls.report = trace_soundbooster.trace_controls(cls.engine, payload)
        cls.rows = soundbooster.parse_rows(payload.decode("ascii"))

    def test_original_control_dispatch_and_highpass(self):
        for mode in ("legacy", "music"):
            calls = self.report[mode + "_calls"]
            self.assertEqual([call["group"] for call in calls], ["A", "B"])
            for call in calls:
                self.assertEqual(call["hpf"], [1, 75, 0])
                self.assertEqual(call["amf"]["filter_count"], 8)
                self.assertEqual(call["fft_hpf"], [1, 75, 8, 0])
        for call in self.report["legacy_calls"]:
            group = call["group"]
            self.assertEqual(call["volume_fields_after_clamp"], [0, 0, 0])
            self.assertEqual(call["fft_mbdrc"]["enable"], 1)
            self.assertEqual(call["fft_mbdrc"]["four_12_value_blocks"],
                             [self.rows[group + "L"][start:start + 12] for start in (1, 13, 25, 37)])
            self.assertEqual(call["fft_mbdrc"]["remaining_control_arguments"], [12, 2, -1])
            self.assertEqual(call["fft_obdrc"], [1, 3, -4, 100, 500, 0, 2, 0])
            self.assertEqual(call["fft_configure_obdrc"], [1, 0])
            self.assertEqual(call["pre_drc_arguments"], [4, 2, 0])
        for call in self.report["music_calls"]:
            self.assertEqual(call["volume_table_after_clamp"], [-100] + [0] * 15)
            self.assertEqual(call["drc"]["enable_by_level"], [0] + [1] * 15)
        self.assertEqual([check["cutoff_hz"] for check in self.report["hpf_coefficient_checks"]], [75, 100])
        for check in self.report["hpf_coefficient_checks"]:
            self.assertLessEqual(check["max_sampled_response_error_db"], 0.02)

    def test_mode_bank_selection_with_distinct_synthetic_markers(self):
        rows = {key: values[:] for key, values in self.rows.items()}
        for group in "AB":
            rows[group + "CA"][0] += 1
        calls = trace_soundbooster.trace_interface(self.engine, rows)
        for call in calls:
            for mode, index, bank in ((1, 50, "A"), (2, 77, "C")):
                outgoing = trace_soundbooster.dispatch_base(self.engine, call, mode)
                group = "AB"[call["object_index"]]
                self.assertEqual(outgoing[index:index + 33],
                                 trace_soundbooster.amf_values(rows, group + bank))

    def test_original_volume_clamp_boundaries(self):
        values = [-2147483648, -101, -100, -99, -1, 0, 1, 2147483647] * 2
        trace = trace_soundbooster.ControlTrace(self.engine)
        trace.allowed = [(trace_soundbooster.BASE + 0x11B10, trace_soundbooster.BASE + 0x11E7C)]
        trace.write(trace_soundbooster.DATA, values)
        trace.run(0x11B10, [trace_soundbooster.DATA])
        self.assertEqual(trace.read(trace_soundbooster.OBJECT + 0x17F8, 16),
                         [min(0, max(-100, value)) for value in values])
        for normal, alternate in zip(values, reversed(values)):
            trace = trace_soundbooster.ControlTrace(self.engine)
            trace.allowed = [(trace_soundbooster.BASE + 0x100F8, trace_soundbooster.BASE + 0x101E0)]
            trace.run(0x100F8, [normal, 1, alternate])
            self.assertEqual(trace.read(trace_soundbooster.OBJECT + 0xAE0, 3),
                             [min(0, max(-100, normal)), 1, min(0, max(-100, alternate))])

    def test_legacy_invalid_drc_fields_reset_not_saturated(self):
        rows = {key: values[:] for key, values in self.rows.items()}
        for index, value in ((1, 31), (13, 1), (25, 2001), (37, -1)):
            rows["AL"][index] = value
        call = trace_soundbooster.trace_interface(self.engine, rows)[0]
        result = trace_soundbooster.trace_legacy(self.engine, rows, call)
        self.assertEqual([block[0] for block in result["fft_mbdrc"]["four_12_value_blocks"]], [0] * 4)

    def test_original_compression_backend_partition(self):
        for call in self.report["legacy_calls"]:
            source = call["fft_mbdrc"]["four_12_value_blocks"]
            filx, emqf = call["mbdrc_backends"]
            self.assertEqual((filx["backend"], filx["band_count"]), ("FILX", 11))
            self.assertEqual((emqf["backend"], emqf["band_count"]), ("EMQF", 3))
            self.assertEqual(filx["four_control_blocks"], [[0] + block[2:] for block in source])
            self.assertEqual(emqf["four_control_blocks"], [block[:2] + [0] for block in source])
            for backend in (filx, emqf):
                checks = backend["parameter_checks"]
                self.assertTrue(checks["mode2_curve_model_exact_for_supplied_controls"])
                self.assertEqual(checks["max_integer_errors_gain_threshold_attack_release"], [0] * 4)

    def test_original_backend_parameter_boundaries_and_time_scaling(self):
        for backend, count in (("FILX", 11), ("EMQF", 3)):
            for gain in (-30, -6, 0, 3, 4, 5, 30):
                for threshold in (-30, -12, 0):
                    for frame in (512, 1024):
                        with self.subTest(backend=backend, gain=gain, threshold=threshold, frame=frame):
                            blocks = [[gain] * count, [threshold] * count,
                                      ([0, 1, 2000] * count)[:count], ([2000, 1, 0] * count)[:count]]
                            report = trace_soundbooster.trace_backend_parameters(
                                self.engine, backend, blocks, frame_size=frame)
                            self.assertTrue(report["mode2_curve_model_exact_for_supplied_controls"])
                            self.assertEqual(report["mode2_gain_curve_records"][0],
                                             soundbooster.compression_curve_mode2(gain, threshold))


if __name__ == "__main__":
    unittest.main()

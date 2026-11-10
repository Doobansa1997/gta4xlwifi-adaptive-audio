import copy
import hashlib
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import probe_soundbooster
import soundbooster
from test_soundbooster import parameters


def report():
    cases = []
    for frequency in (0, 157, 340, 1000, 7400):
        for level in (-36, -18, -6):
            gain = {-36: 6, -18: 0, -6: -6}[level]
            cases.append({"frequency_hz": frequency, "input_dbfs": level,
                          "input_energy": 100000 if frequency else 0,
                          "output_energy": 100000 * 10 ** (gain / 10) if frequency else 0,
                          "peak": 100 if frequency else 0, "changed_samples": 49152 if frequency else 0,
                          "clipped_samples": 0, "measured_samples": 49152})
    return {"engine_mode": 2, "sample_rate_hz": 48000, "pcm_bits": 16,
            "frame_count_per_call": 256, "cases": cases}


class NativeProbeTests(unittest.TestCase):
    def test_vendor_runtime_requires_exact_live_identity(self):
        valid = f"{probe_soundbooster.VENDOR_RUNTIME_SHA256}  {probe_soundbooster.VENDOR_RUNTIME_PATH}\n"
        probe_soundbooster.validate_vendor_runtime_identity(valid)
        for invalid in ("", "Permission denied", valid.replace("05b", "15b"),
                        valid.replace("/vendor/lib/", "/system/lib/"), valid + valid):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "preload refused"):
                probe_soundbooster.validate_vendor_runtime_identity(invalid)

    def test_adapter_report_scope_and_matrix(self):
        evidence = {"format": 1, "pointer_bits": 64, "compared_frames": 137472, "checks": 8000,
                    "ndk_shared_runtime_absent": False, "platform_shared_runtime_present": False,
                    "vendor_shared_runtime_present": False,
                    "accumulation_verified": True, "accumulation_compared_frames": 1060032,
                    "pcm16_and_float_verified": True,
                    "direct_engine_exact_match": True, "speaker_only_bypass_verified": True,
                    "android_service_integration_verified": False, "aosp_header_abi_verified": True}
        evidence["process_timing"] = [
            {"pcm_format": pcm, "calls": 192, "median_period_ratio": 0.1,
             "p99_period_ratio": 0.2, "max_period_ratio": 0.3} for pcm in (1, 5)]
        self.assertEqual(probe_soundbooster.validate_effect_report(evidence, True), evidence)
        arm32 = {**evidence, "pointer_bits": 32}
        self.assertEqual(probe_soundbooster.validate_effect_report(arm32, True, 32), arm32)
        with self.assertRaisesRegex(ValueError, "architecture"):
            probe_soundbooster.validate_effect_report(arm32, True, 64)
        isolated = {**arm32, "ndk_shared_runtime_absent": True}
        self.assertEqual(probe_soundbooster.validate_effect_report(isolated, True, 32, True), isolated)
        with self.assertRaisesRegex(ValueError, "isolation"):
            probe_soundbooster.validate_effect_report(arm32, True, 32, True)
        vendor = {**isolated, "vendor_shared_runtime_present": True}
        self.assertEqual(probe_soundbooster.validate_effect_report(vendor, True, 32, True, True), vendor)
        for invalid in (
                {**vendor, "platform_shared_runtime_present": True},
                {**vendor, "vendor_shared_runtime_present": False}):
            with self.assertRaises(ValueError):
                probe_soundbooster.validate_effect_report(invalid, True, 32, True, True)
        for field, value in (("format", 2), ("compared_frames", 1), ("checks", 6999),
                             ("pointer_bits", 32),
                             ("ndk_shared_runtime_absent", True),
                             ("platform_shared_runtime_present", None),
                             ("vendor_shared_runtime_present", True),
                             ("accumulation_verified", False), ("accumulation_compared_frames", 1),
                             ("pcm16_and_float_verified", False),
                             ("direct_engine_exact_match", False),
                             ("speaker_only_bypass_verified", False),
                             ("android_service_integration_verified", True),
                             ("aosp_header_abi_verified", False)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                probe_soundbooster.validate_effect_report({**evidence, field: value}, True)
        for value in (math.nan, -1, 0):
            invalid = copy.deepcopy(evidence)
            invalid["process_timing"][0]["p99_period_ratio"] = value
            with self.subTest(timing=value), self.assertRaises(ValueError):
                probe_soundbooster.validate_effect_report(invalid)
        slow = copy.deepcopy(evidence)
        slow["process_timing"][0].update(p99_period_ratio=2, max_period_ratio=3)
        self.assertFalse(probe_soundbooster.validate_effect_report(slow)["shell_timing_p99_within_audio_period"])

    def test_static_runtime_dependency_and_export_isolation(self):
        for abi in ("armeabi-v7a", "arm64-v8a"):
            dependencies = {"effect": ["libc.so", "libdl.so", "libm.so", "liblog.so"],
                            "harness": ["libc.so", "libdl.so", "libm.so"]}
            exports = {"effect": ["AELI"], "harness": []}
            result = probe_soundbooster.validate_static_linkage(abi, dependencies, exports)
            self.assertTrue(result["no_direct_shared_cpp_dependency"])
            for invalid in ("libc++_shared.so", "libc++.so", "/tmp/engine.so"):
                with self.subTest(abi=abi, dependency=invalid), self.assertRaises(ValueError):
                    probe_soundbooster.validate_static_linkage(
                        abi, {**dependencies, "effect": dependencies["effect"] + [invalid]}, exports)
            for invalid in ({**exports, "harness": ["_Znwj"]},
                            {**exports, "effect": exports["effect"] + ["unexpected"]},
                            {**exports, "effect": exports["effect"][1:]}):
                with self.subTest(abi=abi, exports=invalid), self.assertRaises(ValueError):
                    probe_soundbooster.validate_static_linkage(abi, dependencies, invalid)

    def test_linked_vendor_group_requires_both_exact_dependencies(self):
        engine = "/vendor/lib/soundfx/lib_SoundBooster_ver1050.so"
        runtime = probe_soundbooster.VENDOR_RUNTIME_PATH
        dependencies = {"effect": ["libc.so", "libdl.so", "libm.so", "liblog.so", runtime, engine],
                        "harness": ["libc.so", "libdl.so", "libm.so"]}
        exports = {"effect": ["AELI"], "harness": []}
        result = probe_soundbooster.validate_static_linkage(
            "armeabi-v7a", dependencies, exports, True, engine)
        self.assertFalse(result["no_direct_shared_cpp_dependency"])
        for missing in (runtime, engine):
            invalid = {**dependencies, "effect": [item for item in dependencies["effect"] if item != missing]}
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                probe_soundbooster.validate_static_linkage("armeabi-v7a", invalid, exports, True, engine)
        for invalid in (
                {**dependencies, "effect": dependencies["effect"] + ["libc++_shared.so"]},
                {**dependencies, "harness": dependencies["harness"] + [runtime]},
                {**dependencies, "effect": [item.replace("/vendor/lib/libc++", "/system/lib/libc++")
                                          for item in dependencies["effect"]]},
                {**dependencies, "effect": dependencies["effect"] + [engine]}):
            with self.assertRaises(ValueError):
                probe_soundbooster.validate_static_linkage("armeabi-v7a", invalid, exports, True, engine)
        with self.assertRaises(ValueError):
            probe_soundbooster.validate_static_linkage("arm64-v8a", dependencies, exports, True, engine)
        with self.assertRaisesRegex(ValueError, "Unreviewed linked vendor runtime"):
            with tempfile.TemporaryDirectory() as temporary:
                runtime_file = Path(temporary) / "libc++.so"
                runtime_file.write_bytes(b"unreviewed")
                probe_soundbooster.vendor_runtime_import(
                    Path(temporary), "compiler", runtime_file, Path(temporary) / "stub.so", engine)

    def test_engine_relocation_fixture_requires_complete_reviewed_coverage(self):
        for abi, counts in probe_soundbooster.ENGINE_CPP_SLOT_COUNTS.items():
            width = 4 if abi == "armeabi-v7a" else 8
            kind = "R_ARM_ABS32" if width == 4 else "R_AARCH64_ABS64"
            symbols = [symbol for symbol, count in counts.items() for _ in range(count)]
            lines = [f"{0x1000 + index * width:x} 00000000 {kind} 00000000 {symbol}"
                     for index, symbol in enumerate(symbols)]
            text = "\n".join(lines)
            relocations = probe_soundbooster.engine_relocations(abi, text)
            self.assertEqual(len(relocations), 105 if width == 4 else 31)
            self.assertEqual([symbol for _, symbol in relocations], symbols)
            for invalid in (
                "\n".join(lines[1:]), text + "\n" + lines[0],
                text.replace(kind, "R_UNREVIEWED", 1),
                text.replace("1000 ", "1001 ", 1),
                text.replace("1000 ", f"{0x1000 + width:x} ", 1),
            ):
                with self.subTest(abi=abi, invalid=invalid[:80]), self.assertRaises(ValueError):
                    probe_soundbooster.engine_relocations(abi, invalid)

    def test_engine_binding_evidence_requires_all_slots_and_known_providers(self):
        relocations = [(4, "_Znwj"), (8, "_ZdlPv"), (12, "_ZdlPv")]
        evidence = [
            {"symbol": "_Znwj", "provider": "platform_cpp", "slots": 1},
            {"symbol": "_ZdlPv", "provider": "platform_cpp", "slots": 2},
        ]
        probe_soundbooster.validate_bindings(evidence, relocations, True)
        shared = copy.deepcopy(evidence)
        shared[1]["provider"] = "ndk_shared"
        probe_soundbooster.validate_bindings(shared, relocations, False)
        vendor = [{**binding, "provider": "vendor_cpp"} for binding in evidence]
        probe_soundbooster.validate_bindings(vendor, relocations, True, True)
        for invalid in (evidence, shared, [vendor[0], evidence[1]]):
            with self.assertRaises(ValueError):
                probe_soundbooster.validate_bindings(invalid, relocations, True, True)
        for invalid in (
            None, evidence[:1], evidence + [evidence[0]],
            [evidence[0], None],
            [{**evidence[0], "slots": True}, evidence[1]],
            [{**evidence[0], "symbol": []}, evidence[1]],
            [evidence[0], evidence[0]],
            [evidence[0], {**evidence[1], "slots": 1}],
            [evidence[0], {**evidence[1], "provider": "unknown"}],
            [evidence[0], {**evidence[1], "provider": []}],
            [evidence[0], {**evidence[1], "provider": "bridge_embedded"}],
            [evidence[0], {**evidence[1], "symbol": "unreviewed"}], shared,
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                probe_soundbooster.validate_bindings(invalid, relocations, True)
        with self.assertRaises(ValueError):
            probe_soundbooster.validate_bindings(vendor, relocations, False)

    def test_original_aosp_header_identity_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for path in probe_soundbooster.AOSP_EFFECT_HEADERS:
                target = directory / path
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(b"unreviewed header")
            with self.assertRaisesRegex(ValueError, "Unreviewed AOSP"):
                probe_soundbooster.validate_aosp_headers(directory)

    def test_native_payload_schema_and_identity(self):
        payload = parameters()
        with mock.patch.object(soundbooster, "PARAMETER_SHA256", hashlib.sha256(payload).hexdigest()):
            binary = probe_soundbooster.parameter_payload(payload)
        self.assertEqual(len(binary), (16 + 30 + 4 * 1072) * 4)
        values = struct.unpack(f"<{len(binary) // 4}i", binary)
        self.assertEqual(values[:46], (0,) * 46)
        amf_offset = 46 + 3 + 17 + 58 + 16 * 58
        self.assertEqual(values[amf_offset:amf_offset + 33], tuple([1000, 250, 3] * 8 + [1] * 9))
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            probe_soundbooster.parameter_payload(payload)

    def test_report_requires_real_nonlinear_pcm_evidence(self):
        result = probe_soundbooster.validate_report(report(), 2)
        self.assertIsNone(result["cases"][0]["rms_gain_db"])
        self.assertAlmostEqual(result["cases"][3]["rms_gain_db"], 6)
        self.assertAlmostEqual(result["cases"][5]["rms_gain_db"], -6)

    def test_invalid_native_reports_refused(self):
        original = report()
        variants = []
        wrong_mode = copy.deepcopy(original)
        wrong_mode["engine_mode"] = 1
        variants.append(wrong_mode)
        missing_case = copy.deepcopy(original)
        missing_case["cases"].pop()
        variants.append(missing_case)
        for field, value in (("output_energy", math.nan), ("output_energy", -1),
                             ("input_energy", 0), ("output_energy", 0),
                             ("output_energy", 10 ** 20), ("peak", 32769),
                             ("measured_samples", 2), ("changed_samples", 49153),
                             ("clipped_samples", 1)):
            invalid = copy.deepcopy(original)
            invalid["cases"][3][field] = value
            variants.append(invalid)
        noisy_silence = copy.deepcopy(original)
        noisy_silence["cases"][0].update(output_energy=1, peak=1)
        variants.append(noisy_silence)
        linear = copy.deepcopy(original)
        for case in linear["cases"]:
            case["changed_samples"] = 0
            case["output_energy"] = case["input_energy"]
        variants.append(linear)
        linear_changed = copy.deepcopy(linear)
        for case in linear_changed["cases"]:
            case["changed_samples"] = 1
        variants.append(linear_changed)
        for index, invalid in enumerate(variants):
            with self.subTest(variant=index), self.assertRaises(ValueError):
                probe_soundbooster.validate_report(invalid, 2)


if __name__ == "__main__":
    unittest.main()

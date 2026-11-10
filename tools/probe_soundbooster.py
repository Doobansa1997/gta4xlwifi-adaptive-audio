#!/usr/bin/env python3
"""Build/run an opt-in temporary Android in-memory probe; never enable an audio effect."""

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import struct
import subprocess
import uuid

import soundbooster
from trace_soundbooster import amf_values

ROOT = Path(__file__).resolve().parents[1]
ENGINE64_SHA256 = "b221f73f65aeae13b10200b90d05f493c178ced1e8f6441291bda81eaa6cc3c0"
ENGINE32_SHA256 = "5dd9b49a3718a5529ee160e4a4bdd5552c5cb494a329e022a7d3166bff6d8bac"
VENDOR_RUNTIME_PATH = "/vendor/lib/libc++.so"
VENDOR_RUNTIME_SHA256 = "05b594f7ce7f249e743f2e170ebe844e157d9a5e016ffbadf657d6d6d59ed663"
ARCHITECTURES = {
    "arm64-v8a": ("lib64", "aarch64-linux-android", "aarch64-linux-android29", ENGINE64_SHA256),
    "armeabi-v7a": ("lib", "arm-linux-androideabi", "armv7a-linux-androideabi29", ENGINE32_SHA256),
}
STATIC_EXPORTS = {"AELI"}
ENGINE_CPP_SLOT_COUNTS = {
    "armeabi-v7a": {
        "_ZTVN10__cxxabiv117__class_type_infoE": 14,
        "_ZTVN10__cxxabiv120__si_class_type_infoE": 14,
        "__cxa_pure_virtual": 71, "__cxa_call_unexpected": 2,
        "_Znwj": 1, "_ZdlPv": 1, "__cxa_end_cleanup": 1, "__gxx_personality_v0": 1,
    },
    "arm64-v8a": {
        "_ZTVN10__cxxabiv117__class_type_infoE": 14,
        "_ZTVN10__cxxabiv120__si_class_type_infoE": 14,
        "_Znwm": 1, "_ZdlPv": 1, "__gxx_personality_v0": 1,
    },
}


def validate_vendor_runtime_identity(output):
    if output.split() != [VENDOR_RUNTIME_SHA256, VENDOR_RUNTIME_PATH]:
        raise ValueError("Unreviewed installed vendor C++ runtime; preload refused")


def vendor_runtime_import(toolchain, compiler, runtime, output, engine_path):
    if hashlib.sha256(runtime.read_bytes()).hexdigest() != VENDOR_RUNTIME_SHA256:
        raise ValueError("Unreviewed linked vendor runtime")
    # A link-only import stub pins DT_NEEDED to the vendor path, not system libc++.
    run(str(toolchain / "bin" / (compiler + "-clang")), "-shared", "-nostdlib",
        "-x", "c", "/dev/null", "-Wl,-soname," + VENDOR_RUNTIME_PATH, "-o", str(output))
    engine_import = output.with_name("engine-import.so")
    run(str(toolchain / "bin" / (compiler + "-clang")), "-shared", "-nostdlib",
        "-x", "c", "/dev/null", "-Wl,-soname," + engine_path, "-o", str(engine_import))
    return ["-Wl,--no-as-needed", str(output), str(engine_import), "-Wl,--as-needed"]


def engine_relocations(abi, text):
    required = ENGINE_CPP_SLOT_COUNTS[abi]
    allowed = ({"R_ARM_ABS32", "R_ARM_GLOB_DAT", "R_ARM_JUMP_SLOT"} if abi == "armeabi-v7a"
               else {"R_AARCH64_ABS64", "R_AARCH64_GLOB_DAT", "R_AARCH64_JUMP_SLOT"})
    result = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[4] not in required:
            continue
        if fields[2] not in allowed:
            raise ValueError("Unreviewed C++ relocation type")
        offset = int(fields[0], 16)
        if offset <= 0 or offset % (4 if abi == "armeabi-v7a" else 8):
            raise ValueError("Invalid engine relocation offset")
        result.append((offset, fields[4]))
    if Counter(symbol for _, symbol in result) != required or len({offset for offset, _ in result}) != len(result):
        raise ValueError("Incomplete or duplicate engine C++ relocation coverage")
    return result


def validate_bindings(bindings, relocations, static_runtime, vendor_runtime=False):
    expected = {}
    for _, symbol in relocations:
        expected[symbol] = expected.get(symbol, 0) + 1
    if not isinstance(bindings, list) or len(bindings) != len(expected):
        raise ValueError("Missing engine runtime binding evidence")
    seen = set()
    providers = {"platform_cpp"} if static_runtime else {"platform_cpp", "ndk_shared"}
    if vendor_runtime:
        providers = {"vendor_cpp"}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError("Invalid engine runtime binding record")
        symbol = binding.get("symbol")
        if (not isinstance(symbol, str) or symbol not in expected or symbol in seen or
                type(binding.get("slots")) is not int or binding["slots"] != expected[symbol] or
                not isinstance(binding.get("provider"), str) or binding["provider"] not in providers):
            raise ValueError(f"Invalid or incomplete engine runtime binding evidence: {binding!r}")
        seen.add(symbol)


def validate_static_linkage(abi, dependencies, exports, linked_vendor_runtime=False, engine_path=None):
    if abi not in ARCHITECTURES:
        raise ValueError("Unsupported static runtime ABI")
    expected = STATIC_EXPORTS
    if set(exports.get("effect", [])) != expected or exports.get("harness") != []:
        raise ValueError("Unexpected static-runtime exports or harness symbol leakage")
    allowed = {"libc.so", "libm.so", "libdl.so", "liblog.so"}
    if linked_vendor_runtime:
        if abi != "armeabi-v7a" or dependencies.get("effect", []).count(VENDOR_RUNTIME_PATH) != 1:
            raise ValueError("Missing linked ARM32 vendor runtime dependency")
        if not engine_path or dependencies.get("effect", []).count(engine_path) != 1:
            raise ValueError("Missing engine in vendor runtime local dependency group")
    if set(dependencies) != {"effect", "harness"} or any(
            not values or len(values) != len(set(values)) or
            not set(values) <= (allowed | {VENDOR_RUNTIME_PATH, engine_path}
                               if linked_vendor_runtime and role == "effect" else allowed)
            for role, values in dependencies.items()):
        raise ValueError("Unexpected shared dependency in isolated static-runtime experiment")
    return {"dependencies": dependencies, "effect_exports": sorted(expected),
            "harness_exports": [], "no_direct_shared_cpp_dependency": not linked_vendor_runtime}


def inspect_static_linkage(toolchain, abi, effect, executable, linked_vendor_runtime=False, engine_path=None):
    dependencies, exports = {}, {}
    for role, path in (("effect", effect), ("harness", executable)):
        dynamic = run(str(toolchain / "bin/llvm-readelf"), "--dynamic", str(path)).stdout
        dependencies[role] = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", dynamic)
        symbols = run(str(toolchain / "bin/llvm-nm"), "-D", "--defined-only",
                      "--format=posix", str(path)).stdout
        exports[role] = [line.split()[0] for line in symbols.splitlines() if line.strip()]
    return validate_static_linkage(abi, dependencies, exports, linked_vendor_runtime, engine_path)
AOSP_EFFECT_HEADERS = {
    "hardware/audio_effect.h": "35465295c44521ee7e548bb73c4980d0641d670651328f2002b56b5f5f5d1e81",
    "system/audio_effect.h": "4279ef33d0d0cc29f38c78ef4bc41affd1d0937f6f7d2de56ddc367c549fae01",
    "system/audio_effect-base.h": "0dc8d6260e9cad4e2b26a06806a5b38732ad45bcf5963aa7d80359ea9dd9702e",
}


def parameter_payload(payload):
    soundbooster.analyze(payload)
    rows = soundbooster.parse_rows(payload.decode("ascii"))
    values = rows["S"] + [0] * 30
    for group in "ABCD":
        values.extend(rows[group + "H"] + rows[group + "F"] + rows[group + "L"])
        values.extend(value for level in "ABCDEFGHIJKLMNOP" for value in rows[group + "M" + level])
        values.extend(amf_values(rows, group + "A") + amf_values(rows, group + "C"))
    return struct.pack(f"<{len(values)}i", *values)


def validate_report(report, mode):
    if (report.get("engine_mode"), report.get("sample_rate_hz"), report.get("pcm_bits"),
            report.get("frame_count_per_call")) != (mode, 48000, 16, 256):
        raise ValueError("Unexpected native probe format")
    cases = report["cases"]
    expected = [(frequency, level) for frequency in (0, 157, 340, 1000, 7400)
                for level in (-36, -18, -6)]
    if [(case["frequency_hz"], case["input_dbfs"]) for case in cases] != expected:
        raise ValueError("Unexpected native probe case matrix")
    for case in cases:
        for field in ("input_energy", "output_energy", "peak", "changed_samples",
                      "clipped_samples", "measured_samples"):
            if not isinstance(case[field], (int, float)) or not math.isfinite(case[field]) or case[field] < 0:
                raise ValueError(f"Invalid native probe measurement: {field}")
        if case["measured_samples"] != 49152 or case["peak"] > 32768:
            raise ValueError("Unexpected native probe measurement bounds")
        if case["output_energy"] > case["measured_samples"] * case["peak"] ** 2:
            raise ValueError("Output energy exceeds measured peak bound")
        if any(case[field] > case["measured_samples"] for field in ("changed_samples", "clipped_samples")):
            raise ValueError("Invalid native probe sample counts")
        if case["frequency_hz"] == 0:
            if case["input_energy"] != 0 or case["output_energy"] != 0:
                raise ValueError("Fresh-state silence did not remain silent")
            case["rms_gain_db"] = None
        else:
            if case["input_energy"] <= 0 or case["output_energy"] <= 0:
                raise ValueError("Native probe tone has zero energy")
            if case["clipped_samples"]:
                raise ValueError("Native probe tone clipped; do not infer playback suitability")
            case["rms_gain_db"] = 10 * math.log10(case["output_energy"] / case["input_energy"])
    if not any(case["changed_samples"] for case in cases):
        raise ValueError("No processed sample changed; engine processing not demonstrated")
    for frequency in (157, 340):
        matching = [case for case in cases if case["frequency_hz"] == frequency]
        if matching[0]["rms_gain_db"] - matching[-1]["rms_gain_db"] < 1:
            raise ValueError("Expected level-dependent processing was not observed")
    return report


def run(*arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {shlex.join(arguments)}\n"
                           f"{result.stdout}\n{result.stderr}")
    return result


def validate_aosp_headers(directory):
    for path, digest in AOSP_EFFECT_HEADERS.items():
        if hashlib.sha256((directory / path).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Unreviewed AOSP effect header: {path}")


def validate_effect_report(report, require_aosp=False, pointer_bits=64, static_runtime=False,
                           vendor_runtime=False):
    if report.get("pointer_bits") != pointer_bits:
        raise ValueError("Adapter process architecture does not match requested ABI")
    if report.get("ndk_shared_runtime_absent") is not static_runtime:
        raise ValueError("Missing or unexpected process shared-runtime isolation evidence")
    if type(report.get("platform_shared_runtime_present")) is not bool:
        raise ValueError("Missing platform runtime mapping evidence")
    if report.get("vendor_shared_runtime_present") is not vendor_runtime:
        raise ValueError("Missing or unexpected vendor runtime mapping evidence")
    if vendor_runtime and (not static_runtime or pointer_bits != 32 or
                           report["platform_shared_runtime_present"]):
        raise ValueError("Vendor-runtime experiment was not isolated from system libc++")
    if report.get("format") != 1 or report.get("compared_frames") != 137472:
        raise ValueError("Unexpected adapter comparison matrix")
    if not isinstance(report.get("checks"), int) or report["checks"] < 7000:
        raise ValueError("Incomplete adapter checks")
    if (report.get("direct_engine_exact_match") is not True or
            report.get("speaker_only_bypass_verified") is not True or
            report.get("pcm16_and_float_verified") is not True or
            report.get("accumulation_verified") is not True or
            report.get("accumulation_compared_frames") != 1060032 or
            report.get("android_service_integration_verified") is not False):
        raise ValueError("Invalid adapter evidence scope")
    if report.get("aosp_header_abi_verified") not in (True, False) or (
            require_aosp and report["aosp_header_abi_verified"] is not True):
        raise ValueError("Missing original AOSP ABI verification")
    timings = report.get("process_timing", [])
    if [timing.get("pcm_format") for timing in timings] != [1, 5]:
        raise ValueError("Missing PCM16/float process timing")
    for timing in timings:
        ratios = [timing.get(key) for key in ("median_period_ratio", "p99_period_ratio", "max_period_ratio")]
        if timing.get("calls") != 192 or any(
                not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
                for value in ratios) or ratios != sorted(ratios):
            raise ValueError("Invalid process timing measurements")
    report["shell_timing_p99_within_audio_period"] = all(
        timing["p99_period_ratio"] < 1 for timing in timings)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--abi", choices=ARCHITECTURES, default="arm64-v8a")
    parser.add_argument("--ndk", type=Path, default=os.environ.get("ANDROID_NDK_HOME"))
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial")
    parser.add_argument("--run-device", action="store_true", help="Opt in to temporary shell-process execution")
    parser.add_argument("--effect-harness", action="store_true",
                        help="Test the experimental legacy-effect adapter, not system installation")
    parser.add_argument("--static-runtime", action="store_true",
                        help="Effect experiment with embedded C++ runtime, no shared runtime transfer")
    parser.add_argument("--vendor-runtime", action="store_true",
                        help="ARM32 static harness with hash-checked installed vendor libc++ preload")
    parser.add_argument("--linked-vendor-runtime", type=Path,
                        help="Link hash-checked ARM32 vendor libc++ into the effect's local dependency group; no preload")
    parser.add_argument("--vendor-search-path", action="store_true",
                        help="Use /vendor/lib for ARM32 harness dependencies instead of the shell's system libraries")
    parser.add_argument("--aosp-include", type=Path,
                        help="Optional original AOSP include root for independent adapter ABI checks")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.ndk is None:
        parser.error("--ndk or ANDROID_NDK_HOME is required")
    if args.run_device and not args.serial:
        parser.error("--run-device requires an explicit --serial")
    if args.aosp_include and not args.effect_harness:
        parser.error("--aosp-include requires --effect-harness")
    if args.static_runtime and not args.effect_harness:
        parser.error("--static-runtime requires --effect-harness")
    if args.vendor_runtime and (not args.static_runtime or args.abi != "armeabi-v7a"):
        parser.error("--vendor-runtime requires --static-runtime --effect-harness --abi armeabi-v7a")
    if args.vendor_search_path and (not args.static_runtime or args.abi != "armeabi-v7a" or args.vendor_runtime):
        parser.error("--vendor-search-path requires ARM32 static effect harness without preload")
    if args.linked_vendor_runtime:
        if args.vendor_runtime or not args.static_runtime or args.abi != "armeabi-v7a":
            parser.error("--linked-vendor-runtime requires ARM32 static effect harness without --vendor-runtime")
        if hashlib.sha256(args.linked_vendor_runtime.read_bytes()).hexdigest() != VENDOR_RUNTIME_SHA256:
            raise ValueError("Unreviewed linked vendor runtime")
    if args.aosp_include:
        validate_aosp_headers(args.aosp_include)
    library_directory, triple, compiler, engine_hash = ARCHITECTURES[args.abi]
    engine = args.vendor / library_directory / "lib_SoundBooster_ver1050.so"
    if hashlib.sha256(engine.read_bytes()).hexdigest() != engine_hash:
        raise ValueError(f"Unreviewed {args.abi} engine; native probe refused")
    payload = parameter_payload((args.vendor / "etc/SoundBoosterParam.txt").read_bytes())
    directory = ROOT / "build/samsung/native-probe" / args.abi
    if args.static_runtime:
        directory = directory / "static-runtime"
    if args.vendor_runtime:
        directory = directory / "vendor-runtime"
    if args.linked_vendor_runtime:
        directory = directory / "linked-vendor-runtime"
    directory.mkdir(parents=True, exist_ok=True)
    parameters = directory / "parameters.bin"
    parameters.write_bytes(payload)
    host = {"Darwin": "darwin-x86_64", "Linux": "linux-x86_64"}.get(platform.system())
    if host is None:
        raise ValueError("Builds support macOS and Linux only")
    toolchain = args.ndk / "toolchains/llvm/prebuilt" / host
    remote = "/data/local/tmp/soundbooster-probe-" + uuid.uuid4().hex
    executable = directory / ("effect-test" if args.effect_harness else "probe")
    effect = directory / "libadaptive_soundbooster_test.so"
    relocations = []
    vendor_link = vendor_runtime_import(
        toolchain, compiler, args.linked_vendor_runtime, directory / "vendor-runtime-import.so",
        remote + "/" + engine.name
    ) if args.linked_vendor_runtime else []
    if args.effect_harness:
        relocations = engine_relocations(args.abi, run(
            str(toolchain / "bin/llvm-readelf"), "--relocations", "--wide", str(engine)).stdout)
        relocation_header = directory / "engine-relocations.h"
        relocation_header.write_text(
            "#define SB_ENGINE_RELOCATIONS {" +
            ",".join(f'{{0x{offset:x}, "{symbol}"}}' for offset, symbol in relocations) +
            "}\n", encoding="ascii")
        run(str(toolchain / "bin" / (compiler + "-clang++")), "-std=c++17", "-O2",
            "-Wall", "-Wextra", "-Werror", "-fstack-protector-strong", "-fPIC", "-shared",
            "-fvisibility=hidden", "-Wl,-z,relro,-z,now",
            *(["-static-libstdc++", "-Wl,--strip-all,--gc-sections",
               "-Wl,--version-script=" + str(ROOT / "src/soundbooster_static.map")]
              if args.static_runtime else []),
            '-DSB_ENGINE_PATH="' + remote + "/" + engine.name + '"',
            '-DSB_ENGINE_HASH="' + engine_hash + '"',
            '-DSB_PARAMETER_PATH="' + remote + "/" + parameters.name + '"',
            '-DSB_PARAMETER_HASH="' + hashlib.sha256(payload).hexdigest() + '"',
            str(ROOT / "src/soundbooster_effect.cpp"), "-o", str(effect), "-ldl", "-lm", "-llog",
            *vendor_link)
    run(str(toolchain / "bin" / (compiler + "-clang++")), "-std=c++17", "-O2",
        "-Wall", "-Wextra", "-Werror", "-fstack-protector-strong", "-fPIE", "-pie",
        "-Wl,-z,relro,-z,now", str(ROOT / "tools" /
                                 ("test_soundbooster_effect.cpp" if args.effect_harness else
                                  "probe_soundbooster.cpp")),
        *(["-DSB_STATIC_RUNTIME", "-static-libstdc++", "-fvisibility=hidden", "-Wl,--exclude-libs,ALL"]
          if args.static_runtime else []),
        *(["-DSB_AOSP_ABI", "-I" + str(args.aosp_include)] if args.aosp_include else []),
        *(["-include", str(relocation_header)] if args.effect_harness else []),
        "-o", str(executable), "-ldl", "-lm")
    static_linkage = inspect_static_linkage(
        toolchain, args.abi, effect, executable, bool(args.linked_vendor_runtime),
        remote + "/" + engine.name) if args.static_runtime else None
    namespace_test = directory / "namespace-test"
    if args.vendor_search_path:
        run(str(toolchain / "bin" / (compiler + "-clang++")), "-std=c++17", "-O2",
            "-Wall", "-Wextra", "-Werror", "-fPIE", "-pie", "-nostdlib++",
            "-fno-exceptions", "-fno-rtti", "-Wl,-z,relro,-z,now",
            str(ROOT / "tools/test_soundbooster_namespace.cpp"), "-o", str(namespace_test), "-ldl")
    if not args.run_device:
        print(f"Built {executable}; no device accessed. Use --run-device --serial for an in-memory test.")
        return
    runtime = toolchain / "sysroot/usr/lib" / triple / "libc++_shared.so"
    files = ((executable, engine, parameters) +
             (() if args.static_runtime else (runtime,)) +
             ((effect,) if args.effect_harness else ()) +
             ((namespace_test,) if args.vendor_search_path else ()))

    def adb(*arguments):
        return run(args.adb, "-s", args.serial, *arguments)

    uses_vendor_runtime = args.vendor_runtime or bool(args.linked_vendor_runtime)
    if uses_vendor_runtime:
        validate_vendor_runtime_identity(adb("shell", "sha256sum " + VENDOR_RUNTIME_PATH).stdout)
    reports = []
    namespace_report = None
    adb("shell", "mkdir " + shlex.quote(remote))
    try:
        for file in files:
            adb("push", str(file), remote + "/" + file.name)
            expected_hash = hashlib.sha256(file.read_bytes()).hexdigest()
            measured_hash = adb("shell", "sha256sum " + shlex.quote(remote + "/" + file.name)).stdout.split()[0]
            if measured_hash != expected_hash:
                raise ValueError(f"Device transfer hash mismatch: {file.name}")
        adb("shell", "chmod 700 " + shlex.quote(remote + "/" + executable.name))
        if args.vendor_search_path:
            adb("shell", "chmod 700 " + shlex.quote(remote + "/" + namespace_test.name))
            result = adb("shell", "LD_PRELOAD= LD_LIBRARY_PATH= " +
                         shlex.quote(remote + "/" + namespace_test.name) + " " +
                         shlex.quote(remote + "/" + effect.name))
            namespace_report = json.loads(result.stdout)
            if namespace_report != {"isolated_vendor_namespace": True, "runtime_preloaded": False,
                                    "processed_frames": 1024, "bypassed_frames": 0, "hidl_mask": 30}:
                raise ValueError("Invalid isolated namespace processing evidence")
        for mode in ((None,) if args.effect_harness else (1, 2)):
            command = (f"ulimit -c 0; LD_PRELOAD={VENDOR_RUNTIME_PATH if args.vendor_runtime else ''} "
                       f"LD_LIBRARY_PATH={'/vendor/lib' if args.vendor_search_path else '' if args.static_runtime else shlex.quote(remote)} "
                       f"{shlex.quote(remote + '/' + executable.name)} " +
                       (shlex.quote(remote + "/" + effect.name) + " " if args.effect_harness else "") +
                       f"{shlex.quote(remote + '/' + engine.name)} "
                       f"{shlex.quote(remote + '/' + parameters.name)}" +
                       ("" if args.effect_harness else f" {mode}"))
            result = adb("shell", command)
            parsed = json.loads(result.stdout)
            if args.linked_vendor_runtime:
                args.output.with_suffix(".raw.json").write_text(json.dumps(parsed, indent=2) + "\n")
            if args.effect_harness:
                validate_bindings(parsed.get("engine_cpp_bindings"), relocations, args.static_runtime,
                                  uses_vendor_runtime)
            reports.append(validate_effect_report(parsed, bool(args.aosp_include),
                                                  32 if args.abi == "armeabi-v7a" else 64,
                                                  args.static_runtime, uses_vendor_runtime)
                           if args.effect_harness else
                           validate_report(parsed, mode))
    finally:
        paths = " ".join(shlex.quote(remote + "/" + file.name) for file in files)
        adb("shell", "rm -f " + paths + " && rmdir " + shlex.quote(remote))
    report = {
        "format": 1, "abi": args.abi, "engine_sha256": engine_hash,
        "parameter_sha256": soundbooster.PARAMETER_SHA256,
        "scope": "Native shell-process synthetic PCM processing, no audio output or effect installation",
        "runtime_integration_verified": False, "stock_runtime_equivalence_verified": False,
        "native_pcm_processing_verified": True,
        "device_file_transfer_hashes_verified": True,
        "temporary_device_files_removed": True,
        "effect_adapter_harness": args.effect_harness,
        "embedded_cpp_runtime": args.static_runtime,
        "shared_cpp_runtime_transferred": not args.static_runtime,
        "temporary_library_search_path_used": not args.static_runtime or args.vendor_search_path,
        "vendor_library_search_path_used": args.vendor_search_path,
        "vendor_runtime_preloaded": args.vendor_runtime,
        "vendor_runtime_linked": bool(args.linked_vendor_runtime),
        "isolated_namespace_test": namespace_report,
        "vendor_runtime_sha256": VENDOR_RUNTIME_SHA256 if uses_vendor_runtime else None,
        "static_linkage": static_linkage,
        "engine_cpp_relocation_slots_checked": len(relocations),
        "aosp_effect_header_hashes": AOSP_EFFECT_HEADERS if args.aosp_include else None,
        "assumptions": (["Explicit Legacy mode, 48000 Hz, PCM16 or finite normalized float stereo, WRITE/ACCUMULATE output",
                         "PCM16 accumulation saturates; float accumulation preserves finite headroom",
                         "Engine volume indication uses min(left,right); framework retains volume ownership",
                         "Unknown/non-speaker/mixed routes bypass, disabled processing returns ENODATA",
                         "Shared test ABI; original AOSP header layout checks only when explicitly supplied",
                         "Temporary build paths embedded; NOT a deployable vendor effect",
                         "No audio service, routing callbacks or real-time integration tested"]
                        if args.effect_harness else
                        ["Explicit Music/Legacy mode, 48000 Hz, PCM16 stereo, 256-frame calls",
                        "Reviewed parsed tables passed directly to SetPar; stock file loader bypassed",
                        "Zero THC aggregate, volume argument 1.0, no orientation/motion calls",
                        "Independent fresh engine per tone; measure last half of 49152 input frames"]),
        "adapter_tests" if args.effect_harness else "modes": reports,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{'Effect adapter harness' if args.effect_harness else 'Native probe (both modes)'} passed; "
          f"temporary device files removed. Report: {args.output}")


if __name__ == "__main__":
    main()

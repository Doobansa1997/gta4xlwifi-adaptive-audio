#!/usr/bin/env python3
"""Trace reviewed SoundBooster control routines offline, with stubbed DSP dependencies."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

import soundbooster
from verify_soundbooster import ENGINE_SHA256

BASE = 0x100000
OBJECT = 0x300000
TABLES = 0x310000
DATA = 0x320000
STOP = BASE + 0x40000


def packed(values):
    return struct.pack(f"<{len(values)}i", *values)


class ControlTrace:
    def __init__(self, engine):
        if hashlib.sha256(engine).hexdigest() != ENGINE_SHA256:
            raise ValueError("Unreviewed SoundBooster engine; control trace refused")
        from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, UC_PROT_EXEC, UC_PROT_READ, UC_PROT_WRITE
        from unicorn import arm_const

        self.reg = arm_const
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.cpu.mem_map(BASE, 0x33000, UC_PROT_READ | UC_PROT_EXEC)
        self.cpu.mem_write(BASE, engine[:0x3200b])
        self.cpu.mem_map(0x200000, 0x20000, UC_PROT_READ | UC_PROT_WRITE)
        self.cpu.mem_map(OBJECT, 0x30000, UC_PROT_READ | UC_PROT_WRITE)
        self.cpu.mem_map(TABLES + 0x30000, 0x1000, UC_PROT_READ | UC_PROT_EXEC)
        self.cpu.reg_write(arm_const.UC_ARM_REG_C1_C0_2, 0xF00000)
        self.cpu.reg_write(arm_const.UC_ARM_REG_FPEXC, 1 << 30)
        self.allowed = []
        self.callbacks = {}
        self.cpu.hook_add(UC_HOOK_CODE, self.instruction)

    def read(self, address, count):
        return list(struct.unpack(f"<{count}i", self.cpu.mem_read(address, count * 4)))

    def write(self, address, values):
        self.cpu.mem_write(address, packed(values))

    def register(self, index):
        return self.cpu.reg_read(getattr(self.reg, f"UC_ARM_REG_R{index}"))

    def arguments(self, count):
        values = [self.register(index) for index in range(1, min(3, count) + 1)]
        if count > 3:
            values.extend(self.read(self.cpu.reg_read(self.reg.UC_ARM_REG_SP), count - 3))
        return [value - (1 << 32) if value >= (1 << 31) else value for value in values]

    def returned(self, value=0):
        self.cpu.reg_write(self.reg.UC_ARM_REG_R0, value)
        self.cpu.reg_write(self.reg.UC_ARM_REG_PC, self.cpu.reg_read(self.reg.UC_ARM_REG_LR))

    def instruction(self, cpu, address, size, data):
        if address in self.callbacks:
            self.callbacks[address]()
        elif address == BASE + 0x9588:
            self.returned()
        elif address == BASE + 0x9594:
            destination, source, length = (self.register(index) for index in range(3))
            if length > 1024:
                raise ValueError("Unexpected memcpy length in control trace")
            cpu.mem_write(destination, bytes(cpu.mem_read(source, length)))
            self.returned(destination)
        elif address == BASE + 0x95E8:
            destination, value, length = (self.register(index) for index in range(3))
            if length > 1024:
                raise ValueError("Unexpected memset length in control trace")
            cpu.mem_write(destination, bytes([value & 255]) * length)
            self.returned(destination)
        elif not any(start <= address < end for start, end in self.allowed):
            raise ValueError(f"Unexpected control-trace instruction {address:#x}")

    def run(self, entry, values, object_address=OBJECT):
        sp = 0x218000
        self.cpu.reg_write(self.reg.UC_ARM_REG_SP, sp)
        self.cpu.reg_write(self.reg.UC_ARM_REG_LR, STOP)
        self.cpu.reg_write(self.reg.UC_ARM_REG_R0, object_address)
        for index, value in enumerate(values[:3], 1):
            self.cpu.reg_write(getattr(self.reg, f"UC_ARM_REG_R{index}"), value & 0xFFFFFFFF)
        if len(values) > 3:
            self.write(sp, values[3:])
        self.cpu.emu_start(BASE + entry, STOP, timeout=1000000, count=50000)
        if self.cpu.reg_read(self.reg.UC_ARM_REG_PC) != STOP:
            raise ValueError("Control trace exceeded its instruction/time budget")

    def fake_object(self, address, slots):
        table = TABLES + (address - OBJECT) // 4
        self.write(address, [table])
        for slot, function in slots.items():
            self.write(table + slot, [function])


def amf_values(rows, prefix):
    return [value for band in "ABCDEFGH" for value in rows[prefix + band]] + rows[prefix + "M"] + rows[prefix + "U"]


def trace_interface(engine, rows):
    trace = ControlTrace(engine)
    trace.allowed = [(BASE + 0xC1C8, BASE + 0xC630)]
    calls = []
    for channel, address in enumerate((OBJECT + 0x4000, OBJECT + 0x5000)):
        target = TABLES + 0x30000 + channel * 4
        trace.fake_object(address, {8: target})

        def capture(channel=channel):
            calls.append({"object_index": channel, "values": trace.arguments(192)})
            trace.returned()

        trace.callbacks[target] = capture
    trace.write(OBJECT + 0x10, [OBJECT + 0x4000, OBJECT + 0x5000])
    values = rows["S"] + [0] * 30
    for index, group in enumerate("ABCD"):
        pointer = DATA + index * 0x1000
        trace.write(pointer, [value for level in "ABCDEFGHIJKLMNOP" for value in rows[group + "M" + level]])
        values.extend(rows[group + "H"] + rows[group + "F"] + rows[group + "L"] + [pointer] +
                      amf_values(rows, group + "A") + amf_values(rows, group + "C"))
    trace.run(0xC1C8, values)
    return calls


def dispatch_base(engine, interface_call, mode):
    if mode not in (1, 2):
        raise ValueError("Only reviewed Music/Legacy mode traces are supported")
    dispatch = ControlTrace(engine)
    dispatch.allowed = [(BASE + 0xF118, BASE + 0xF328)]
    target = TABLES + 0x30000
    dispatch.write(OBJECT + 0x10, [mode])
    dispatch.write(OBJECT + (0x8 if mode == 1 else 0xC), [OBJECT + 0x4000])
    dispatch.fake_object(OBJECT + 0x4000, {8: target})
    outgoing = []
    count = 84 if mode == 1 else 110

    def capture_parameters():
        outgoing.extend(dispatch.arguments(count))
        dispatch.returned()

    dispatch.callbacks[target] = capture_parameters
    dispatch.run(0xF118, interface_call["values"])
    if len(outgoing) != count:
        raise ValueError(f"Mode {mode} did not receive the expected parameter block")
    return outgoing


def trace_music(engine, rows, interface_call):
    outgoing = dispatch_base(engine, interface_call, 1)
    group_index = (outgoing[49] - DATA) // 0x1000
    if group_index not in range(4):
        raise ValueError("Unexpected Music M-table pointer")
    group = "ABCD"[group_index]
    if outgoing[46:49] != rows[group + "H"] or outgoing[50:83] != amf_values(rows, group + "A"):
        raise ValueError("Music source H/AMF tables do not match decoded rows")

    trace = ControlTrace(engine)
    trace.allowed = [(BASE + 0x11F3C, BASE + 0x12370),
                     (BASE + 0x111F8, BASE + 0x112FC),
                     (BASE + 0x11400, BASE + 0x1143C),
                     (BASE + 0x11B10, BASE + 0x11E7C)]
    trace.write(DATA + group_index * 0x1000,
                [value for level in "ABCDEFGHIJKLMNOP" for value in rows[group + "M" + level]])
    fft = OBJECT + 0x8000
    trace.write(OBJECT + 0x9F0, [fft])
    events = {}
    trace.fake_object(fft, {slot: TABLES + 0x30000 + slot for slot in (0, 8, 24)})
    for slot, count, label in ((0, 3, "fft_init"), (8, 4, "fft_hpf"), (24, 1, "fft_pre_drc_mode")):
        def capture(slot=slot, count=count, label=label):
            events[label] = trace.arguments(count)
            trace.returned()
        trace.callbacks[TABLES + 0x30000 + slot] = capture

    def forward(entry, label, count):
        events[label] = trace.arguments(count)
        trace.cpu.reg_write(trace.reg.UC_ARM_REG_PC, BASE + entry)

    trace.callbacks[BASE + 0x9A08] = lambda: forward(0x111F8, "common", 5)
    trace.callbacks[BASE + 0x9A14] = lambda: forward(0x11400, "hpf", 3)
    trace.callbacks[BASE + 0x9A2C] = lambda: forward(0x11B10, "volume_pointer", 1)

    def capture_amf():
        pointer, count = trace.arguments(2)
        events["amf"] = {"filter_count": count, "values": trace.read(pointer, 33)}
        trace.returned()

    def capture_drc():
        arguments = trace.arguments(15)
        events["drc"] = {
            "enable_by_level": trace.read(arguments[0], 16),
            "four_12_value_blocks_by_level": [
                [trace.read(pointer + level * 48, 12) for level in range(16)]
                for pointer in arguments[1:5]
            ],
            "five_control_tables": [trace.read(pointer, 16) for pointer in arguments[5:10]],
            "mode_arguments": arguments[10:13],
            "two_additional_tables": [trace.read(pointer, 16) for pointer in arguments[13:15]],
        }
        trace.returned()

    trace.callbacks[BASE + 0x99FC] = capture_amf
    trace.callbacks[BASE + 0x9A20] = capture_drc
    trace.run(0x11F3C, outgoing)
    events.pop("volume_pointer")
    events["volume_table_after_clamp"] = trace.read(OBJECT + 0x17F8, 16)
    events["group"] = group
    events["object_index"] = interface_call["object_index"]
    events["amf"]["bank"] = next(
        prefix for prefix in (group + "A", group + "C")
        if amf_values(rows, prefix) == events["amf"]["values"])
    events["amf"]["bank_is_ambiguous"] = amf_values(rows, group + "A") == amf_values(rows, group + "C")
    return events


def trace_legacy(engine, rows, interface_call):
    outgoing = dispatch_base(engine, interface_call, 2)
    group_index = (interface_call["values"][124] - DATA) // 0x1000
    if group_index not in range(4):
        raise ValueError("Unexpected Legacy source group")
    group = "ABCD"[group_index]
    if outgoing[16:19] != rows[group + "H"] or outgoing[19:77] != rows[group + "L"]:
        raise ValueError("Legacy source H/L tables do not match decoded rows")
    trace = ControlTrace(engine)
    trace.allowed = [(BASE + 0x10298, BASE + 0x103C0),
                     (BASE + 0xF990, BASE + 0xFA94),
                     (BASE + 0xFB98, BASE + 0xFBD4),
                     (BASE + 0xFBD4, BASE + 0x100F8),
                     (BASE + 0x100F8, BASE + 0x101E0)]
    fft = OBJECT + 0x8000
    trace.write(OBJECT + 0x9F8, [fft])
    events = {"group": group, "object_index": interface_call["object_index"]}
    trace.fake_object(fft, {slot: TABLES + 0x30000 + slot for slot in (0, 8, 12, 16, 24, 28)})
    for slot, count, label in ((0, 3, "fft_init"), (8, 4, "fft_hpf"), (24, 1, "fft_pre_drc_mode"),
                               (16, 8, "fft_obdrc"), (28, 2, "fft_configure_obdrc")):
        def capture(count=count, label=label):
            events[label] = trace.arguments(count)
            trace.returned()
        trace.callbacks[TABLES + 0x30000 + slot] = capture

    def forward(entry, label, count):
        events[label] = trace.arguments(count)
        trace.cpu.reg_write(trace.reg.UC_ARM_REG_PC, BASE + entry)

    trace.callbacks[BASE + 0x98AC] = lambda: forward(0xF990, "common", 5)
    trace.callbacks[BASE + 0x98B8] = lambda: forward(0xFB98, "hpf", 3)
    trace.callbacks[BASE + 0x98D0] = lambda: forward(0x100F8, "volume_arguments", 3)
    def capture_pre_drc():
        events["pre_drc_arguments"] = trace.arguments(3)
        trace.returned()

    trace.callbacks[BASE + 0x9888] = capture_pre_drc

    def capture_fft_mbdrc():
        arguments = trace.arguments(8)
        events["fft_mbdrc"] = {
            "enable": arguments[0],
            "four_12_value_blocks": [trace.read(pointer, 12) for pointer in arguments[1:5]],
            "remaining_control_arguments": arguments[5:],
        }
        trace.returned()

    trace.callbacks[TABLES + 0x30000 + 12] = capture_fft_mbdrc

    def capture_amf():
        pointer, count = trace.arguments(2)
        events["amf"] = {"filter_count": count, "values": trace.read(pointer, 33)}
        trace.returned()

    def capture_drc():
        arguments = trace.arguments(15)
        events["drc"] = {
            "enable": arguments[0],
            "four_12_value_blocks": [trace.read(pointer, 12) for pointer in arguments[1:5]],
            "remaining_control_arguments": arguments[5:],
        }
        trace.cpu.reg_write(trace.reg.UC_ARM_REG_PC, BASE + 0xFBD4)

    trace.callbacks[BASE + 0x98A0] = capture_amf
    trace.callbacks[BASE + 0x98C4] = capture_drc
    trace.run(0x10298, outgoing)
    events["volume_fields_after_clamp"] = trace.read(OBJECT + 0xAE0, 3)
    if events["amf"]["values"] != amf_values(rows, group + "C"):
        raise ValueError("Legacy did not receive the second AMF parameter bank")
    events["amf"]["bank"] = group + "C"
    return events


def trace_controls(engine, payload):
    soundbooster.analyze(payload)
    rows = soundbooster.parse_rows(payload.decode("ascii"))
    calls = trace_interface(engine, rows)
    if [call["object_index"] for call in calls] != [0, 1]:
        raise ValueError("Unexpected interface-to-base object dispatch")
    legacy = [trace_legacy(engine, rows, call) for call in calls]
    for call in legacy:
        call["mbdrc_backends"] = trace_mbdrc(engine, call["fft_mbdrc"])
    return {
        "format": 1, "engine_sha256": ENGINE_SHA256,
        "parameter_sha256": soundbooster.PARAMETER_SHA256,
        "scope": "Observed control calls with stubbed dependent DSP objects, not audio processing",
        "assumptions": ["Engine modes 1 (Music) and 2 (Legacy) supplied explicitly",
                        "Wrapper defaults to mode 2, but SB_init can override it with supplied init data",
                        "THC table zeroed, matching parser memset with no T record in reviewed input",
                        "Two preallocated fake base objects, without constructor or Android framework",
                        "FFT format field zeroed; captured Init format is synthetic, not a runtime observation",
                        "Gain-scaler objects null; stored volume controls do not establish effective gain",
                        "Backend conversion uses an explicit synthetic 1024-frame/48000-Hz FFT context",
                        "No runtime orientation, motion or playback control sequence"],
        "runtime_bank_selection_verified": False, "drc_audio_processing_verified": False,
        "hpf_coefficient_response_verified": True, "hpf_audio_processing_verified": False,
        "effective_volume_gain_verified": False,
        "legacy_calls": legacy,
        "music_calls": [trace_music(engine, rows, call) for call in calls],
        "hpf_coefficient_checks": [trace_highpass(engine, cutoff) for cutoff in
                                   sorted({rows[group + "H"][1] for group in "ABCD"})],
    }


def trace_mbdrc(engine, controls):
    if len(controls["four_12_value_blocks"]) != 4 or controls["remaining_control_arguments"] != [12, 2, -1]:
        raise ValueError("Only the reviewed 12-control mode-2 Legacy split is supported")
    trace = ControlTrace(engine)
    trace.allowed = [(BASE + 0x1CE28, BASE + 0x1D1B0)]
    pointers = [DATA + index * 64 for index in range(4)]
    for pointer, block in zip(pointers, controls["four_12_value_blocks"]):
        if len(block) != 12:
            raise ValueError("Expected 12 multiband controls per block")
        trace.write(pointer, block)
    events = []
    for address, name in ((0x9F54, "FILX"), (0x9F60, "EMQF")):
        def capture(name=name):
            args = trace.arguments(7)
            count = args[5]
            if count not in (3, 11):
                raise ValueError("Unexpected compression backend band count")
            blocks = [trace.read(pointer, count) for pointer in args[1:5]]
            events.append({"backend": name, "enable": args[0], "band_count": count,
                           "four_control_blocks": blocks, "remaining_control": args[6],
                           "parameter_checks": trace_backend_parameters(engine, name, blocks)})
            trace.returned()
        trace.callbacks[BASE + address] = capture
    trace.run(0x1CE28, [controls["enable"], *pointers, *controls["remaining_control_arguments"]])
    return events


def trace_backend_parameters(engine, backend, blocks, frame_size=1024, sample_rate=48000):
    if backend not in ("FILX", "EMQF") or frame_size not in (512, 1024) or sample_rate != 48000:
        raise ValueError("Only reviewed backend parameters and synthetic FFT formats are supported")
    count = 11 if backend == "FILX" else 3
    if len(blocks) != 4 or any(len(block) != count for block in blocks):
        raise ValueError("Unexpected compression backend control shape")
    if any(not -30 <= value <= 30 for value in blocks[0]) or any(
            not -30 <= value <= 0 for value in blocks[1]) or any(
            not 0 <= value <= 2000 for block in blocks[2:] for value in block):
        raise ValueError("Backend conversion requires reviewed gain and time ranges")
    trace = ControlTrace(engine)
    entry, end = (0x20920, 0x20AE8) if backend == "FILX" else (0x20738, 0x208FC)
    trace.allowed = [(BASE + entry, BASE + end),
                     (BASE + 0x201D4, BASE + 0x205F4),
                     (BASE + 0x2061C, BASE + 0x20738)]
    trace.write(OBJECT + 0x4858, [frame_size])
    trace.write(OBJECT + 0x4860, [sample_rate])
    pointers = [DATA + index * 64 for index in range(4)]
    for pointer, block in zip(pointers, blocks):
        trace.write(pointer, block)

    def imported_math(function, count):
        args = [struct.unpack("<f", struct.pack("<I", trace.register(index)))[0]
                for index in range(count)]
        result = struct.unpack("<I", struct.pack("<f", function(*args)))[0]
        trace.returned(result)

    trace.callbacks[BASE + 0x9C6C] = lambda: imported_math(math.pow, 2)
    trace.callbacks[BASE + 0x9558] = lambda: imported_math(math.exp, 1)
    curve_calls = []

    def capture_curve():
        args = trace.arguments(7)
        curve_calls.append({"four_control_blocks": [trace.read(pointer, count) for pointer in args[:4]],
                            "band_count": args[4], "remaining_control": args[5],
                            "output_pointer": args[6]})
        trace.cpu.reg_write(trace.reg.UC_ARM_REG_PC, BASE + 0x201D4)

    trace.callbacks[BASE + 0xA098] = capture_curve
    trace.run(entry, [1, *pointers, count, 2])
    if len(curve_calls) != 1 or curve_calls[0]["four_control_blocks"] != blocks:
        raise ValueError("Unexpected gain-curve callback")
    curves = []
    for index in range(count):
        raw = bytes(trace.cpu.mem_read(curve_calls[0]["output_pointer"] + index * 44, 44))
        values = list(struct.unpack("<10f", raw[:40]))
        point_count = struct.unpack("<i", raw[40:])[0]
        if not all(math.isfinite(value) for value in values) or point_count != 5:
            raise ValueError("Unexpected mode-2 gain-curve shape")
        curves.append({"first_five_values": values[:5], "second_five_values": values[5:],
                       "point_count": point_count})
    for curve, gain_control, threshold_control in zip(curves, blocks[0], blocks[1]):
        if curve != soundbooster.compression_curve_mode2(gain_control, threshold_control):
            raise ValueError("Original mode-2 compression curve does not match model")
    del curve_calls[0]["output_pointer"]
    offsets = (0x72CC, 0x7324, 0x7350, 0x7366) if backend == "FILX" else (0xA830, 0xA848, 0xA854, 0xA85A)
    gain = trace.read(OBJECT + offsets[0], count)
    threshold = trace.read(OBJECT + offsets[1], count)
    attack, release = [list(struct.unpack(f"<{count}h", trace.cpu.mem_read(OBJECT + offset, count * 2)))
                       for offset in offsets[2:]]
    expected_gain = [int(10 ** (value / 20) * 32768) for value in blocks[0]]
    threshold_scale = 32768 if backend == "FILX" else 8388608
    expected_threshold = [int(10 ** (value / 20) * threshold_scale) for value in blocks[1]]
    expected_times = [[int(math.exp(-2.2 * (frame_size // 2) / sample_rate / (value * 0.001)) * 32768)
                       if value else 0
                       for value in block] for block in blocks[2:]]
    errors = [max(abs(actual - expected) for actual, expected in zip(values, model))
              for values, model in zip((gain, threshold, attack, release),
                                       (expected_gain, expected_threshold, *expected_times))]
    limits = [1, 2 if backend == "EMQF" else 1, 1, 1]
    if any(error > limit for error, limit in zip(errors, limits)):
        raise ValueError(f"{backend} parameter conversion mismatch: {errors}")
    return {"synthetic_frame_size": frame_size, "synthetic_sample_rate_hz": sample_rate,
            "gain_q15": gain, "threshold_q15" if backend == "FILX" else "threshold_q23": threshold,
            "attack_q15": attack, "release_q15": release,
            "max_integer_errors_gain_threshold_attack_release": errors,
            "integer_error_limits": limits, "gain_curve_call": curve_calls[0],
            "mode2_gain_curve_records": curves,
            "mode2_curve_model_exact_for_supplied_controls": True,
            "scope": "Conditional parameter and original curve generation; audio processing not executed"}


def trace_highpass(engine, cutoff):
    if cutoff not in (75, 100):
        raise ValueError("Only reviewed 75/100 Hz high-pass traces are supported")
    trace = ControlTrace(engine)
    trace.allowed = [(BASE + 0x1821C, BASE + 0x184B4), (BASE + 0x184F0, BASE + 0x18704)]

    def double_import(function, two_arguments=False):
        first = struct.unpack("<d", struct.pack("<II", trace.register(0), trace.register(1)))[0]
        if two_arguments:
            second = struct.unpack("<d", struct.pack("<II", trace.register(2), trace.register(3)))[0]
            result = function(first, second)
        else:
            result = function(first)
        lower, upper = struct.unpack("<II", struct.pack("<d", result))
        trace.cpu.reg_write(trace.reg.UC_ARM_REG_R1, upper)
        trace.returned(lower)

    trace.callbacks[BASE + 0x9C78] = lambda: double_import(math.cos)
    trace.callbacks[BASE + 0x9C84] = lambda: double_import(math.sin)
    trace.callbacks[BASE + 0x9C9C] = lambda: double_import(math.pow, True)
    trace.run(0x1821C, [DATA, cutoff, soundbooster.SAMPLE_RATE])
    raw = trace.read(DATA, 10)
    sections = []
    for offset in (0, 5):
        b0, b1, b2, minus_a1, minus_a2 = raw[offset:offset + 5]
        sections.append([value / (1 << 30) for value in (b0, b1, b2, -minus_a1, -minus_a2)])
    points = []
    for frequency in sorted({*soundbooster.FREQUENCIES, cutoff, cutoff / 2, cutoff * 2}):
        actual = sum(soundbooster.response_db(section, frequency) for section in sections)
        expected = soundbooster.highpass_response_db(cutoff, frequency)
        points.append({"frequency_hz": frequency, "original_coefficient_response_db": actual,
                       "butterworth_order4_response_db": expected, "error_db": abs(actual - expected)})
    maximum_error = max(point["error_db"] for point in points)
    if maximum_error > 0.02:
        raise ValueError(f"Original HPF does not match the order-4 model: {maximum_error} dB")
    return {"cutoff_hz": cutoff, "raw_q30_coefficients": raw,
            "sections_b0_b1_b2_a1_a2": sections, "sampled_response": points,
            "max_sampled_response_error_db": maximum_error, "error_limit_db": 0.02,
            "scope": "Coefficient routine and conditional HPF magnitude only, not DSP playback"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--parameters", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = trace_controls(args.engine.read_bytes(), args.parameters.read_bytes())
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for mode in ("legacy", "music"):
        for call in report[mode + "_calls"]:
            print(f"{mode} object {call['object_index']}: group {call['group']}, "
                  f"HPF {call['hpf']}, volume arguments "
                  f"{call.get('volume_arguments', call.get('volume_table_after_clamp'))}")
            for backend in call.get("mbdrc_backends", []):
                print(f"  {backend['backend']}: {backend['band_count']} internal slots, "
                      "original mode-2 curves match model")
    for check in report["hpf_coefficient_checks"]:
        print(f"HPF {check['cutoff_hz']} Hz: order-4 sampled-response error "
              f"{check['max_sampled_response_error_db']:.6f} dB")
    print(f"Control trace written to {args.output}; dependent DSP processing was stubbed")


if __name__ == "__main__":
    main()

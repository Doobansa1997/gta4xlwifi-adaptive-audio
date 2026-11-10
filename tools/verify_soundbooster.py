#!/usr/bin/env python3
"""Optional bounded ARM emulation to check the static AMF model against a local engine."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

import soundbooster

ENGINE_SHA256 = "5dd9b49a3718a5529ee160e4a4bdd5552c5cb494a329e022a7d3166bff6d8bac"


def emulate_filter(engine, frequency, bandwidth, gain):
    from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, UC_PROT_READ, UC_PROT_EXEC, UC_PROT_WRITE
    from unicorn.arm_const import (UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR,
                                  UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                                  UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP)

    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    base, stack, output, stop = 0x100000, 0x200000, 0x300000, 0x140000
    cpu.mem_map(base, 0x33000, UC_PROT_READ | UC_PROT_EXEC)
    cpu.mem_write(base, engine[:0x3200b])
    cpu.mem_map(stack, 0x10000, UC_PROT_READ | UC_PROT_WRITE)
    cpu.mem_map(output, 0x1000, UC_PROT_READ | UC_PROT_WRITE)
    cpu.reg_write(UC_ARM_REG_C1_C0_2, 0xF00000)
    cpu.reg_write(UC_ARM_REG_FPEXC, 1 << 30)
    sp = stack + 0xF000
    cpu.reg_write(UC_ARM_REG_SP, sp)
    cpu.reg_write(UC_ARM_REG_LR, stop)
    cpu.reg_write(UC_ARM_REG_R0, 0)
    cpu.reg_write(UC_ARM_REG_R1, output)
    cpu.reg_write(UC_ARM_REG_R2, frequency)
    cpu.reg_write(UC_ARM_REG_R3, bandwidth)
    cpu.mem_write(sp, struct.pack("<iii", gain, soundbooster.SAMPLE_RATE, 1))

    def as_float(bits):
        return struct.unpack("<f", struct.pack("<I", bits))[0]

    def instruction(uc, address, size, data):
        offset = address - base
        if offset in (0x9B7C, 0x9C6C):
            first = as_float(uc.reg_read(UC_ARM_REG_R0))
            result = (math.tan(first) if offset == 0x9B7C else
                      math.pow(first, as_float(uc.reg_read(UC_ARM_REG_R1))))
            uc.reg_write(UC_ARM_REG_R0, struct.unpack("<I", struct.pack("<f", result))[0])
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        elif not 0x188A0 <= offset < 0x18C44:
            raise ValueError(f"Unexpected execution address {address:#x}; emulation refused")

    cpu.hook_add(UC_HOOK_CODE, instruction)
    cpu.emu_start(base + 0x188A0, stop, timeout=100000, count=1000)
    if cpu.reg_read(UC_ARM_REG_PC) != stop:
        raise ValueError("Emulation did not return within the instruction/time budget")
    b0, b1, b2, minus_a1, minus_a2 = struct.unpack("<5i", cpu.mem_read(output, 20))
    return tuple(value / (1 << 30) for value in (b0, b1, b2, -minus_a1, -minus_a2))


def verify(engine, report):
    if hashlib.sha256(engine).hexdigest() != ENGINE_SHA256:
        raise ValueError("Unreviewed SoundBooster engine; address-based emulation refused")
    checked = 0
    coefficient_error = response_error = bank_response_error = 0.0
    for bank in report["banks"].values():
        if not bank["enabled"]:
            continue
        actual_filters = []
        for item in bank["filters"]:
            actual = emulate_filter(engine, item["frequency_hz"], item["bandwidth_hz"], item["gain_db"])
            actual_filters.append(actual)
            expected = item["coefficients_b0_b1_b2_a1_a2"]
            coefficient_error = max(coefficient_error, max(abs(a - b) for a, b in zip(actual, expected)))
            for frequency in (*soundbooster.FREQUENCIES, item["frequency_hz"]):
                response_error = max(response_error, abs(
                    soundbooster.response_db(actual, frequency) -
                    soundbooster.response_db(expected, frequency)))
            checked += 1
        for point in bank["static_amf_only_response_db"]:
            actual_response = sum(soundbooster.response_db(coefficients, point["frequency_hz"])
                                  for coefficients in actual_filters)
            bank_response_error = max(bank_response_error, abs(actual_response - point["gain_db"]))
    if checked != 32 or coefficient_error > 0.000002 or max(response_error, bank_response_error) > 0.02:
        raise ValueError(f"AMF verification failed: {checked=}, {coefficient_error=}, "
                         f"{response_error=}, {bank_response_error=}")
    return {
        "engine_sha256": ENGINE_SHA256, "enabled_parameter_filter_cases_checked": checked,
        "max_coefficient_absolute_error": coefficient_error,
        "max_single_filter_response_error_db": response_error,
        "max_static_bank_response_error_db": bank_response_error,
        "coefficient_error_limit": 0.000002, "response_error_limit_db": 0.02,
        "scope": "Type-1 coefficient generation only; no engine initialization, syscalls or device access",
        "math_imports": "Host tan/pow rounded to float32; not Android libm bit-exact",
        "runtime_bank_selection_verified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--parameters", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = soundbooster.analyze(args.parameters.read_bytes())
    result = verify(args.engine.read_bytes(), report)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Inspect reviewed local SoundBooster AMF banks; never generate a device preset."""

import argparse
import cmath
import csv
import hashlib
import json
import math
from pathlib import Path

PARAMETER_SHA256 = "668c3a89b3974aef719d7c9ac9cd8b1d18351501d0107bb842962c5f7b97e098"
SAMPLE_RATE = 48000
FREQUENCIES = (47, 141, 234, 328, 469, 656, 844, 1031, 1313, 1688,
               2250, 3000, 3750, 4688, 5813, 7125, 9000, 11250, 13875, 19688)


def parse_rows(text):
    rows = {}
    for line, row in enumerate(csv.reader(text.splitlines()), 1):
        if not row:
            continue
        key, *fields = row
        if key in rows:
            raise ValueError(f"Duplicate parameter {key} at line {line}")
        if key == "S":
            width = 16
        elif len(key) == 2 and key[0] in "ABCD" and key[1] in "HFL":
            width = {"H": 3, "F": 17, "L": 58}[key[1]]
        elif len(key) == 3 and key[0] in "ABCD" and key[1] == "M" and key[2] in "ABCDEFGHIJKLMNOP":
            width = 58
        elif len(key) == 3 and key[0] in "ABCD" and key[1] in "AC" and key[2] in "ABCDEFGHMU":
            width = 8 if key[2] == "M" else 1 if key[2] == "U" else 3
        else:
            raise ValueError(f"Unknown parameter {key!r} at line {line}")
        if len(fields) != width:
            raise ValueError(f"{key} requires {width} fields, found {len(fields)}")
        try:
            rows[key] = [int(field) for field in fields]
        except ValueError as error:
            raise ValueError(f"Non-integer field in {key} at line {line}") from error
    expected = {"S"}
    for group in "ABCD":
        expected.update(group + category for category in "HFL")
        expected.update(group + "M" + band for band in "ABCDEFGHIJKLMNOP")
        for bank in "AC":
            expected.update(group + bank + band for band in "ABCDEFGHMU")
    if set(rows) != expected:
        raise ValueError(f"Missing parameters: {', '.join(sorted(expected - rows.keys()))}")
    return rows


def peaking_coefficients(frequency, bandwidth, gain_db, sample_rate=SAMPLE_RATE):
    """Floating-point AMF type-1 transfer; not a bit-exact fixed-point DSP."""
    if not all(math.isfinite(value) for value in (frequency, bandwidth, gain_db, sample_rate)):
        raise ValueError("Filter parameters must be finite")
    if not 0 < frequency < sample_rate / 2 or bandwidth <= 0 or abs(gain_db) > 24:
        raise ValueError("Unsupported AMF frequency, bandwidth or gain")
    k = math.tan(math.pi * frequency / sample_rate)
    t = k * bandwidth / frequency
    v = 10 ** (abs(gain_db) / 20)
    squared = k * k
    denominator = 1 + (t if gain_db >= 0 else v * t) + squared
    numerator_t = v * t if gain_db >= 0 else t
    denominator_t = t if gain_db >= 0 else v * t
    return ((1 + numerator_t + squared) / denominator,
            2 * (squared - 1) / denominator,
            (1 - numerator_t + squared) / denominator,
            2 * (squared - 1) / denominator,
            (1 - denominator_t + squared) / denominator)


def response_db(coefficients, frequency, sample_rate=SAMPLE_RATE):
    if not math.isfinite(frequency) or not 0 <= frequency <= sample_rate / 2:
        raise ValueError("Response frequency is outside the Nyquist interval")
    b0, b1, b2, a1, a2 = coefficients
    z = cmath.exp(-2j * math.pi * frequency / sample_rate)
    magnitude = abs((b0 + b1 * z + b2 * z * z) / (1 + a1 * z + a2 * z * z))
    return 20 * math.log10(magnitude)


def highpass_response_db(cutoff, frequency, sample_rate=SAMPLE_RATE):
    """Conditional fourth-order Butterworth HPF magnitude; excludes all dynamics."""
    if not all(math.isfinite(value) for value in (cutoff, frequency, sample_rate)):
        raise ValueError("High-pass parameters must be finite")
    if not 0 < cutoff < sample_rate / 2 or not 0 < frequency <= sample_rate / 2:
        raise ValueError("Unsupported high-pass cutoff or response frequency")
    ratio = math.tan(math.pi * cutoff / sample_rate) / math.tan(math.pi * frequency / sample_rate)
    return -10 * math.log10(1 + ratio ** 8)


def compression_curve_mode2(gain, threshold):
    """Five-point control record, not a reconstruction of envelope/audio processing."""
    if not all(math.isfinite(value) for value in (gain, threshold)):
        raise ValueError("Compression controls must be finite")
    if not -30 <= gain <= 30 or not -30 <= threshold <= 0:
        raise ValueError("Unsupported compression gain or threshold")
    second = min(gain - 50, threshold - 10)
    quarter = (threshold - second) / 4
    return {"first_five_values": [-96.0, -50.0, -35.0, -20.0, 0.0],
            "second_five_values": [min(gain - 96, -91), second,
                                   min(gain - 35, second + 2 * quarter),
                                   min(gain - 20, second + 3 * quarter), threshold],
            "point_count": 5}


def analyze(payload):
    digest = hashlib.sha256(payload).hexdigest()
    if digest != PARAMETER_SHA256:
        raise ValueError("Unreviewed SoundBooster parameter file; refusing schema/units assumptions")
    rows = parse_rows(payload.decode("ascii"))
    banks = {}
    for group in "ABCD":
        for bank in "AC":
            prefix = group + bank
            enabled = rows[prefix + "U"][0]
            types = rows[prefix + "M"]
            if enabled not in (0, 1) or any(value != (1 if enabled else 0) for value in types):
                raise ValueError(f"Unreviewed AMF enable/type combination: {prefix}")
            filters = []
            for index, band in enumerate("ABCDEFGH"):
                frequency, bandwidth, gain = rows[prefix + band]
                coefficients = peaking_coefficients(frequency, bandwidth, gain) if enabled else None
                filters.append({
                    "row": prefix + band, "type": types[index],
                    "frequency_hz": frequency, "bandwidth_hz": bandwidth, "gain_db": gain,
                    "q": frequency / bandwidth,
                    "coefficients_b0_b1_b2_a1_a2": coefficients,
                })
            banks[prefix] = {
                "enabled": bool(enabled), "filters": filters,
                "static_amf_only_response_db": [
                    {"frequency_hz": frequency,
                     "gain_db": sum(response_db(item["coefficients_b0_b1_b2_a1_a2"], frequency)
                                    for item in filters) if enabled else 0.0}
                    for frequency in FREQUENCIES
                ],
            }
    return {
        "format": 1, "parameter_sha256": digest, "sample_rate_hz": SAMPLE_RATE,
        "scope": "Conditional static AMF banks only; NOT complete SoundBooster or a flashable preset",
        "runtime_bank_selection_verified": False,
        "fixed_point_bit_exact": False,
        "excluded": ["HPF", "pre-DRC", "multiband DRC", "volume scaling",
                     "channel reconfiguration", "motion switching", "other Samsung/Dolby stages"],
        "common_raw": rows["S"],
        "banks": banks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameters", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.parameters.read_bytes())
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"AMF analysis written to {args.output}; no device writes or runtime equivalence claim")


if __name__ == "__main__":
    main()

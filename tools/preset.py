"""Conservative speaker preset; firmware XML must be supplied locally."""

import hashlib
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
# Prefer the pinned host tools over older distribution versions without --cat.
os.environ["PATH"] = str(BUILD / "host-bin") + os.pathsep + os.environ.get("PATH", "")
VENDOR_TREE = BUILD / "vendor"
FILES = (
    "etc/audio_policy_volumes.xml",
    "etc/audio_policy_engine_stream_volumes.xml",
    "etc/dolby/dax-default.xml",
)
ORIGINAL_HASHES = (
    "618040c5019f8c3184d3fb557f88ee7e939f9c1bd79131fbb04241145003aa6b",
    "b33282e8765b3303d0d208d3316a45f8096476bc2cc9eae6a97ee5a100894863",
    "e867897cbf1ba05a372833c0ac77d6c28598bbd3218636665492fdb278ede20e",
)
ATTENUATION_MB = 600
EQ_Q4 = {
    47: -96, 141: -48, 234: -24, 328: -16, 469: -8,
    656: 0, 844: 0, 1031: 0, 1313: -8, 1688: -16,
    2250: -24, 3000: -24, 3750: -16, 4688: -8, 5813: 0,
    7125: -8, 9000: -16, 11250: -16, 13875: -24, 19688: -32,
}


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def canonical(node):
    return (
        node.tag, tuple(sorted(node.attrib.items())), (node.text or "").strip(),
        tuple(canonical(child) for child in node),
    )


def same_length_xml(original, text):
    payload = re.sub(r"\n[ \t]+", "\n", text).encode("utf-8").rstrip(b"\n")
    if len(payload) + 1 > len(original):
        raise ValueError("Modified XML does not fit the original decoded length")
    payload += b" " * (len(original) - len(payload) - 1) + b"\n"
    ET.fromstring(payload)
    return payload


def validate_curves(original, modified, defaults):
    before, after = ET.fromstring(original), ET.fromstring(modified)
    refs = {
        node.attrib["name"]: [point.text for point in node.findall("point")]
        for node in ET.fromstring(defaults).findall("reference")
    }
    selector = './/volume[@deviceCategory="DEVICE_CATEGORY_SPEAKER"]'
    old_speakers, new_speakers = before.findall(selector), after.findall(selector)
    if not old_speakers or len(old_speakers) != len(new_speakers):
        raise ValueError("Missing or added speaker curves")
    for old, new in zip(old_speakers, new_speakers):
        points = refs[old.attrib["ref"]] if "ref" in old.attrib else [
            point.text for point in old.findall("point")
        ]
        expected = []
        for point in points:
            index, gain = map(int, point.split(","))
            expected.append(f"{index},{gain - ATTENUATION_MB}")
        if [point.text for point in new.findall("point")] != expected:
            raise ValueError("Incorrect attenuation")
        new.attrib.clear()
        new.attrib.update(old.attrib)
        new.text = old.text
        for child in list(new):
            new.remove(child)
        for child in list(old):
            new.append(ET.fromstring(ET.tostring(child)))
    if canonical(before) != canonical(after):
        raise ValueError("Non-speaker volume configuration changed")


def attenuate_speakers(original, defaults):
    references = {
        node.attrib["name"]: [point.text for point in node.findall("point")]
        for node in ET.fromstring(defaults).findall("reference")
    }
    count = 0

    def replace(match):
        nonlocal count
        node = ET.fromstring(match.group())
        points = references[node.attrib.pop("ref")] if "ref" in node.attrib else [
            point.text for point in node.findall("point")
        ]
        if not points:
            raise ValueError("Speaker curve is empty")
        for child in list(node):
            node.remove(child)
        previous_index, previous_gain = -1, -100000
        for point in points:
            index, gain = map(int, point.split(","))
            if not previous_index < index <= 100 or gain < previous_gain or gain > 0:
                raise ValueError("Invalid source volume curve")
            ET.SubElement(node, "point").text = f"{index},{gain - ATTENUATION_MB}"
            previous_index, previous_gain = index, gain
        count += 1
        return ET.tostring(node, encoding="unicode")

    pattern = r'<volume\b[^>]*?deviceCategory="DEVICE_CATEGORY_SPEAKER"[^>]*?(?:/>|>.*?</volume>)'
    text = re.sub(pattern, replace, original.decode("utf-8"), flags=re.DOTALL)
    expected_count = len(ET.fromstring(original).findall(
        './/volume[@deviceCategory="DEVICE_CATEGORY_SPEAKER"]'
    ))
    if expected_count not in {12, 13} or count != expected_count:
        raise ValueError(f"Expected {expected_count} speaker curves, found {count}")
    result = same_length_xml(original, text)
    validate_curves(original, result, defaults)
    return result


def equalize_speakers(original):
    root = ET.fromstring(original)
    selector = './tuning[@name="speaker"]/data/audio-optimizer-bands'
    speaker = root.find(selector)
    if speaker is None or len(speaker) != len(EQ_Q4):
        raise ValueError("Unexpected speaker optimizer")
    modified = ET.fromstring(original)
    target = modified.find(selector)
    for old, new, (frequency, gain) in zip(speaker, target, EQ_Q4.items()):
        if old.attrib != {"frequency": str(frequency), "gain_left": "0", "gain_right": "0"}:
            raise ValueError("Unexpected original optimizer gains")
        if not -96 <= gain <= 0:
            raise ValueError("Prototype must not boost any band")
        new.set("gain_left", str(gain))
        new.set("gain_right", str(gain))
    match = re.search(
        r'(<tuning name="speaker"[^>]*>.*?)(<audio-optimizer-bands>.*?</audio-optimizer-bands>)',
        original.decode(), flags=re.DOTALL,
    )
    if match is None:
        raise ValueError("Speaker optimizer text not found")
    text = original.decode()
    text = text[:match.start(2)] + ET.tostring(target, encoding="unicode") + text[match.end(2):]
    result = same_length_xml(original, text)
    if canonical(ET.fromstring(result)) != canonical(modified):
        raise ValueError("Unintended Dolby configuration change")
    return result

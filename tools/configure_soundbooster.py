#!/usr/bin/env python3
"""Prepare a reviewed music-effect configuration and exact rollback; never install it."""

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

SOURCE_SHA256 = "ed6a693adae5c0e28170c48956f02f5f0e7cfba77d690c5fe40da163ed1d3ea0"
NAMESPACE = "http://schemas.android.com/audio/audio_effects_conf/v2_0"
LIBRARY = "adaptive_soundbooster"
LIBRARY_FILE = "libadaptive_soundbooster.so"
UUID = "d7625a14-10c6-4eed-98a0-322461ab7055"


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def candidate(payload):
    if digest(payload) != SOURCE_SHA256:
        raise ValueError("Unreviewed audio_effects.xml; configuration generation refused")
    root = ET.fromstring(payload)
    if root.tag != f"{{{NAMESPACE}}}audio_effects_conf" or root.get("version") != "2.0":
        raise ValueError("Unsupported effects configuration schema")
    ns = {"a": NAMESPACE}
    if root.find("a:postprocess", ns) is not None:
        raise ValueError("Existing postprocess attachment requires explicit review")
    if any(element.get("name") == LIBRARY or element.get("uuid") == UUID
           for element in root.iter()):
        raise ValueError("SoundBooster configuration already declared")
    replacements = (
        (b"    </libraries>", f'        <library name="{LIBRARY}" path="{LIBRARY_FILE}"/>\n'
         '    </libraries>'.encode("ascii")),
        (b"    </effects>", f'        <effect name="{LIBRARY}" library="{LIBRARY}" uuid="{UUID}"/>\n'
         '    </effects>'.encode("ascii")),
        (b"</audio_effects_conf>", f'    <postprocess>\n'
         '        <stream type="music">\n'
         f'            <apply effect="{LIBRARY}"/>\n'
         '        </stream>\n'
         '    </postprocess>\n\n</audio_effects_conf>'.encode("ascii")),
    )
    result = payload
    for marker, replacement in replacements:
        if result.count(marker) != 1:
            raise ValueError("Ambiguous effects configuration insertion point")
        result = result.replace(marker, replacement, 1)
    ET.fromstring(result)
    return result


def prepare(source, output):
    original = source.read_bytes()
    modified = candidate(original)
    # Refuse reuse so a previous rollback/configuration cannot be overwritten.
    output.mkdir(parents=True, exist_ok=False)
    (output / "audio_effects.xml").write_bytes(modified)
    (output / "audio_effects.original.xml").write_bytes(original)
    manifest = {
        "format": 1,
        "scope": "Configuration candidate only; not an installation package",
        "target": "/vendor/etc/audio_effects.xml",
        "original_sha256": digest(original),
        "candidate_sha256": digest(modified),
        "library": LIBRARY_FILE,
        "required_abi": "armeabi-v7a",
        "library_target": "/vendor/lib/soundfx/" + LIBRARY_FILE,
        "runtime_dependency": "Shared build needs libc++_shared.so; static-runtime build removes that direct "
                              "dependency, but platform runtime coexistence/service loading remain unverified",
        "implementation_uuid": UUID,
        "attachment": "music postprocess; bridge bypasses non-speaker routes",
        "android_service_integration_verified": False,
        "deployment_verified": False,
        "dolby_coexistence_verified": False,
        "libraries_included": False,
        "rollback_scope": "Exact original XML only; not a library/partition rollback procedure",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effects", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New, nonexistent output directory")
    args = parser.parse_args()
    prepare(args.effects, args.output)
    print(f"Configuration candidate and exact original saved under {args.output}. "
          "Not installed; no libraries included. Service compatibility and deployment remain unverified.")


if __name__ == "__main__":
    main()

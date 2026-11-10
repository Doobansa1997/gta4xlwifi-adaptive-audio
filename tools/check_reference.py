#!/usr/bin/env python3
"""Optional private reference-image integration test; never access block devices."""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

from preset import BUILD, FILES, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, default=BUILD / "stage")
    parser.add_argument("--samsung-vendor", type=Path,
                        help="Also require exact Samsung Dolby bytes in the selected patched templates")
    args = parser.parse_args()
    tool = BUILD / "audio-adaptive-host"
    stage = args.stage
    if args.samsung_vendor is not None:
        from package import verified_samsung_dolby
        if (stage / "templates/2.patched").read_bytes() != verified_samsung_dolby(args.samsung_vendor):
            raise ValueError("Baseline template does not exactly match the reviewed Samsung Dolby XML")
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        tools = directory / "tools"
        shutil.copytree(stage / "templates", tools / "templates")
        (tools / "bin").mkdir()
        for name in ("dump.erofs", "fsck.erofs"):
            executable = shutil.which(name)
            if executable is None:
                raise RuntimeError(f"Missing dependency: {name}")
            (tools / "bin" / name).symlink_to(executable)
        image = directory / "vendor.img"
        shutil.copyfile(BUILD / "reference-vendor.img", image)
        original_hash = digest(image)
        subprocess.run([str(tool), "checkboot", str(BUILD / "reference-boot.img")], check=True)
        for mode in ("preflight", "apply"):
            subprocess.run([str(tool), mode, "--file", str(image), str(directory / "backups"),
                            str(tools), str(directory)], check=True)
        for index, name in enumerate(FILES):
            content = subprocess.check_output(["dump.erofs", "--cat", f"--path=/{name}", str(image)])
            if content != (stage / "templates" / f"{index}.patched").read_bytes():
                raise ValueError(f"Patched reference XML mismatch: {name}")
        patched_hash = digest(image)
        subprocess.run([str(tool), "apply", "--file", str(image), str(directory / "backups"),
                        str(tools), str(directory)], check=True)
        if digest(image) != patched_hash:
            raise ValueError("Reapplication was not idempotent")
        subprocess.run([str(tool), "restore", "--file", str(image), str(directory / "backups"),
                        str(tools), str(directory)], check=True)
        if digest(image) != original_hash:
            raise ValueError("Restored image differs from the original")
        previous_tools = directory / "previous-tools"
        shutil.copytree(tools, previous_tools, symlinks=True)
        for index in range(len(FILES)):
            shutil.copyfile(previous_tools / "templates" / f"{index}.previous",
                            previous_tools / "templates" / f"{index}.patched")
        subprocess.run([str(tool), "replace", "--file", str(image), "-",
                        str(previous_tools), str(directory)], check=True)
        for index in range(len(FILES)):
            shutil.copyfile(previous_tools / "templates" / f"{index}.previous9",
                            previous_tools / "templates" / f"{index}.patched")
        subprocess.run([str(tool), "replace", "--file", str(image), "-",
                        str(previous_tools), str(directory)], check=True)
        for index in range(len(FILES)):
            shutil.copyfile(previous_tools / "templates" / f"{index}.previous11",
                            previous_tools / "templates" / f"{index}.patched")
        subprocess.run([str(tool), "replace", "--file", str(image), "-",
                        str(previous_tools), str(directory)], check=True)
        for index in range(len(FILES)):
            shutil.copyfile(previous_tools / "templates" / f"{index}.previous_treble",
                            previous_tools / "templates" / f"{index}.patched")
        subprocess.run([str(tool), "replace", "--file", str(image), "-",
                        str(previous_tools), str(directory)], check=True)
        for index in range(len(FILES)):
            shutil.copyfile(previous_tools / "templates" / f"{index}.previous_bass",
                            previous_tools / "templates" / f"{index}.patched")
        subprocess.run([str(tool), "replace", "--file", str(image), "-",
                        str(previous_tools), str(directory)], check=True)
        for mode in ("preflight", "replace", "replace", "reset", "reset"):
            subprocess.run([str(tool), mode, "--file", str(image), "-",
                            str(tools), str(directory)], check=True)
            suffix = "original" if mode == "reset" else "previous_bass" if mode == "preflight" else "patched"
            for index, name in enumerate(FILES):
                content = subprocess.check_output(["dump.erofs", "--cat", f"--path=/{name}", str(image)])
                if content != (tools / "templates" / f"{index}.{suffix}").read_bytes():
                    raise ValueError(f"Backup-free {mode} XML mismatch: {name}")
            if args.samsung_vendor is not None and mode == "replace":
                content = subprocess.check_output(["dump.erofs", "--cat",
                                                  "--path=/etc/dolby/dax-default.xml", str(image)])
                if content != verified_samsung_dolby(args.samsung_vendor):
                    raise ValueError("Installed Dolby XML differs from the reviewed Samsung firmware")
    print("PASS: private reference-image boot/preflight/apply/restore and backup-free migration/reset")


if __name__ == "__main__":
    main()

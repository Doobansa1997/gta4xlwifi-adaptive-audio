#!/usr/bin/env python3
"""Optional private reference-image integration test; never access block devices."""

from pathlib import Path
import shutil
import subprocess
import tempfile

from preset import BUILD, FILES, digest


def main():
    tool = BUILD / "audio-adaptive-host"
    stage = BUILD / "stage"
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
    print("PASS: private reference-image boot/preflight/apply/idempotency/restore")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compile recovery tools using a user-supplied Android NDK or host compiler."""

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
THIRD = ROOT / "third-party"
LZ4 = THIRD / "lz4-lz4-ebb370c" / "lib"
EROFS = THIRD / "erofs-erofs-utils-f36cadb"
OUT = ROOT / "build" / "bin"


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def build_host():
    objects = ROOT / "build/host-objects"
    objects.mkdir(exist_ok=True)
    for name in ("lz4", "lz4hc"):
        run(os.environ.get("CC", "cc"), "-O2", "-c", str(LZ4 / f"{name}.c"),
            "-o", str(objects / f"{name}.o"))
    run(os.environ.get("AR", "ar"), "rcs", str(objects / "liblz4.a"),
        str(objects / "lz4.o"), str(objects / "lz4hc.o"))
    run(os.environ.get("CXX", "c++"), "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
        "-I" + str(LZ4), "-I" + str(THIRD),
        str(ROOT / "src/adaptive.cpp"), str(objects / "liblz4.a"),
        "-lz", "-o", str(ROOT / "build/audio-adaptive-host"))
    build = ROOT / "build/host-erofs"
    build.mkdir(exist_ok=True)
    out = ROOT / "build/host-bin"
    out.mkdir(exist_ok=True)
    fec = THIRD / "fec-90857de"
    for name in ("init_rs_char", "encode_rs_char"):
        run(os.environ.get("CC", "cc"), "-O2", "-c", str(fec / (name + ".c")),
            "-I" + str(fec), "-o", str(objects / (name + ".o")))
    run(os.environ.get("CXX", "c++"), "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
        "-I" + str(THIRD), "-I" + str(fec), str(ROOT / "tools/fec_encode.cpp"),
        str(objects / "init_rs_char.o"), str(objects / "encode_rs_char.o"), "-o", str(out / "fec"))
    env = os.environ.copy()
    env.update({
        "CFLAGS": "-O2", "LDFLAGS": f"-L{objects}",
        "PKG_CONFIG_LIBDIR": str(objects / "no-host-pkgconfig"),
        "liblz4_CFLAGS": f"-I{LZ4}", "liblz4_LIBS": str(objects / "liblz4.a"),
    })
    if not (EROFS / "configure").exists():
        run("./autogen.sh", cwd=EROFS)
    run(str(EROFS / "configure"), "--disable-shared", "--enable-static",
        "--disable-multithreading", "--enable-lz4", "--disable-lzma",
        "--without-zlib", "--without-uuid", "--without-libcurl", "--without-openssl",
        "--without-libxml2", "--without-json-c", "--without-libnl3", cwd=build, env=env)
    run("make", "-C", str(build / "lib"), "-j4", env=env)
    for directory, name in (("dump", "dump.erofs"), ("fsck", "fsck.erofs"), ("mkfs", "mkfs.erofs")):
        run("make", "-C", str(build / directory), "-j4", env=env)
        shutil.copyfile(build / directory / name, out / name)
        (out / name).chmod(0o755)
    run(os.environ.get("CXX", "c++"), "-std=gnu++17", "-O2", "-Wall", "-Wextra", "-Werror",
        "-DHAVE_CONFIG_H", "-I" + str(build), "-isystem", str(EROFS / "include"), "-I" + str(THIRD),
        str(ROOT / "tools/erofs_manifest.cpp"), str(build / "lib/.libs/liberofs.a"),
        str(objects / "liblz4.a"), "-o", str(out / "erofs-manifest"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-only", action="store_true", help="Build native test and pinned EROFS tools")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.host_only:
        build_host()
        return
    ndk_home = os.environ.get("ANDROID_NDK_HOME")
    if not ndk_home:
        raise ValueError("Set ANDROID_NDK_HOME to an installed Android NDK (tested: 28.2.13676358)")
    host = {"Darwin": "darwin-x86_64", "Linux": "linux-x86_64"}.get(platform.system())
    if host is None:
        raise ValueError("Builds support macOS and Linux only")
    BIN = Path(ndk_home).resolve() / "toolchains/llvm/prebuilt" / host / "bin"
    if not (BIN / "aarch64-linux-android28-clang").is_file():
        raise ValueError("Android ARM64 API-28 compiler not found in ANDROID_NDK_HOME")
    objects = ROOT / "build/objects"
    objects.mkdir(parents=True, exist_ok=True)
    cc = BIN / "aarch64-linux-android28-clang"
    cxx = BIN / "aarch64-linux-android28-clang++"
    for name in ("lz4", "lz4hc"):
        run(str(cc), "-O2", "-fPIC", "-c", str(LZ4 / f"{name}.c"),
            "-o", str(objects / f"{name}.o"))
    run(str(BIN / "llvm-ar"), "rcs", str(objects / "liblz4.a"),
        str(objects / "lz4.o"), str(objects / "lz4hc.o"))
    env = os.environ.copy()
    env.update({
        "CC": str(cc), "AR": str(BIN / "llvm-ar"),
        "RANLIB": str(BIN / "llvm-ranlib"), "STRIP": str(BIN / "llvm-strip"),
        "CFLAGS": "-O2", "LDFLAGS": f"-static -L{objects}",
        "PKG_CONFIG_LIBDIR": str(objects / "no-host-pkgconfig"),
        "liblz4_CFLAGS": f"-I{LZ4}", "liblz4_LIBS": str(objects / "liblz4.a"),
        "ac_cv_func_copy_file_range": "no",
    })
    build = ROOT / "build/erofs"
    build.mkdir(parents=True, exist_ok=True)
    if not (EROFS / "configure").exists():
        run("./autogen.sh", cwd=EROFS)
    run(str(EROFS / "configure"), "--host=aarch64-linux-android",
        "--disable-shared", "--enable-static", "--disable-multithreading", "--enable-lz4",
        "--disable-lzma", "--without-zlib", "--without-uuid",
        "--without-libcurl", "--without-openssl", "--without-libxml2",
        "--without-json-c", "--without-libnl3", cwd=build, env=env)
    run("make", "-C", str(build / "lib"), "-j4", env=env)
    for directory, name in (("dump", "dump.erofs"), ("fsck", "fsck.erofs")):
        run("make", "-C", str(build / directory), "clean", env=env)
        run("make", "-C", str(build / directory), "-j4", "LDFLAGS=-all-static", env=env)
        shutil.copyfile(build / directory / name, OUT / name)
    run(str(cxx), "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
        "-static", "-static-libstdc++", "-I" + str(LZ4), "-I" + str(THIRD),
        str(ROOT / "src/adaptive.cpp"), str(objects / "liblz4.a"), "-lz",
        "-o", str(OUT / "audio-adaptive"))
    for path in OUT.iterdir():
        run(str(BIN / "llvm-strip"), str(path))
    licenses = ROOT / "build/licenses"
    licenses.mkdir(exist_ok=True)
    for source, name in (
        (THIRD / "picosha2.h", "PicoSHA2-header-and-license"),
        (LZ4 / "LICENSE", "LZ4-LICENSE"),
        (EROFS / "COPYING", "EROFS-COPYING"),
        (ROOT / "LICENSE", "PROJECT-MIT"),
        (Path(ndk_home) / "NOTICE", "ANDROID-NDK-NOTICE"),
        (Path(ndk_home) / "NOTICE.toolchain", "ANDROID-TOOLCHAIN-NOTICE"),
    ):
        shutil.copyfile(source, licenses / name)
    shutil.copytree(EROFS / "LICENSES", licenses / "erofs", dirs_exist_ok=True)


if __name__ == "__main__":
    main()

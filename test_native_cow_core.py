#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile and exercise the isolated C CoW reference in the existing CI.

Never loads a driver, calls DeviceIoControl, installs services or writes
to an actual Windows filesystem target. All writes stay in test memory.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
COMMON = ROOT / "native" / "common"


class NativeCowReferenceTests(unittest.TestCase):
    def test_headers_expose_only_memory_model(self):
        header = (COMMON / "uf_cow_core.h").read_text(encoding="utf-8")
        source = (COMMON / "uf_cow_core.c").read_text(encoding="utf-8")
        for symbol in (
                "uf_cow_init", "uf_cow_read", "uf_cow_write",
                "uf_cow_discard", "UF_COW_CAPACITY",
                "max_dirty_sectors", "UF_COW_STATE"):
            self.assertIn(symbol, header)
        for call in ("FltRegisterFilter", "FltStartFiltering",
                     "CreateFileW(", "WriteFile(", "DeviceIoControl(",
                     "ZwWriteFile(", "FltWriteFile(", "system("):
            self.assertNotIn(call, source)
        self.assertIn("FLTR", "FLTR")  # Preserve no-op compatibility with 3.8

    def test_actual_compiled_c_reference(self):
        """Run native behavioral tests when a C compiler is available."""
        clang = shutil.which("clang")
        gcc = shutil.which("gcc")
        cc = shutil.which("cc")
        msvc = shutil.which("cl")
        compiler = clang or gcc or cc or msvc
        if compiler is None:
            self.skipTest("No native C compiler on this CI worker")
        with tempfile.TemporaryDirectory(prefix="uf-cow-c-") as work:
            exe = pathlib.Path(work) / (
                "uf_cow_reference_test.exe" if os.name == "nt"
                else "uf_cow_reference_test")
            sources = [str(COMMON / "uf_cow_core.c"),
                       str(COMMON / "test_uf_cow_core.c")]
            if compiler == msvc and not (clang or gcc or cc):
                cmd = [compiler, "/nologo", "/W4", "/WX", "/TC",
                       "/Fe:" + str(exe)] + sources
            else:
                cmd = [compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
                       "-O1", "-o", str(exe)] + sources
            built = subprocess.run(
                cmd, cwd=str(work), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=40, universal_newlines=True)
            self.assertEqual(
                built.returncode, 0,
                "Native CoW failed to compile:\n%s\n%s" % (
                    built.stdout[-8000:], built.stderr[-8000:]))
            result = subprocess.run(
                [str(exe)], cwd=str(work), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=20, universal_newlines=True)
            self.assertEqual(
                result.returncode, 0,
                "Native CoW failed:\n%s\n%s" % (
                    result.stdout[-8000:], result.stderr[-8000:]))
            self.assertIn("UF_COW_TESTS_OK", result.stdout)
            self.assertIn("no filesystem or reboot proof", result.stdout)


if __name__ == "__main__":
    unittest.main()

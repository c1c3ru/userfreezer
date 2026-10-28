#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native NT relative handle proof; Windows 7-compatible APIs only."""
import os
import subprocess
import tempfile
import unittest

from win32_relative_directory import (
    directory_identity, open_relative_directory, open_trusted_root,
    create_relative_file)


@unittest.skipUnless(os.name == "nt", "NtCreateFile so Windows")
class NativeRelativeOpenProof(unittest.TestCase):
    def test_reparse_final_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            outside = os.path.join(temp, "outside")
            root = os.path.join(temp, "root")
            os.makedirs(outside)
            os.makedirs(root)
            junction = os.path.join(root, "junction")
            cmd = subprocess.run(
                ["cmd", "/c", "mklink", "/J", junction, outside],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if cmd.returncode:
                self.skipTest("mklink /J indisponivel: %r" % cmd.stderr)
            try:
                with open_trusted_root(root) as parent:
                    with self.assertRaises(OSError):
                        with open_relative_directory(parent, "junction"):
                            pass
            finally:
                if os.path.lexists(junction):
                    os.rmdir(junction)

    def test_handle_relative_remains_under_original_parent_after_junction_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "root")
            outside = os.path.join(temp, "outside")
            os.makedirs(os.path.join(root, "sub", "deep"))
            os.makedirs(os.path.join(outside, "deep"))
            old = os.path.join(root, "sub")
            moved = os.path.join(root, "moved")
            with open_trusted_root(root) as trusted:
                with open_relative_directory(trusted, "sub") as pinned:
                    # Rename while handle open MUST NOT redirect RootDirectory.
                    cp = subprocess.run(
                        [__import__("sys").executable, "-c",
                         "import os,sys; os.rename(sys.argv[1],sys.argv[2])",
                         old, moved],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if cp.returncode:
                        self.skipTest("rename of pinned dir not supported: %r" % cp.stderr)
                    created = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", old, outside],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if created.returncode:
                        self.skipTest("mklink nao suportado: %r" % created.stderr)
                    try:
                        with open_relative_directory(pinned, "deep") as safe:
                            safe_id = directory_identity(safe)
                        with open_trusted_root(os.path.join(moved, "deep")) as original:
                            original_id = directory_identity(original)
                        with open_trusted_root(os.path.join(outside, "deep")) as external:
                            external_id = directory_identity(external)
                        self.assertEqual(safe_id, original_id)
                        self.assertNotEqual(safe_id, external_id)
                    finally:
                        if os.path.lexists(old):
                            os.rmdir(old)

    def test_create_relative_file_fica_na_arvore_original_apos_junction_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "root")
            outside = os.path.join(temp, "outside")
            os.makedirs(os.path.join(root, "sub"))
            os.makedirs(outside)
            old = os.path.join(root, "sub")
            moved = os.path.join(root, "moved")
            with open_trusted_root(root) as trusted:
                with open_relative_directory(trusted, "sub") as pinned:
                    cp = subprocess.run(
                        [__import__("sys").executable, "-c",
                         "import os,sys; os.rename(sys.argv[1],sys.argv[2])",
                         old, moved], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if cp.returncode:
                        self.skipTest("rename indisponivel: %r" % cp.stderr)
                    link = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", old, outside],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if link.returncode:
                        self.skipTest("junction indisponivel: %r" % link.stderr)
                    try:
                        payload = b"gravacao vinculada ao handle" * 70000
                        self.assertEqual(
                            create_relative_file(pinned, "novo.txt", payload),
                            len(payload))
                        with open(os.path.join(moved, "novo.txt"), "rb") as fin:
                            self.assertEqual(fin.read(), payload)
                        self.assertFalse(os.path.exists(
                            os.path.join(outside, "novo.txt")))
                        with self.assertRaises(OSError):
                            create_relative_file(pinned, "novo.txt", b"overwrite")
                    finally:
                        if os.path.lexists(old):
                            os.rmdir(old)

    def test_create_relative_file_rejeita_componentes_inseguros(self):
        with tempfile.TemporaryDirectory() as temp:
            with open_trusted_root(temp) as root:
                for name in ("..", "x/y", "x\\\\y", "evil:ads", "", "a."):
                    with self.subTest(name=name):
                        with self.assertRaises(ValueError):
                            create_relative_file(root, name, b"a")

    def test_component_rejects_relative_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            with open_trusted_root(temp) as parent:
                for name in ("..", ".", "", r"..\\escape", "/etc",
                             "C:", "evil:stream", "dot."):
                    with self.subTest(name=name):
                        with self.assertRaises(ValueError):
                            with open_relative_directory(parent, name):
                                pass


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native NT relative handle proof; Windows 7-compatible APIs only."""
import os
import subprocess
import tempfile
import unittest

from win32_relative_directory import (
    directory_identity, open_relative_directory, open_trusted_root,
    create_relative_file, create_relative_directory, delete_relative_file,
    rename_relative_file)


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

    def test_mkdir_unlink_relativos_apos_troca_por_junction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "root")
            outside = os.path.join(temp, "outside")
            old = os.path.join(root, "sub")
            moved = os.path.join(root, "moved")
            os.makedirs(old)
            os.makedirs(outside)
            sentinel = os.path.join(outside, "sentinela.txt")
            with open(sentinel, "wb") as out:
                out.write(b"NAO MODIFICAR")
            with open_trusted_root(root) as trusted:
                with open_relative_directory(trusted, "sub") as pinned:
                    create_relative_file(pinned, "apagar.txt", b"somente-interno")
                    cp = subprocess.run(
                        [__import__("sys").executable, "-c",
                         "import os,sys; os.rename(sys.argv[1],sys.argv[2])",
                         old, moved], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertEqual(cp.returncode, 0, cp.stderr)
                    link = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", old, outside],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertEqual(link.returncode, 0, link.stderr)
                    try:
                        identity = create_relative_directory(pinned, "created")
                        with open_trusted_root(os.path.join(moved, "created")) as newdir:
                            self.assertEqual(directory_identity(newdir), identity)
                        self.assertFalse(os.path.exists(os.path.join(outside, "created")))
                        delete_relative_file(pinned, "apagar.txt")
                        self.assertFalse(os.path.lexists(
                            os.path.join(moved, "apagar.txt")))
                        self.assertEqual(open(sentinel, "rb").read(),
                                         b"NAO MODIFICAR")
                    finally:
                        if os.path.lexists(old):
                            os.rmdir(old)

    def test_unlink_recusa_reparse_e_diretorio(self):
        with tempfile.TemporaryDirectory() as temp:
            outside = os.path.join(temp, "outside")
            root = os.path.join(temp, "root")
            os.mkdir(root)
            os.mkdir(outside)
            junction = os.path.join(root, "danger")
            with open(os.path.join(outside, "secret.txt"), "wb") as out:
                out.write(b"preservar")
            link = subprocess.run(
                ["cmd", "/c", "mklink", "/J", junction, outside],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if link.returncode:
                self.skipTest("junction indisponivel: %r" % link.stderr)
            try:
                with open_trusted_root(root) as pinned:
                    with self.assertRaises(OSError):
                        delete_relative_file(pinned, "danger")
                    with self.assertRaises(OSError):
                        delete_relative_file(pinned, "missing")
                self.assertEqual(
                    open(os.path.join(outside, "secret.txt"), "rb").read(),
                    b"preservar")
            finally:
                if os.path.lexists(junction):
                    os.rmdir(junction)

    def test_mkdir_e_unlink_recusam_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            with open_trusted_root(temp) as parent:
                for name in ("..", ".", "bad/path", r"bad\\child",
                             "bad:ads", "", "ending."):
                    with self.subTest(name=name):
                        with self.assertRaises(ValueError):
                            create_relative_directory(parent, name)
                        with self.assertRaises(ValueError):
                            delete_relative_file(parent, name)

    def test_rename_e_replace_relativos_apos_junction_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "root")
            outside = os.path.join(temp, "outside")
            old = os.path.join(root, "sub")
            moved = os.path.join(root, "moved")
            os.makedirs(old)
            os.makedirs(outside)
            with open(os.path.join(outside, "dest.txt"), "wb") as out:
                out.write(b"EXTERNO")
            with open_trusted_root(root) as trusted:
                with open_relative_directory(trusted, "sub") as pinned:
                    create_relative_file(pinned, "source.txt", b"NOVO")
                    create_relative_file(pinned, "dest.txt", b"ANTIGO")
                    cp = subprocess.run(
                        [__import__("sys").executable, "-c",
                         "import os,sys; os.rename(sys.argv[1],sys.argv[2])",
                         old, moved], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertEqual(cp.returncode, 0, cp.stderr)
                    link = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", old, outside],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertEqual(link.returncode, 0, link.stderr)
                    try:
                        # Sem replace, colidir em arquivo existente falha.
                        with self.assertRaises(OSError):
                            rename_relative_file(pinned, "source.txt", "dest.txt")
                        rename_relative_file(pinned, "source.txt",
                                             "dest.txt", replace=True)
                        self.assertFalse(os.path.exists(os.path.join(moved, "source.txt")))
                        with open(os.path.join(moved, "dest.txt"), "rb") as inp:
                            self.assertEqual(inp.read(), b"NOVO")
                        with open(os.path.join(outside, "dest.txt"), "rb") as inp:
                            self.assertEqual(inp.read(), b"EXTERNO")
                    finally:
                        if os.path.lexists(old):
                            os.rmdir(old)

    def test_rename_recusa_entrada_ambigua_ou_reparse(self):
        with tempfile.TemporaryDirectory() as temp:
            with open_trusted_root(temp) as parent:
                for invalid in ("..", ".", "dir/file", r"dir\\file",
                                "bad:stream", "last.", ""):
                    with self.subTest(invalid=invalid):
                        with self.assertRaises(ValueError):
                            rename_relative_file(parent, invalid, "safe.txt")
                        with self.assertRaises(ValueError):
                            rename_relative_file(parent, "safe.txt", invalid)
                with self.assertRaises(ValueError):
                    rename_relative_file(parent, "Same.txt", "same.TXT")

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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two-process Windows regression for pinned NT handles (#63).

ATTACK: a separate process renames the target directory and creates an
NTFS junction at its old pathname for each round.
DEFENSE: the first process keeps a handle to the original NT directory
and performs mkdir/write/rename/unlink/rmtree relative to that handle.

This is not a real Win7 SP1 VM test. Controlled pre-open swaps use an
already-enrolled root identity; uncontrolled races and full audit remain open.
"""
import os
import subprocess
import sys
import tempfile
import unittest

from win32_relative_directory import (
    open_trusted_root, open_relative_directory, create_relative_directory,
    create_relative_file, rename_relative_file, delete_relative_file,
    remove_relative_tree,
)


@unittest.skipUnless(os.name == "nt", "somente Windows NTFS")
class NtHandleRaceStress(unittest.TestCase):
    def test_twelve_cross_process_junction_swaps_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as temp:
            target = os.path.join(temp, "protected")
            moved = os.path.join(temp, "renamed")
            outside = os.path.join(temp, "outside")
            os.mkdir(target)
            os.mkdir(outside)
            sentinel = os.path.join(outside, "sentinel.txt")
            with open(sentinel, "wb") as out:
                out.write(b"EXTERNAL-ORIGINAL")
            worker = r"""
import os, subprocess, sys
target, moved, outside = sys.argv[1:]
for i in range(12):
    os.rename(target, moved)
    subprocess.check_call(
        ["cmd", "/c", "mklink", "/J", target, outside],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sys.stdout.write("swapped\n")
    sys.stdout.flush()
    if not sys.stdin.readline():
        raise RuntimeError("victim disconnected")
    os.rmdir(target)
    os.rename(moved, target)
"""
            proc = None
            with open_trusted_root(target) as pinned:
                try:
                    proc = subprocess.Popen(
                        [sys.executable, "-u", "-c", worker,
                         target, moved, outside],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, universal_newlines=True)
                    for i in range(12):
                        signal = proc.stdout.readline().strip()
                        self.assertEqual(signal, "swapped",
                                         "attacker did not swap path round=%d" % i)
                        folder = "round-%02d" % i
                        create_relative_directory(pinned, folder)
                        with open_relative_directory(pinned, folder) as sub:
                            create_relative_file(sub, "temp.txt", b"trusted")
                            rename_relative_file(sub, "temp.txt", "renamed.txt")
                            delete_relative_file(sub, "renamed.txt")
                        remove_relative_tree(pinned, folder)
                        self.assertFalse(os.path.lexists(
                            os.path.join(outside, folder)))
                        with open(sentinel, "rb") as check:
                            self.assertEqual(check.read(), b"EXTERNAL-ORIGINAL")
                        proc.stdin.write("\n")
                        proc.stdin.flush()
                    proc.stdin.close()
                    status = proc.wait(timeout=30)
                    err = proc.stderr.read()
                    self.assertEqual(status, 0, err)
                finally:
                    if proc is not None and proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=10)
            self.assertFalse(os.path.lexists(moved))
            self.assertTrue(os.path.isdir(target))
            with open(sentinel, "rb") as check:
                self.assertEqual(check.read(), b"EXTERNAL-ORIGINAL")

    def test_sixteen_preopen_directory_swaps_require_enrolled_identity(self):
        """Separate process replaces the root BEFORE every consumer open."""
        from nt_commit_experimental import apply_enrolled_plan_experimental
        from win32_relative_directory import directory_identity

        with tempfile.TemporaryDirectory() as temp:
            target = os.path.join(temp, "protected")
            moved = os.path.join(temp, "original-moved")
            decoy = os.path.join(temp, "decoy")
            os.mkdir(target)
            os.mkdir(decoy)
            with open(os.path.join(target, "sentinel.txt"), "wb") as out:
                out.write(b"ORIGINAL")
            with open(os.path.join(decoy, "sentinel.txt"), "wb") as out:
                out.write(b"EXTERNAL")
            with open_trusted_root(target) as handle:
                enrolled = directory_identity(handle)

            worker = r"""
import os, sys
target, moved, decoy = sys.argv[1:]
for i in range(16):
    os.rename(target, moved)
    os.rename(decoy, target)
    sys.stdout.write("swapped\n")
    sys.stdout.flush()
    if not sys.stdin.readline():
        raise RuntimeError("victim disconnected")
    os.rename(target, decoy)
    os.rename(moved, target)
    sys.stdout.write("restored\n")
    sys.stdout.flush()
"""
            proc = None
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-u", "-c", worker, target, moved, decoy],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, universal_newlines=True)
                for i in range(16):
                    self.assertEqual(proc.stdout.readline().strip(), "swapped",
                                     "attacker did not swap round=%d" % i)
                    with self.assertRaises(OSError):
                        apply_enrolled_plan_experimental(
                            target, [("W", "sentinel.txt", b"ESCAPED")],
                            enrolled)
                    with open(os.path.join(target, "sentinel.txt"), "rb") as src:
                        self.assertEqual(src.read(), b"EXTERNAL")
                    self.assertFalse(os.path.lexists(
                        os.path.join(target, "round-%02d.txt" % i)))
                    proc.stdin.write("\n")
                    proc.stdin.flush()
                    self.assertEqual(proc.stdout.readline().strip(), "restored")
                    name = "round-%02d.txt" % i
                    self.assertEqual(
                        apply_enrolled_plan_experimental(
                            target, [("W", name, b"TRUSTED")], enrolled),
                        [name])
                    with open(os.path.join(target, name), "rb") as src:
                        self.assertEqual(src.read(), b"TRUSTED")
                    self.assertFalse(os.path.lexists(os.path.join(decoy, name)))
                proc.stdin.close()
                status = proc.wait(timeout=30)
                err = proc.stderr.read()
                self.assertEqual(status, 0, err)
            finally:
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=10)
            self.assertFalse(os.path.lexists(moved))
            with open(os.path.join(decoy, "sentinel.txt"), "rb") as src:
                self.assertEqual(src.read(), b"EXTERNAL")



if __name__ == "__main__":
    unittest.main()

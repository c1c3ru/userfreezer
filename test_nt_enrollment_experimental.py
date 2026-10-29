#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Experimental, account-scoped DPAPI root identity tests (#63)."""
import os
import tempfile
import unittest

from nt_enrollment_experimental import (
    _canonical_root, _checked_identity, seal_root_identity,
    unseal_root_identity, apply_sealed_plan_experimental,
)


class EnrollmentValidationTests(unittest.TestCase):
    def test_rejects_root_volume_unc_and_noncanonical_paths(self):
        for root in ("", "/", "C:\\", "C:relative", r"\\host\share\root",
                     r"\\?\C:\folder", "C:/mixed", "C:\\folder\\..",
                     "C:\\folder\\\\double", "C:\\CON"):
            with self.subTest(root=root), self.assertRaises(ValueError):
                _canonical_root(root)

    def test_rejects_bad_identity(self):
        for identity in ((1, 2), [1, 2, 3], (1, True, 3),
                         (-1, 2, 3), (1, 2, 0x100000000)):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                _checked_identity(identity)

    def test_requires_windows_dpapi(self):
        if os.name != "nt":
            with self.assertRaises(OSError):
                seal_root_identity("C:\\data", (1, 2, 3))

    def test_invalid_envelope_fails_before_dpapi(self):
        for value in (None, "", b"", b"x" * 16385):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError):
                    unseal_root_identity("C:\\trusted", value)


@unittest.skipUnless(os.name == "nt", "requires Windows DPAPI")
class WindowsDpapiEnrollmentTests(unittest.TestCase):
    def test_roundtrip_same_principal(self):
        root = r"C:\Lab\Protected"
        expected = (1234, 5678, 9012)
        blob = seal_root_identity(root, expected)
        self.assertIsInstance(blob, bytes)
        self.assertEqual(unseal_root_identity(root, blob), expected)
        self.assertEqual(unseal_root_identity(r"c:\lab\protected", blob), expected)

    def test_tampering_and_wrong_root_are_rejected(self):
        root = r"C:\Lab\Protected"
        blob = seal_root_identity(root, (1, 2, 3))
        with self.assertRaises(OSError):
            unseal_root_identity(root, blob[:-1] + bytes([blob[-1] ^ 0x01]))
        with self.assertRaises(ValueError):
            unseal_root_identity(r"C:\Lab\Other", blob)

    def test_sealed_record_blocks_preopen_directory_replacement(self):
        from win32_relative_directory import open_trusted_root, directory_identity
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "protected")
            moved = os.path.join(temp, "original")
            decoy = os.path.join(temp, "decoy")
            os.mkdir(root)
            os.mkdir(decoy)
            with open_trusted_root(root) as handle:
                blob = seal_root_identity(root, directory_identity(handle))
            with open(os.path.join(decoy, "sentinel.txt"), "wb") as out:
                out.write(b"EXTERNAL")
            os.rename(root, moved)
            os.rename(decoy, root)
            with self.assertRaises(OSError):
                apply_sealed_plan_experimental(
                    root, [("W", "sentinel.txt", b"CHANGED")], blob)
            with open(os.path.join(root, "sentinel.txt"), "rb") as inp:
                self.assertEqual(inp.read(), b"EXTERNAL")
            self.assertFalse(os.path.lexists(os.path.join(moved, "sentinel.txt")))


if __name__ == "__main__":
    unittest.main()

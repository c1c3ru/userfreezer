#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for read-only protected NT root enrollment store (#63)."""
import os
import tempfile
import unittest
from unittest import mock

from nt_enrollment_store_experimental import (
    _validate_acl_entries, load_identity_from_store,
    record_name_for_root, apply_stored_plan_experimental,
)
from win32_relative_directory import (
    open_trusted_root, read_relative_file,
)


class EnrollmentStorePolicyTests(unittest.TestCase):
    def test_record_filename_is_canonical_and_not_user_controlled(self):
        one = record_name_for_root(r"C:\Data\Protected")
        two = record_name_for_root(r"c:\data\protected")
        self.assertEqual(one, two)
        self.assertEqual(len(one), 70)
        self.assertTrue(one.endswith(".dpapi"))
        with self.assertRaises(ValueError):
            record_name_for_root(r"\\server\share\protected")

    def test_acl_policy_rejects_untrusted_owner_and_world_writable(self):
        system = "S-1-5-18"
        admins = "S-1-5-32-544"
        everyone = "S-1-1-0"
        self.assertTrue(_validate_acl_entries(
            system, [(0, system), (0, admins), (1, everyone)]))
        for owner, aces in (
                (everyone, [(0, system)]),
                (system, [(0, everyone), (0, system)]),
                (admins, [(9, admins)]),
                (system, []),
                (system, [(1, everyone)])):
            with self.subTest(owner=owner, aces=aces):
                with self.assertRaises(PermissionError):
                    _validate_acl_entries(owner, aces)

    def test_read_rejected_by_parent_acl_never_opens_record(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "open_trusted_root") as opener:
            with mock.patch.object(store, "_assert_protected_acl",
                                   side_effect=PermissionError("ACL denied")):
                with mock.patch.object(store, "read_relative_file") as reader:
                    opener.return_value.__enter__.return_value = object()
                    with self.assertRaises(PermissionError):
                        load_identity_from_store(
                            r"C:\Data\Protected", r"C:\ProgramData\DeepFreezer\Enroll")
                    reader.assert_not_called()

    def test_load_validates_file_acl_and_unseals_only_after_read(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "open_trusted_root") as opener:
            with mock.patch.object(store, "_assert_protected_acl") as guard:
                with mock.patch.object(store, "read_relative_file",
                                       return_value=b"ciphertext") as reader:
                    with mock.patch.object(store, "unseal_root_identity",
                                           return_value=(1, 2, 3)) as unseal:
                        opener.return_value.__enter__.return_value = 99
                        actual = load_identity_from_store(
                            r"C:\Data\Protected", r"C:\ProgramData\DeepFreezer\Enroll")
                        self.assertEqual(actual, (1, 2, 3))
                        opener.assert_called_once_with(
                            r"C:\ProgramData\DeepFreezer\Enroll", read_control=True)
                        guard.assert_called_once_with(99)
                        reader.assert_called_once_with(
                            99, record_name_for_root(r"C:\Data\Protected"),
                            max_bytes=16384, handle_guard=store._assert_protected_acl)
                        unseal.assert_called_once_with(
                            r"C:\Data\Protected", b"ciphertext")

    def test_loaded_identity_reaches_only_strict_experimental_entry(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "load_identity_from_store",
                               return_value=(7, 8, 9)):
            import nt_commit_experimental as commit
            with mock.patch.object(commit, "apply_enrolled_plan_experimental",
                                   return_value=["ok"]) as apply:
                result = apply_stored_plan_experimental(
                    r"C:\Data\Protected", [("W", "ok", b"x")],
                    r"C:\ProgramData\DeepFreezer\Enroll")
                self.assertEqual(result, ["ok"])
                apply.assert_called_once_with(
                    r"C:\Data\Protected", [("W", "ok", b"x")], (7, 8, 9))

    def test_invalid_store_path_fails_before_any_handle(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "open_trusted_root") as opener:
            with self.assertRaises(ValueError):
                load_identity_from_store(r"C:\Data", r"\\server\share\Enroll")
            opener.assert_not_called()


@unittest.skipUnless(os.name == "nt", "requires Windows native NT handles")
class NtHandleReadTests(unittest.TestCase):
    def test_read_bounded_and_exact(self):
        with tempfile.TemporaryDirectory() as root:
            name = "sealed.dpapi"
            payload = bytes(range(256)) * 64
            with open(os.path.join(root, name), "wb") as stream:
                stream.write(payload)
            with open_trusted_root(root) as directory:
                self.assertEqual(read_relative_file(directory, name), payload)
                with self.assertRaises(ValueError):
                    read_relative_file(directory, name, max_bytes=128)
                with self.assertRaises(ValueError):
                    read_relative_file(directory, "../outside")
                with self.assertRaises(ValueError):
                    read_relative_file(directory, name, max_bytes=0)
                with self.assertRaises(PermissionError):
                    read_relative_file(
                        directory, name,
                        handle_guard=lambda _handle: (_ for _ in ()).throw(
                            PermissionError("ACL refused")))

    def test_file_reparse_point_is_not_read(self):
        with tempfile.TemporaryDirectory() as root:
            origin = os.path.join(root, "origin.txt")
            link = os.path.join(root, "alias.dpapi")
            with open(origin, "wb") as out:
                out.write(b"not allowed")
            try:
                os.symlink(origin, link)
            except (OSError, NotImplementedError) as exc:
                self.skipTest("Windows symlink privilege unavailable: %s" % exc)
            with open_trusted_root(root) as directory:
                with self.assertRaises(OSError):
                    read_relative_file(directory, "alias.dpapi")


if __name__ == "__main__":
    unittest.main()

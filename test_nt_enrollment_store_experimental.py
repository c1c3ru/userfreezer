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



class FirstEnrollmentTests(unittest.TestCase):
    """No mutation until authorization and protected store ACL are checked."""

    def test_invalid_paths_fail_before_privileged_token_check(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "_require_privileged_enroller") as auth:
            with mock.patch.object(store, "open_trusted_root") as opener:
                for root, directory in (
                        (r"\\server\share\root", r"C:\Store"),
                        (r"C:\Data", r"\\server\share\store"),
                        (r"C:\Data\..\Other", r"C:\Store")):
                    with self.subTest(root=root, directory=directory):
                        with self.assertRaises(ValueError):
                            store.enroll_root_once_experimental(root, directory)
                auth.assert_not_called()
                opener.assert_not_called()

    def test_unprivileged_token_cannot_open_store_or_root(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "_require_privileged_enroller",
                               side_effect=PermissionError("UAC")) as auth:
            with mock.patch.object(store, "open_trusted_root") as opener:
                with self.assertRaises(PermissionError):
                    store.enroll_root_once_experimental(
                        r"C:\Data", r"C:\Store")
                auth.assert_called_once_with()
                opener.assert_not_called()

    def test_unprotected_store_cannot_observe_root_or_create_record(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "_require_privileged_enroller"):
            with mock.patch.object(store, "open_trusted_root") as opener:
                with mock.patch.object(store, "_assert_protected_acl",
                                       side_effect=PermissionError("ACL")):
                    with mock.patch.object(store, "create_relative_file") as create:
                        opener.return_value.__enter__.return_value = 123
                        with self.assertRaises(PermissionError):
                            store.enroll_root_once_experimental(
                                r"C:\Data", r"C:\Store")
                        opener.assert_called_once_with(
                            r"C:\Store", read_control=True)
                        create.assert_not_called()

    def test_success_creates_once_from_pinned_handle_and_reads_back(self):
        from contextlib import ExitStack
        import nt_enrollment_store_experimental as store
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(store, "_require_privileged_enroller"))
            opener = stack.enter_context(mock.patch.object(store, "open_trusted_root"))
            guard = stack.enter_context(mock.patch.object(store, "_assert_protected_acl"))
            get_identity = stack.enter_context(mock.patch.object(
                store, "directory_identity", return_value=(1, 2, 3)))
            seal = stack.enter_context(mock.patch.object(
                store, "seal_root_identity", return_value=b"sealed"))
            create = stack.enter_context(mock.patch.object(store, "create_relative_file"))
            reader = stack.enter_context(mock.patch.object(
                store, "read_relative_file", return_value=b"sealed"))
            unseal = stack.enter_context(mock.patch.object(
                store, "unseal_root_identity", return_value=(1, 2, 3)))
            opener.return_value.__enter__.side_effect = [11, 22]
            result = store.enroll_root_once_experimental(
                r"C:\Data\Protected", r"C:\Secure\Enroll")
            self.assertEqual(result, (1, 2, 3))
            self.assertEqual(opener.call_args_list, [
                mock.call(r"C:\Secure\Enroll", read_control=True),
                mock.call(r"C:\Data\Protected")])
            guard.assert_called_once_with(11)
            get_identity.assert_called_once_with(22)
            seal.assert_called_once_with(r"C:\Data\Protected", (1, 2, 3))
            name = store.record_name_for_root(r"C:\Data\Protected")
            create.assert_called_once_with(11, name, b"sealed")
            reader.assert_called_once_with(
                11, name, max_bytes=16384, handle_guard=store._assert_protected_acl)
            unseal.assert_called_once_with(r"C:\Data\Protected", b"sealed")

    def test_existing_record_is_not_replaced_or_read(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "_require_privileged_enroller"):
            with mock.patch.object(store, "open_trusted_root") as opener:
                with mock.patch.object(store, "_assert_protected_acl"):
                    with mock.patch.object(store, "directory_identity",
                                           return_value=(1, 2, 3)):
                        with mock.patch.object(store, "seal_root_identity",
                                               return_value=b"sealed"):
                            with mock.patch.object(store, "create_relative_file",
                                                   side_effect=FileExistsError("exists")) as create:
                                with mock.patch.object(store, "read_relative_file") as read:
                                    opener.return_value.__enter__.side_effect = [11, 22]
                                    with self.assertRaises(FileExistsError):
                                        store.enroll_root_once_experimental(
                                            r"C:\Data", r"C:\Secure\Enroll")
                                    create.assert_called_once()
                                    read.assert_not_called()

    def test_wrong_readback_fails_without_reporting_enrollment(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "_require_privileged_enroller"):
            with mock.patch.object(store, "open_trusted_root") as opener:
                with mock.patch.object(store, "_assert_protected_acl"):
                    with mock.patch.object(store, "directory_identity",
                                           return_value=(1, 2, 3)):
                        with mock.patch.object(store, "seal_root_identity",
                                               return_value=b"sealed"):
                            with mock.patch.object(store, "create_relative_file"):
                                with mock.patch.object(store, "read_relative_file",
                                                       return_value=b"other"):
                                    with mock.patch.object(store, "unseal_root_identity",
                                                           return_value=(1, 2, 4)):
                                        opener.return_value.__enter__.side_effect = [11, 22]
                                        with self.assertRaises(OSError):
                                            store.enroll_root_once_experimental(
                                                r"C:\Data", r"C:\Secure\Enroll")

    def test_oversized_dpapi_blob_never_creates_record(self):
        import nt_enrollment_store_experimental as store
        with mock.patch.object(store, "_require_privileged_enroller"):
            with mock.patch.object(store, "open_trusted_root") as opener:
                with mock.patch.object(store, "_assert_protected_acl"):
                    with mock.patch.object(store, "directory_identity",
                                           return_value=(1, 2, 3)):
                        with mock.patch.object(store, "seal_root_identity",
                                               return_value=b"x" * 16385):
                            with mock.patch.object(store, "create_relative_file") as create:
                                opener.return_value.__enter__.side_effect = [11, 22]
                                with self.assertRaises(ValueError):
                                    store.enroll_root_once_experimental(
                                        r"C:\Data", r"C:\Secure\Enroll")
                                create.assert_not_called()


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

    def test_native_create_only_and_dpapi_roundtrip_disposable_store(self):
        """Proves NT create semantics on Windows, NOT the store ACL policy."""
        import nt_enrollment_store_experimental as store
        with tempfile.TemporaryDirectory() as base:
            target = os.path.join(base, "protected")
            registry = os.path.join(base, "enrollment")
            os.mkdir(target)
            os.mkdir(registry)
            with mock.patch.object(store, "_require_privileged_enroller"):
                # The disposable test folder is not a production ACL store.
                # ACL policy itself is covered by independent negative tests.
                with mock.patch.object(store, "_assert_protected_acl"):
                    enrolled = store.enroll_root_once_experimental(
                        target, registry)
                    self.assertEqual(
                        store.load_identity_from_store(target, registry), enrolled)
                    name = store.record_name_for_root(target)
                    record = os.path.join(registry, name)
                    with open(record, "rb") as stream:
                        original = stream.read()
                    with self.assertRaises(OSError):
                        store.enroll_root_once_experimental(target, registry)
                    with open(record, "rb") as stream:
                        self.assertEqual(stream.read(), original)

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

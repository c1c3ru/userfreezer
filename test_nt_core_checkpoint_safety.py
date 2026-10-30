#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core NT checkpoint safety gate regression; no production commit enabled."""
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

import deepfreezer
import nt_commit_checkpoint_experimental as checkpoint
from deepfreezer import DeepFreezer, DeepFreezeError

TARGET = r"C:\TrustedTarget"
OVERLAY = r"C:\TrustedOverlay"
STORE = r"C:\TrustedStore"
IDENTITY = (1, 2, 3)


class NoOrphanMarkerTests(unittest.TestCase):
    def test_absent_ledger_allows_preflight_inspection(self):
        with mock.patch.object(checkpoint, "list_relative_directory",
                               return_value=["other.dpapi"]):
            self.assertTrue(checkpoint.assert_no_orphan_nt_commit_markers(
                17, TARGET))

    def test_orphan_markers_never_authorize_new_intent(self):
        prefix = checkpoint._ledger_prefix(TARGET)
        for name in (prefix + ".00000.started", prefix + ".00000.done",
                     prefix + ".complete", prefix + ".review",
                     prefix + ".resolution"):
            with self.subTest(name=name):
                with mock.patch.object(checkpoint, "list_relative_directory",
                                       return_value=["other.dpapi", name]):
                    with self.assertRaises(checkpoint.PendingNTCommitError):
                        checkpoint.assert_no_orphan_nt_commit_markers(
                            17, TARGET)

    def test_intent_with_progress_is_not_misclassified_as_orphan(self):
        prefix = checkpoint._ledger_prefix(TARGET)
        with mock.patch.object(checkpoint, "list_relative_directory",
                               return_value=[prefix + ".intent",
                                             prefix + ".00000.started"]):
            self.assertTrue(checkpoint.assert_no_orphan_nt_commit_markers(
                17, TARGET))

    def test_enumeration_failure_refuses_silent_clean_status(self):
        with mock.patch.object(checkpoint, "list_relative_directory",
                               side_effect=OSError("ACL or NT error")):
            with self.assertRaises(OSError):
                checkpoint.assert_no_orphan_nt_commit_markers(17, TARGET)


class CoreNativeGateTests(unittest.TestCase):
    def _gate(self, stack, snapshot=None, check_error=None):
        from nt_enrollment_store_experimental import _assert_protected_acl
        fake = DeepFreezer.__new__(DeepFreezer)
        fake.target = TARGET
        fake.overlay = OVERLAY
        fake.ops = {"safe.txt": (1, "W", 0)}
        stack.enter_context(mock.patch.object(
            DeepFreezer, "_require_frozen"))
        stack.enter_context(mock.patch.object(deepfreezer.os, "name", "nt"))
        stack.enter_context(mock.patch(
            "nt_enrollment_store_experimental.load_identity_from_store",
            return_value=IDENTITY))
        opener = stack.enter_context(mock.patch(
            "win32_relative_directory.open_trusted_root"))
        opener.return_value.__enter__.return_value = 33
        stack.enter_context(mock.patch(
            "win32_relative_directory.directory_identity",
            return_value=IDENTITY))
        stack.enter_context(mock.patch(
            "nt_enrollment_store_experimental._assert_protected_acl"))
        listing = stack.enter_context(mock.patch(
            "nt_commit_checkpoint_experimental.assert_no_orphan_nt_commit_markers",
            side_effect=check_error))
        ledger = stack.enter_context(mock.patch(
            "nt_commit_checkpoint_experimental.inspect_nt_commit_checkpoint",
            return_value=snapshot or
            {"state": "absent", "completed": 0, "total": 0}))
        preview = stack.enter_context(mock.patch.object(
            DeepFreezer, "preview_windows_native_commit",
            return_value=[{"operation": "W", "path": "safe.txt",
                           "bytes": 3, "sha256": "a" * 64}]))
        return fake, listing, ledger, preview

    def test_checkpoint_blocks_preview_and_does_not_mutate(self):
        state = {"state": "uncertain", "completed": 0, "total": 2,
                 "uncertain_index": 0}
        with ExitStack() as stack:
            fake, listing, ledger, preview = self._gate(stack, snapshot=state)
            report = fake.inspect_windows_native_commit_safety(STORE)
            self.assertEqual(report["status"], "checkpoint_blocks_new_commit")
            self.assertEqual(report["checkpoint_state"], "uncertain")
            self.assertFalse(report["production_commit_authorized"])
            preview.assert_not_called()
            listing.assert_called_once()
            ledger.assert_called_once()

    def test_successful_preflight_still_does_not_authorize_commit(self):
        with ExitStack() as stack:
            fake, _listing, ledger, preview = self._gate(stack)
            report = fake.inspect_windows_native_commit_safety(STORE)
            self.assertEqual(report["status"], "experimental_preflight_only")
            self.assertEqual(report["operations"], 1)
            self.assertEqual(report["write_bytes"], 3)
            self.assertFalse(report["production_commit_authorized"])
            self.assertTrue(report["read_only"])
            self.assertEqual(ledger.call_count, 2)
            preview.assert_called_once_with(STORE)

    def test_orphan_blocks_before_preview_or_ledger_read(self):
        with ExitStack() as stack:
            fake, listing, ledger, preview = self._gate(
                stack, check_error=checkpoint.PendingNTCommitError("orphan"))
            with self.assertRaises(checkpoint.PendingNTCommitError):
                fake.inspect_windows_native_commit_safety(STORE)
            listing.assert_called_once()
            preview.assert_not_called()
            ledger.assert_not_called()

    def test_root_identity_mismatch_is_fail_closed(self):
        with ExitStack() as stack:
            fake, listing, ledger, preview = self._gate(stack)
            stack.enter_context(mock.patch(
                "win32_relative_directory.directory_identity",
                return_value=(1, 2, 4)))
            with self.assertRaises(DeepFreezeError):
                fake.inspect_windows_native_commit_safety(STORE)
            listing.assert_not_called()
            ledger.assert_not_called()
            preview.assert_not_called()

    def test_checkpoint_state_change_during_preview_aborts(self):
        with ExitStack() as stack:
            fake, _listing, ledger, preview = self._gate(stack)
            ledger.side_effect = [
                {"state": "absent", "completed": 0, "total": 0},
                {"state": "incomplete", "completed": 0, "total": 1},
            ]
            with self.assertRaises(DeepFreezeError):
                fake.inspect_windows_native_commit_safety(STORE)
            preview.assert_called_once()

    def test_linux_denies_use(self):
        if os.name == "nt":
            self.skipTest("Linux-only negative test")
        with tempfile.TemporaryDirectory() as root:
            with DeepFreezer(root) as freezer:
                freezer.freeze()
                with self.assertRaises(DeepFreezeError):
                    freezer.inspect_windows_native_commit_safety(STORE)

    def test_production_commit_gate_is_not_removed(self):
        import inspect
        source = inspect.getsource(DeepFreezer._apply_commit)
        self.assertIn('if os.name == "nt" and self.ops:', source)


@unittest.skipUnless(os.name == "nt", "real Windows native handles only")
class WindowsCoreNativeGateTests(unittest.TestCase):
    def test_real_frozen_core_can_preflight_without_mutating_target(self):
        from win32_relative_directory import (
            open_trusted_root, directory_identity,
        )
        import nt_enrollment_store_experimental as enrollment
        import nt_overlay_journal_experimental as journal
        import nt_overlay_payload_experimental as payload
        import nt_commit_checkpoint_experimental as ledger
        import ntpath

        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "target")
            store = os.path.join(base, "store")
            os.mkdir(root)
            os.mkdir(store)
            with DeepFreezer(root) as freezer:
                freezer.freeze()
                freezer.write("new.txt", b"DATA")
                with open_trusted_root(root) as h:
                    target_id = directory_identity(h)
                with open_trusted_root(freezer.overlay) as h:
                    overlay_id = directory_identity(h)

                def identity(path, _store):
                    return (target_id if ntpath.normcase(path) ==
                            ntpath.normcase(root) else overlay_id)
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(
                        enrollment, "load_identity_from_store",
                        side_effect=identity))
                    for module in (enrollment, journal, payload, ledger):
                        stack.enter_context(mock.patch.object(
                            module, "_assert_protected_acl"))
                    stack.enter_context(mock.patch.object(
                        journal, "load_identity_from_store",
                        side_effect=identity))
                    report = freezer.inspect_windows_native_commit_safety(store)
                self.assertEqual(report["status"], "experimental_preflight_only")
                self.assertEqual(report["write_bytes"], 4)
                self.assertFalse(report["production_commit_authorized"])
                self.assertFalse(os.path.exists(os.path.join(root, "new.txt")))

    def test_real_nt_store_orphan_progress_is_rejected(self):
        from win32_relative_directory import open_trusted_root, create_relative_file
        with tempfile.TemporaryDirectory() as store:
            with open_trusted_root(store) as handle:
                create_relative_file(
                    handle, checkpoint._ledger_prefix(TARGET) + ".00000.started",
                    b"orphan")
                with self.assertRaises(checkpoint.PendingNTCommitError):
                    checkpoint.assert_no_orphan_nt_commit_markers(handle, TARGET)


if __name__ == "__main__":
    unittest.main()

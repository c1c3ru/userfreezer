#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only NT commit preview API regression tests (#63)."""
import hashlib
import ntpath
import os
import tempfile
import unittest
from unittest import mock

from deepfreezer import DeepFreezer, DeepFreezeError


class PreviewAvailabilityTests(unittest.TestCase):
    def test_linux_refuses_without_touching_target(self):
        if os.name == "nt":
            self.skipTest("Linux-only negative test")
        with tempfile.TemporaryDirectory() as target:
            with DeepFreezer(target) as df:
                df.freeze()
                df.write("new.txt", b"PAYLOAD")
                with self.assertRaises(DeepFreezeError):
                    df.preview_windows_native_commit(r"C:\Store")
                self.assertFalse(os.path.lexists(
                    os.path.join(target, "new.txt")))
                self.assertTrue(df.frozen)


@unittest.skipUnless(os.name == "nt", "native NTFS Windows")
class WindowsCorePreviewTests(unittest.TestCase):
    def test_preview_real_frozen_core_replays_no_mutations(self):
        import nt_enrollment_store_experimental as store
        import nt_overlay_journal_experimental as journal
        import nt_overlay_payload_experimental as payload
        from win32_relative_directory import open_trusted_root, directory_identity

        with tempfile.TemporaryDirectory() as base:
            target = os.path.join(base, "target")
            os.mkdir(target)
            with DeepFreezer(target) as df:
                df.freeze()
                df.write("new.txt", b"PREVIEW-ONLY")
                with open_trusted_root(target) as pinned:
                    target_id = directory_identity(pinned)
                with open_trusted_root(df.overlay) as pinned:
                    overlay_id = directory_identity(pinned)

                def enrolled(path, _store):
                    if ntpath.normcase(path) == ntpath.normcase(target):
                        return target_id
                    if ntpath.normcase(path) == ntpath.normcase(df.overlay):
                        return overlay_id
                    raise AssertionError("unexpected root")

                with mock.patch.object(
                        store, "load_identity_from_store",
                        side_effect=enrolled):
                    with mock.patch.object(
                            journal, "load_identity_from_store",
                            side_effect=enrolled):
                        with mock.patch.object(journal, "_assert_protected_acl"):
                            with mock.patch.object(payload, "_assert_protected_acl"):
                                report = df.preview_windows_native_commit(
                                    r"C:\TestStore")
                self.assertEqual(report, [{
                    "operation": "W", "path": "new.txt",
                    "bytes": len(b"PREVIEW-ONLY"),
                    "sha256": hashlib.sha256(b"PREVIEW-ONLY").hexdigest()}])
                self.assertFalse(os.path.lexists(
                    os.path.join(target, "new.txt")))
                self.assertTrue(df.frozen)
                with self.assertRaises(DeepFreezeError):
                    df.thaw(commit=True)

    def test_target_replacement_before_preview_refuses(self):
        import nt_enrollment_store_experimental as store
        from win32_relative_directory import open_trusted_root, directory_identity
        with tempfile.TemporaryDirectory() as base:
            target = os.path.join(base, "target")
            moved = os.path.join(base, "moved")
            decoy = os.path.join(base, "decoy")
            os.mkdir(target)
            os.mkdir(decoy)
            with DeepFreezer(target) as df:
                df.freeze()
                df.write("new.txt", b"SHOULD-NOT-WRITE")
                with open_trusted_root(target) as pinned:
                    enrolled_id = directory_identity(pinned)
                os.rename(target, moved)
                os.rename(decoy, target)
                with mock.patch.object(
                        store, "load_identity_from_store",
                        return_value=enrolled_id):
                    with self.assertRaises(DeepFreezeError):
                        df.preview_windows_native_commit(r"C:\TestStore")
                self.assertFalse(os.path.lexists(
                    os.path.join(target, "new.txt")))


if __name__ == "__main__":
    unittest.main()

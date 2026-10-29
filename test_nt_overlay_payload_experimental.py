#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NT overlay handle reader hardening tests for issue #63."""
import os
import tempfile
import unittest
from unittest import mock

import nt_overlay_payload_experimental as overlay
from nt_commit_bridge_experimental import apply_pinned_overlay_plan_experimental
from win32_relative_directory import open_trusted_root, directory_identity


class OverlayPathValidationTests(unittest.TestCase):
    def test_only_journal_subtrees_and_canonical_components(self):
        self.assertEqual(overlay._parse_overlay_source("payloads/0000000000000001"),
                         ["payloads", "0000000000000001"])
        self.assertEqual(overlay._parse_overlay_source("files/a/b.txt"),
                         ["files", "a", "b.txt"])
        for source in (
                "", "payloads", "payloads/x", "payloads/1/extra",
                "payloads/١", "files", "files/../outside",
                "files/a//x", "files/a\\x", "files/CON", "/files/x",
                "files/a:ads", "files/dir/junction/../../x",
                "other/a", "payloads/1" * 200):
            with self.subTest(source=source), self.assertRaises(ValueError):
                overlay._parse_overlay_source(source)

    def test_mismatch_refuses_before_any_acl_or_payload_reads(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            opener = stack.enter_context(
                mock.patch.object(overlay, "open_trusted_root"))
            identity = stack.enter_context(
                mock.patch.object(overlay, "directory_identity",
                                  return_value=(1, 2, 3)))
            guard = stack.enter_context(
                mock.patch.object(overlay, "_assert_protected_acl"))
            read = stack.enter_context(
                mock.patch.object(overlay, "read_relative_file"))
            opener.return_value.__enter__.return_value = 77
            with self.assertRaises(OSError):
                with overlay.pinned_overlay_payload_loader(
                        r"C:\Overlay", (1, 2, 4)):
                    pass
            identity.assert_called_once_with(77)
            guard.assert_not_called()
            read.assert_not_called()

    def test_root_acl_denied_refuses_before_payload_reads(self):
        with mock.patch.object(overlay, "open_trusted_root") as opener:
            with mock.patch.object(overlay, "directory_identity",
                                   return_value=(1, 2, 3)):
                with mock.patch.object(overlay, "_assert_protected_acl",
                                       side_effect=PermissionError("ACL denied")):
                    with mock.patch.object(overlay, "read_relative_file") as reader:
                        opener.return_value.__enter__.return_value = 77
                        with self.assertRaises(PermissionError):
                            with overlay.pinned_overlay_payload_loader(
                                    r"C:\Overlay", (1, 2, 3)):
                                pass
                        reader.assert_not_called()

    def test_invalid_limits_and_source_never_read(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            opener = stack.enter_context(
                mock.patch.object(overlay, "open_trusted_root"))
            stack.enter_context(mock.patch.object(
                overlay, "directory_identity", return_value=(1, 2, 3)))
            stack.enter_context(mock.patch.object(
                overlay, "_assert_protected_acl"))
            reader = stack.enter_context(
                mock.patch.object(overlay, "read_relative_file"))
            opener.return_value.__enter__.return_value = 77
            with overlay.pinned_overlay_payload_loader(
                    r"C:\Overlay", (1, 2, 3)) as load:
                for source in ("../../secret", "payloads/1/child"):
                    with self.assertRaises(ValueError):
                        load(source, 16)
                for limit in (0, -1, True, 16777217):
                    with self.assertRaises(ValueError):
                        load("payloads/1", limit)
            reader.assert_not_called()

    def test_pinned_loader_is_the_only_backend_path(self):
        import nt_commit_bridge_experimental as bridge
        entries = [(["ok"], "W", 0, "payloads/0001")]
        with mock.patch.object(bridge, "prepare_native_plan",
                               return_value=[("W", "ok", b"safe")]) as prepare:
            with mock.patch("nt_overlay_payload_experimental.pinned_overlay_payload_loader") as pinned:
                with mock.patch(
                        "nt_enrollment_store_experimental.apply_stored_plan_experimental",
                        return_value=["ok"]) as apply:
                    pinned.return_value.__enter__.return_value = lambda s, n: b"safe"
                    self.assertEqual(
                        apply_pinned_overlay_plan_experimental(
                            r"C:\Root", entries, r"C:\Store",
                            r"C:\Overlay", (1, 2, 3)), ["ok"])
                    prepare.assert_called_once()
                    apply.assert_called_once_with(
                        r"C:\Root", [("W", "ok", b"safe")],
                        r"C:\Store")

    def test_bad_plan_never_reaches_backend_or_payload(self):
        entries = [
            (["ok"], "W", 0, "payloads/0001"),
            (["..", "escape"], "D", 1, None),
        ]
        with mock.patch("nt_overlay_payload_experimental.pinned_overlay_payload_loader") as pinned:
            with mock.patch(
                    "nt_enrollment_store_experimental.apply_stored_plan_experimental") as apply:
                load = mock.Mock(side_effect=AssertionError("unexpected read"))
                pinned.return_value.__enter__.return_value = load
                with self.assertRaises(ValueError):
                    apply_pinned_overlay_plan_experimental(
                        r"C:\Root", entries, r"C:\Store",
                        r"C:\Overlay", (1, 2, 3))
                load.assert_not_called()
                apply.assert_not_called()


@unittest.skipUnless(os.name == "nt", "requires NTFS on Windows")
class WindowsPinnedOverlayTests(unittest.TestCase):
    def test_immutable_payload_and_legacy_file_from_root_handle(self):
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, "payloads"))
            os.makedirs(os.path.join(root, "files", "sub"))
            payload = b"payload" * 3000
            with open(os.path.join(root, "payloads", "0001"), "wb") as writer:
                writer.write(payload)
            with open(os.path.join(root, "files", "sub", "ok.txt"), "wb") as writer:
                writer.write(b"legacy")
            with open_trusted_root(root) as handle:
                ident = directory_identity(handle)
            with mock.patch.object(overlay, "_assert_protected_acl"):
                with overlay.pinned_overlay_payload_loader(root, ident) as load:
                    self.assertEqual(load("payloads/0001", len(payload)), payload)
                    self.assertEqual(load("files/sub/ok.txt", 20), b"legacy")
                    with self.assertRaises(ValueError):
                        load("payloads/0001", 10)

    def test_swapped_root_before_open_cannot_read_decoy(self):
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "overlay")
            moved = os.path.join(base, "original")
            decoy = os.path.join(base, "decoy")
            os.mkdir(root)
            os.mkdir(decoy)
            with open_trusted_root(root) as handle:
                expected = directory_identity(handle)
            os.rename(root, moved)
            os.rename(decoy, root)
            with mock.patch.object(overlay, "_assert_protected_acl"):
                with self.assertRaises(OSError):
                    with overlay.pinned_overlay_payload_loader(root, expected):
                        pass
            self.assertTrue(os.path.isdir(moved))

    def test_nested_junction_refuses_to_read_outside(self):
        import subprocess
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "overlay")
            outside = os.path.join(base, "outside")
            os.mkdir(root)
            os.mkdir(outside)
            link = os.path.join(root, "payloads")
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", link, outside],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                self.skipTest("junction unavailable: %r" % result.stderr)
            try:
                with open_trusted_root(root) as handle:
                    expected = directory_identity(handle)
                with mock.patch.object(overlay, "_assert_protected_acl"):
                    with overlay.pinned_overlay_payload_loader(root, expected) as load:
                        with self.assertRaises(OSError):
                            load("payloads/0001", 20)
            finally:
                if os.path.lexists(link):
                    os.rmdir(link)


if __name__ == "__main__":
    unittest.main()

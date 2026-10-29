#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prototipo de plano NT em Windows moderno; Win7 SP1 ainda manual."""
import os
import subprocess
import sys
import tempfile
import unittest

from nt_commit_experimental import (PartialCommitError, _validate_plan,
                                    apply_plan_experimental)


@unittest.skipUnless(os.name == "nt", "somente NTFS Windows")
class ExperimentalPlanTests(unittest.TestCase):
    def test_full_plan_write_mkdir_replace_unlink_and_recursive_delete(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "old.txt"), "wb") as f:
                f.write(b"old")
            with open(os.path.join(root, "delete.txt"), "wb") as f:
                f.write(b"delete")
            os.makedirs(os.path.join(root, "obsolete", "nested"))
            with open(os.path.join(root, "obsolete", "nested", "x.txt"), "wb") as f:
                f.write(b"obsolete")
            ops = [
                ("W", "old.txt", b"updated"),
                ("M", "new/nested", None),
                ("W", "new/nested/file.txt", b"hello"),
                ("F", "delete.txt", None),
                ("D", "obsolete", None),
            ]
            result = apply_plan_experimental(root, ops)
            self.assertEqual(result, [entry[1] for entry in ops])
            with open(os.path.join(root, "old.txt"), "rb") as f:
                self.assertEqual(f.read(), b"updated")
            with open(os.path.join(root, "new", "nested", "file.txt"), "rb") as f:
                self.assertEqual(f.read(), b"hello")
            self.assertFalse(os.path.exists(os.path.join(root, "delete.txt")))
            self.assertFalse(os.path.exists(os.path.join(root, "obsolete")))

    def test_swap_after_root_pin_cannot_write_to_outside_junction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "root")
            target = os.path.join(root, "target")
            moved = os.path.join(root, "renamed")
            outside = os.path.join(temp, "external")
            os.makedirs(target)
            os.mkdir(outside)
            with open(os.path.join(outside, "same.txt"), "wb") as f:
                f.write(b"external-preserved")
            def inject_swap():
                cp = subprocess.run(
                    [sys.executable, "-c",
                     "import os,sys; os.rename(sys.argv[1], sys.argv[2])",
                     target, moved], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(cp.returncode, 0, cp.stderr)
                link = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", target, outside],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(link.returncode, 0, link.stderr)
            try:
                apply_plan_experimental(target, [
                    ("M", "new/deep", None),
                    ("W", "new/deep/hello.txt", b"inside"),
                    ("W", "same.txt", b"must-not-hit-external"),
                ], on_root_pinned=inject_swap)
                with open(os.path.join(moved, "same.txt"), "rb") as f:
                    self.assertEqual(f.read(), b"must-not-hit-external")
                with open(os.path.join(outside, "same.txt"), "rb") as f:
                    self.assertEqual(f.read(), b"external-preserved")
                self.assertFalse(os.path.exists(
                    os.path.join(outside, "new", "deep", "hello.txt")))
            finally:
                if os.path.lexists(target):
                    os.rmdir(target)

    def test_error_reports_partial_completion_without_rollback_claim(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PartialCommitError) as cm:
                apply_plan_experimental(root, [
                    ("W", "saved.txt", b"persisted"),
                    ("F", "missing.txt", None),
                ])
            self.assertEqual(cm.exception.completed, ("saved.txt",))
            with open(os.path.join(root, "saved.txt"), "rb") as f:
                self.assertEqual(f.read(), b"persisted")

    def test_paths_and_plans_reject_traversal_before_mutations(self):
        for p in ("../escape", "/abs", "x//y", "x/./y",
                  r"x\\y", "bad:ads"):
            with self.subTest(path=p), self.assertRaises(ValueError):
                _validate_plan([("W", p, b"test")])
        with self.assertRaises(ValueError):
            _validate_plan([("W", "x.txt", "not-bytes")])
        with self.assertRaises(ValueError):
            _validate_plan([("F", "x.txt", b"garbage")])


class PlanPreflightRegressionTests(unittest.TestCase):
    """Invalid plans must be rejected before any native operation begins."""

    def test_rejects_oversized_plan(self):
        with self.assertRaises(ValueError):
            _validate_plan([("M", "safe", None)] * 10001)

    def test_rejects_bad_trailing_entry(self):
        with self.assertRaises(ValueError):
            _validate_plan([
                ("W", "first.txt", b"payload"),
                ("M", "nested", None),
                ("F", "../outside.txt", None),
            ])


    def test_parent_open_permission_error_does_not_attempt_mkdir(self):
        from unittest import mock
        import nt_commit_experimental as module
        denied = PermissionError("access denied")
        denied.winerror = 5
        with mock.patch.object(module, "os") as fake_os:
            fake_os.name = "nt"
            with mock.patch.object(module, "open_trusted_root") as root:
                with mock.patch.object(module, "open_relative_directory", side_effect=denied):
                    with mock.patch.object(module, "create_relative_directory") as mkdir:
                        root.return_value.__enter__.return_value = object()
                        with self.assertRaises(PartialCommitError) as caught:
                            module.apply_plan_experimental(
                                "C:/trusted", [("W", "parent/file.txt", b"x")])
                        self.assertEqual(caught.exception.completed, ())
                        mkdir.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "requires Windows native backend")
    def test_bad_trailing_entry_cannot_mutate_existing_root(self):
        with tempfile.TemporaryDirectory() as root:
            sentinel = os.path.join(root, "sentinel.txt")
            with open(sentinel, "wb") as handle:
                handle.write(b"unchanged")
            with self.assertRaises(ValueError):
                apply_plan_experimental(root, [
                    ("W", "sentinel.txt", b"should-not-be-written"),
                    ("M", "new-directory", None),
                    ("F", "../escape.txt", None),
                ])
            with open(sentinel, "rb") as handle:
                self.assertEqual(handle.read(), b"unchanged")
            self.assertFalse(os.path.lexists(os.path.join(root, "new-directory")))


if __name__ == "__main__":
    unittest.main()

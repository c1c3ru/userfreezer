#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real subprocess termination + independent checkpoint inspection (#63).

CI Windows is modern, not Windows 7 SP1; a VM reboot is a separate gate.
"""
import json
import ntpath
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import nt_commit_checkpoint_experimental as checkpoint
import nt_commit_forensics_experimental as forensic


class ForensicReportTests(unittest.TestCase):
    def test_unenrolled_root_is_rejected_before_reading_ledger(self):
        with mock.patch.object(forensic, "load_identity_from_store",
                               return_value=(1, 2, 3)):
            with mock.patch.object(forensic, "open_trusted_root") as opener:
                with mock.patch.object(forensic, "directory_identity",
                                       return_value=(1, 2, 4)):
                    with mock.patch.object(forensic, "_inspect_open_store") as read:
                        opener.return_value.__enter__.return_value = 41
                        with self.assertRaises(OSError):
                            forensic.inspect_nt_commit_for_operator(
                                r"C:\Test\Target", r"C:\Test\Store")
                        read.assert_not_called()

    def test_report_always_refuses_automatic_replay(self):
        with mock.patch.object(forensic, "load_identity_from_store",
                               return_value=(1, 2, 3)):
            with mock.patch.object(forensic, "open_trusted_root") as opener:
                with mock.patch.object(forensic, "directory_identity",
                                       return_value=(1, 2, 3)):
                    with mock.patch.object(forensic, "_assert_protected_acl"):
                        with mock.patch.object(forensic, "_inspect_open_store",
                                               return_value={
                                                   "state": "absent",
                                                   "completed": 0, "total": 0}):
                            opener.return_value.__enter__.return_value = 41
                            report = forensic.inspect_nt_commit_for_operator(
                                r"C:\Test\Target", r"C:\Test\Store")
                            self.assertFalse(report["replay_allowed"])
                            self.assertEqual(report["state"], "absent")


class AdminReviewTests(unittest.TestCase):
    REPORT = {"state": "uncertain", "intent_sha256": "a" * 64,
              "completed": 0, "total": 2}

    def test_denied_admin_token_cannot_touch_store(self):
        with mock.patch.object(
                forensic, "_require_privileged_enroller",
                side_effect=PermissionError("not elevated")):
            with mock.patch.object(forensic, "inspect_nt_commit_for_operator") as inspect:
                with mock.patch.object(forensic, "open_trusted_root") as opener:
                    with self.assertRaises(PermissionError):
                        forensic.record_nt_commit_review_experimental(
                            r"C:\Test\Target", r"C:\Test\Store",
                            "CASE_2026_63", "f" * 64)
                    inspect.assert_not_called()
                    opener.assert_not_called()

    def test_invalid_case_or_evidence_refused_without_admin_lookup(self):
        with mock.patch.object(forensic, "_require_privileged_enroller") as auth:
            for ticket, digest in (
                    ("../escape", "a" * 64),
                    ("CASE_2026_63", "not-a-digest"),
                    ("", "a" * 64)):
                with self.subTest(ticket=ticket, digest=digest):
                    with self.assertRaises(ValueError):
                        forensic.record_nt_commit_review_experimental(
                            r"C:\Test\Target", r"C:\Test\Store",
                            ticket, digest)
            auth.assert_not_called()

    def test_review_created_once_and_does_not_unlock_or_delete(self):
        with mock.patch.object(forensic, "_require_privileged_enroller"):
            with mock.patch.object(forensic, "inspect_nt_commit_for_operator",
                                   return_value=self.REPORT):
                with mock.patch.object(forensic, "open_trusted_root") as opener:
                    with mock.patch.object(forensic, "_assert_protected_acl"):
                        with mock.patch.object(forensic, "_inspect_open_store",
                                               return_value=self.REPORT):
                            with mock.patch.object(forensic, "_write_verified") as writer:
                                opener.return_value.__enter__.return_value = 7
                                result = forensic.record_nt_commit_review_experimental(
                                    r"C:\Test\Target", r"C:\Test\Store",
                                    "INCIDENT_63", "f" * 64)
                                self.assertEqual(
                                    result["action"], "review-recorded-no-retry-no-unlock")
                                self.assertEqual(result["observed_state"], "uncertain")
                                self.assertEqual(writer.call_count, 1)
                                self.assertTrue(
                                    writer.call_args[0][1].endswith(".ntcommit.review"))
                                self.assertIn(b'"case_id":"INCIDENT_63"',
                                              writer.call_args[0][2])
                                writer.side_effect = FileExistsError("already reviewed")
                                with self.assertRaises(FileExistsError):
                                    forensic.record_nt_commit_review_experimental(
                                        r"C:\Test\Target", r"C:\Test\Store",
                                        "INCIDENT_63", "f" * 64)
                                self.assertEqual(writer.call_count, 2)

    def test_change_during_review_refuses_write(self):
        with mock.patch.object(forensic, "_require_privileged_enroller"):
            with mock.patch.object(forensic, "inspect_nt_commit_for_operator",
                                   return_value=self.REPORT):
                with mock.patch.object(forensic, "open_trusted_root") as opener:
                    with mock.patch.object(forensic, "_assert_protected_acl"):
                        with mock.patch.object(forensic, "_inspect_open_store",
                                               return_value=dict(
                                                   self.REPORT, intent_sha256="b" * 64)):
                            with mock.patch.object(forensic, "_write_verified") as writer:
                                opener.return_value.__enter__.return_value = 7
                                with self.assertRaises(OSError):
                                    forensic.record_nt_commit_review_experimental(
                                        r"C:\Test\Target", r"C:\Test\Store",
                                        "INCIDENT_63", "f" * 64)
                                writer.assert_not_called()


@unittest.skipUnless(os.name == "nt", "requires real Windows subprocess and NTFS")
class WindowsTerminatedWorkerTests(unittest.TestCase):
    WORKER = r"""
import os, sys, time, ntpath
from unittest import mock
import nt_commit_checkpoint_experimental as checkpoint
from win32_relative_directory import open_trusted_root, directory_identity
root, overlay, store = sys.argv[1:]
with open_trusted_root(root) as fd:
    root_id = directory_identity(fd)
with open_trusted_root(overlay) as fd:
    overlay_id = directory_identity(fd)
def identity(path, _store):
    return overlay_id if ntpath.normcase(path) == ntpath.normcase(overlay) else root_id
def post_write(index, name):
    if index == 0:
        print("AFTER_NATIVE_WRITE", flush=True)
        time.sleep(90)  # parent MUST TerminateProcess before DONE(0)
with mock.patch.object(checkpoint, "load_identity_from_store", side_effect=identity):
    with mock.patch.object(checkpoint, "_assert_protected_acl"):
        checkpoint.apply_checkpointed_plan_experimental(
            root, overlay, store,
            [("W", "first.txt", b"FIRST"), ("W", "second.txt", b"SECOND")],
            after_operation=post_write)
"""

    READER = r"""
import sys, json
from unittest import mock
import nt_commit_checkpoint_experimental as checkpoint
root, store = sys.argv[1:]
with mock.patch.object(checkpoint, "_assert_protected_acl"):
    print(json.dumps(checkpoint.inspect_nt_commit_checkpoint(root, store)))
"""

    def test_terminate_process_between_native_write_and_done_then_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            root, overlay, store = [
                os.path.join(temp, name)
                for name in ("target", "overlay", "store")]
            for path in (root, overlay, store):
                os.mkdir(path)
            command = [sys.executable, "-u", "-c", self.WORKER,
                       root, overlay, store]
            proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    universal_newlines=True)
            try:
                try:
                    stdout, stderr = proc.communicate(timeout=15)
                    self.fail("worker exited before injected kill: rc=%r\n%s\n%s" %
                              (proc.returncode, stdout, stderr))
                except subprocess.TimeoutExpired:
                    proc.kill()  # actual forced Windows process termination
                    stdout, stderr = proc.communicate(timeout=20)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate(timeout=20)
            self.assertIn("AFTER_NATIVE_WRITE", stdout, stderr)
            self.assertNotEqual(proc.returncode, 0)
            with open(os.path.join(root, "first.txt"), "rb") as stream:
                self.assertEqual(stream.read(), b"FIRST")
            self.assertFalse(os.path.exists(os.path.join(root, "second.txt")))

            # Separate Python process, fresh NT handles, after worker death.
            result = subprocess.run(
                [sys.executable, "-u", "-c", self.READER, root, store],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "uncertain")
            self.assertEqual(report["uncertain_index"], 0)
            self.assertEqual(report["completed"], 0)

            # Replaying even a shortened plan must not overwrite the intent.
            from win32_relative_directory import (
                directory_identity, open_trusted_root,
            )
            with open_trusted_root(root) as fd:
                root_id = directory_identity(fd)
            with open_trusted_root(overlay) as fd:
                overlay_id = directory_identity(fd)
            def identity(path, _store):
                return (overlay_id if ntpath.normcase(path) ==
                        ntpath.normcase(overlay) else root_id)
            with mock.patch.object(checkpoint, "load_identity_from_store",
                                   side_effect=identity):
                with mock.patch.object(checkpoint, "_assert_protected_acl"):
                    with self.assertRaises(checkpoint.PendingNTCommitError):
                        checkpoint.apply_checkpointed_plan_experimental(
                            root, overlay, store,
                            [("W", "second.txt", b"UNSAFE-RETRY")])
            self.assertFalse(os.path.exists(os.path.join(root, "second.txt")))


if __name__ == "__main__":
    unittest.main()

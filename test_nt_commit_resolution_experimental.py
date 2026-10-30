#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed NT incident resolution regression tests (#63)."""
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

import nt_commit_resolution_experimental as resolution

ROOT = r"C:\Protected"
STORE = r"C:\Enrollment"
INTENT = "a" * 64
REPORT = {"state": "uncertain", "completed": 0, "total": 2,
          "uncertain_index": 0, "intent_sha256": INTENT}
CASE = "INCIDENT_2026_63"
APPROVAL = "REVIEWER_2026_2"
EVIDENCE = "b" * 64
REVIEW = {
    "v": 1, "root": r"c:\protected", "intent_sha256": INTENT,
    "observed_state": "uncertain", "case_id": CASE,
    "evidence_sha256": "c" * 64,
    "time_utc": "2026-10-30T10:00:00+00:00",
    "action": "review-recorded-no-retry-no-unlock",
}
REVIEW_BYTES = (json.dumps(REVIEW, sort_keys=True,
                           separators=(",", ":")) + "\n").encode("ascii")


class AdministrativeResolutionTests(unittest.TestCase):
    def _setup(self, stack, report=REPORT, review=REVIEW_BYTES):
        stack.enter_context(mock.patch.object(
            resolution, "_require_privileged_enroller"))
        stack.enter_context(mock.patch.object(
            resolution, "inspect_nt_commit_for_operator",
            return_value=report))
        opener = stack.enter_context(mock.patch.object(
            resolution, "open_trusted_root"))
        opener.return_value.__enter__.return_value = 77
        stack.enter_context(mock.patch.object(resolution, "_assert_protected_acl"))
        stack.enter_context(mock.patch.object(
            resolution, "_inspect_open_store", return_value=report))
        read = stack.enter_context(mock.patch.object(
            resolution, "_read_optional", return_value=review))
        writer = stack.enter_context(mock.patch.object(resolution, "_write_verified"))
        return read, writer

    def _record(self):
        return resolution.record_nt_incident_resolution_experimental(
            ROOT, STORE, CASE, APPROVAL, EVIDENCE,
            "restored_from_verified_snapshot")

    def test_resolution_requires_admin_token(self):
        with mock.patch.object(
                resolution, "_require_privileged_enroller",
                side_effect=PermissionError("UAC denied")):
            with mock.patch.object(
                    resolution, "inspect_nt_commit_for_operator") as inspect:
                with self.assertRaises(PermissionError):
                    self._record()
                inspect.assert_not_called()

    def test_malformed_approval_or_hash_cannot_touch_store(self):
        with mock.patch.object(
                resolution, "_require_privileged_enroller") as auth:
            for approval, digest, decision in (
                    ("../escape", EVIDENCE, "manually_reconciled"),
                    (APPROVAL, "invalid", "manually_reconciled"),
                    (APPROVAL, EVIDENCE, "retry_anyway")):
                with self.subTest(approval=approval, decision=decision):
                    with self.assertRaises(ValueError):
                        resolution.record_nt_incident_resolution_experimental(
                            ROOT, STORE, CASE, approval, digest, decision)
            auth.assert_not_called()

    def test_absent_or_completed_record_is_not_closable(self):
        for state in ("absent", "complete"):
            with self.subTest(state=state), ExitStack() as stack:
                self._setup(stack, report=dict(REPORT, state=state))
                with self.assertRaises(ValueError):
                    self._record()

    def test_missing_review_fails_before_any_write(self):
        with ExitStack() as stack:
            _read, writer = self._setup(stack, review=None)
            with self.assertRaisesRegex(ValueError, "REVIEW"):
                self._record()
            writer.assert_not_called()

    def test_review_must_match_same_case_and_intent(self):
        for key, value in (
                ("case_id", "DIFFERENT_CASE"),
                ("intent_sha256", "d" * 64),
                ("observed_state", "complete"),
                ("action", "authorize-retry")):
            with self.subTest(key=key), ExitStack() as stack:
                bad = dict(REVIEW, **{key: value})
                data = (json.dumps(bad, sort_keys=True,
                                   separators=(",", ":")) + "\n").encode("ascii")
                _read, writer = self._setup(stack, review=data)
                with self.assertRaises((OSError, ValueError)):
                    self._record()
                writer.assert_not_called()

    def test_one_resolution_is_chained_to_review_and_never_unlocks(self):
        with ExitStack() as stack:
            _read, writer = self._setup(stack)
            record = self._record()
            self.assertFalse(record["retry_allowed"])
            self.assertEqual(
                record["review_sha256"], hashlib.sha256(REVIEW_BYTES).hexdigest())
            self.assertEqual(record["intent_sha256"], INTENT)
            self.assertEqual(record["initial_evidence_sha256"], "c" * 64)
            self.assertEqual(record["recovery_evidence_sha256"], EVIDENCE)
            writer.assert_called_once()
            self.assertTrue(writer.call_args.args[1].endswith(".ntcommit.resolution"))
            self.assertNotIn(b'"retry_allowed":true', writer.call_args.args[2])

    def test_preexisting_resolution_never_overwritten(self):
        with ExitStack() as stack:
            _read, writer = self._setup(stack)
            writer.side_effect = FileExistsError("existing create-only marker")
            with self.assertRaises(FileExistsError):
                self._record()
            writer.assert_called_once()

    def test_progress_changed_during_recording_fails_closed(self):
        with ExitStack() as stack:
            _read, writer = self._setup(stack)
            stack.enter_context(mock.patch.object(
                resolution, "_inspect_open_store",
                return_value=dict(REPORT, completed=1)))
            with self.assertRaises(OSError):
                self._record()
            writer.assert_not_called()

    def test_inspection_detects_chain_mismatch(self):
        with ExitStack() as stack:
            _read, writer = self._setup(stack)
            record = self._record()
            data = (json.dumps(record, sort_keys=True,
                               separators=(",", ":")) + "\n").encode("ascii")
            def read(_store, name, _max_bytes):
                return data if name.endswith(".resolution") else REVIEW_BYTES
            stack.enter_context(mock.patch.object(
                resolution, "_read_optional", side_effect=read))
            status = resolution.inspect_nt_incident_resolution_experimental(
                ROOT, STORE)
            self.assertEqual(status["status"],
                             "administrative_resolution_recorded")
            self.assertFalse(status["retry_allowed"])
            self.assertFalse(status["new_epoch_allowed"])
            writer.assert_called_once()
            with mock.patch.object(
                    resolution, "_read_optional",
                    side_effect=lambda _s, name, _n:
                    (data.replace(b"no-retry", b"yes-retry")
                     if name.endswith(".resolution") else REVIEW_BYTES)):
                with self.assertRaises(ValueError):
                    resolution.inspect_nt_incident_resolution_experimental(
                        ROOT, STORE)


@unittest.skipUnless(os.name == "nt", "NT native create-only test on Windows")
class WindowsNativeResolutionFileTests(unittest.TestCase):
    def test_resolution_marker_is_write_once_and_preserves_intent(self):
        from nt_commit_checkpoint_experimental import _write_verified
        from win32_relative_directory import open_trusted_root
        import nt_commit_checkpoint_experimental as checkpoint
        with tempfile.TemporaryDirectory() as root:
            with open_trusted_root(root) as fd:
                with mock.patch.object(
                        checkpoint, "_assert_protected_acl"):
                    _write_verified(fd, "test.ntcommit.intent", b"ORIGINAL\n")
                    _write_verified(fd, "test.ntcommit.resolution", b"CLOSED\n")
                    with self.assertRaises(OSError):
                        _write_verified(fd, "test.ntcommit.resolution", b"REPLACED\n")
            with open(os.path.join(root, "test.ntcommit.intent"), "rb") as src:
                self.assertEqual(src.read(), b"ORIGINAL\n")
            with open(os.path.join(root, "test.ntcommit.resolution"), "rb") as src:
                self.assertEqual(src.read(), b"CLOSED\n")


if __name__ == "__main__":
    unittest.main()

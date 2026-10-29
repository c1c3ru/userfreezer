#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only NT write-effect forensic regression (#63)."""
import hashlib
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import nt_commit_effects_experimental as effects
import nt_commit_forensics_experimental as forensic

ROOT = r"C:\Protected"
RID = (10, 11, 12)


def write_entry(path, payload):
    return {"kind": "W", "path": path, "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}


class NTReadOnlyEffectTests(unittest.TestCase):
    def _scan(self, steps, reads, identity=RID):
        with mock.patch.object(effects, "open_trusted_root") as opener:
            with mock.patch.object(
                    effects, "directory_identity", return_value=identity):
                with mock.patch.object(effects, "_assert_protected_acl"):
                    with mock.patch.object(
                            effects, "_read_write_effect",
                            side_effect=reads) as reader:
                        opener.return_value.__enter__.return_value = 7
                        result = effects.inspect_nt_commit_write_effects(
                            ROOT, RID, steps)
                        return result, reader.call_args_list

    def test_matching_hash_never_authorizes_replay(self):
        report, reads = self._scan([write_entry("ok.txt", b"KNOWN")],
                                   [b"KNOWN"])
        self.assertEqual(report["steps"][0]["observation"],
                         "matches_recorded_hash")
        self.assertEqual(report["bytes_scanned"], 5)
        self.assertFalse(report["safe_to_retry"])
        self.assertEqual(len(reads), 1)

    def test_mismatched_absent_and_unsafe_are_distinct(self):
        steps = [write_entry("different", b"ORIGINAL"),
                 write_entry("missing", b"ORIGINAL"),
                 write_entry("junction", b"ORIGINAL"),
                 {"kind": "D", "path": "old", "size": 0, "sha256": None}]
        report, calls = self._scan(
            steps, [b"MUTATED", None, PermissionError("ACL unsafe")])
        self.assertEqual(
            [x["observation"] for x in report["steps"]],
            ["differs_from_recorded_hash", "missing", "unverifiable",
             "not_verified_for_nonwrite"])
        self.assertEqual(len(calls), 3)
        self.assertFalse(report["safe_to_retry"])

    def test_fail_closed_on_root_identity_change(self):
        with mock.patch.object(effects, "open_trusted_root") as opener:
            with mock.patch.object(
                    effects, "directory_identity", return_value=(10, 11, 13)):
                with mock.patch.object(effects, "_read_write_effect") as read:
                    opener.return_value.__enter__.return_value = 7
                    with self.assertRaises(OSError):
                        effects.inspect_nt_commit_write_effects(
                            ROOT, RID, [write_entry("x", b"x")])
                    read.assert_not_called()

    def test_size_limit_prevents_read(self):
        steps = [write_entry("a", b"a"),
                 write_entry("b", b"0123456789")]
        with mock.patch.object(effects, "MAX_SCAN_TOTAL_BYTES", 5):
            report, calls = self._scan(steps, [b"a"])
        self.assertEqual(report["steps"][0]["observation"],
                         "matches_recorded_hash")
        self.assertEqual(report["steps"][1]["observation"],
                         "not_verified_budget")
        self.assertEqual(len(calls), 1)

    def test_bad_metadata_rejected(self):
        with self.assertRaises(ValueError):
            effects.inspect_nt_commit_write_effects(ROOT, RID, [
                {"kind": "W", "path": "safe", "size": True,
                 "sha256": "0" * 64}])

    def test_forensic_report_rechecks_markers_and_refuses_replay(self):
        report = {
            "state": "uncertain", "completed": 0, "total": 2,
            "uncertain_index": 0, "intent_sha256": "a" * 64}
        intent = {
            "root": ROOT, "overlay": r"C:\Overlay",
            "root_id": list(RID), "overlay_id": [13, 14, 15],
            "steps": [write_entry("a", b"X"),
                      write_entry("b", b"Y")]}
        observations = {
            "steps": [{"index": 0, "kind": "W", "path": "a",
                       "observation": "matches_recorded_hash"},
                      {"index": 1, "kind": "W", "path": "b",
                       "observation": "missing"}],
            "bytes_scanned": 1, "safe_to_retry": False}
        with mock.patch.object(forensic, "load_identity_from_store",
                               side_effect=[RID, (13, 14, 15)]):
            with mock.patch.object(forensic, "open_trusted_root") as opener:
                with mock.patch.object(forensic, "directory_identity",
                                       side_effect=[RID, (13, 14, 15)]):
                    with mock.patch.object(forensic, "_assert_protected_acl"):
                        with mock.patch.object(forensic, "_inspect_open_store",
                                               side_effect=[report, report]):
                            with mock.patch.object(forensic, "_read_optional",
                                                   return_value=b"record"):
                                with mock.patch.object(forensic, "_parse_intent",
                                                       return_value=intent):
                                    with mock.patch(
                                            "nt_commit_effects_experimental.inspect_nt_commit_write_effects",
                                            return_value=observations):
                                        opener.return_value.__enter__.side_effect = [1, 2, 3, 4]
                                        result = forensic.inspect_nt_commit_for_operator(
                                            ROOT, r"C:\Store")
        self.assertEqual(result["write_effects"]["steps"][0]["marker_state"],
                         "started_uncertain")
        self.assertEqual(result["write_effects"]["steps"][1]["marker_state"],
                         "not_confirmed")
        self.assertTrue(result["manual_review_required"])
        self.assertFalse(result["replay_allowed"])

    def test_marker_changed_during_hash_scan_is_error(self):
        before = {"state": "uncertain", "completed": 0, "total": 1,
                  "uncertain_index": 0, "intent_sha256": "a" * 64}
        after = dict(before, completed=1, state="complete", uncertain_index=None)
        intent = {"root": ROOT, "overlay": r"C:\Overlay",
                  "root_id": list(RID), "overlay_id": [13, 14, 15],
                  "steps": [write_entry("a", b"X")]}
        with mock.patch.object(forensic, "load_identity_from_store",
                               side_effect=[RID, (13, 14, 15)]):
            with mock.patch.object(forensic, "open_trusted_root") as opener:
                with mock.patch.object(forensic, "directory_identity",
                                       side_effect=[RID, (13, 14, 15)]):
                    with mock.patch.object(forensic, "_assert_protected_acl"):
                        with mock.patch.object(forensic, "_inspect_open_store",
                                               side_effect=[before, after]):
                            with mock.patch.object(forensic, "_read_optional",
                                                   return_value=b"record"):
                                with mock.patch.object(forensic, "_parse_intent",
                                                       return_value=intent):
                                    with mock.patch(
                                            "nt_commit_effects_experimental.inspect_nt_commit_write_effects",
                                            return_value={"steps": []}):
                                        opener.return_value.__enter__.side_effect = [1, 2, 3, 4]
                                        with self.assertRaises(OSError):
                                            forensic.inspect_nt_commit_for_operator(
                                                ROOT, r"C:\Store")


@unittest.skipUnless(os.name == "nt", "requires native Windows NT handles")
class WindowsNTReadOnlyEffectTests(unittest.TestCase):
    def test_disk_writes_matches_missing_and_changed(self):
        from win32_relative_directory import (
            directory_identity, open_trusted_root,
        )
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "match.txt"), "wb") as out:
                out.write(b"MATCH")
            with open(os.path.join(root, "changed.txt"), "wb") as out:
                out.write(b"OTHER")
            with open_trusted_root(root) as parent:
                identity = directory_identity(parent)
            with mock.patch.object(effects, "_assert_protected_acl"):
                report = effects.inspect_nt_commit_write_effects(
                    root, identity, [
                        write_entry("match.txt", b"MATCH"),
                        write_entry("changed.txt", b"EXPECTED"),
                        write_entry("missing.txt", b"NONE")])
            self.assertEqual(
                [s["observation"] for s in report["steps"]],
                ["matches_recorded_hash", "differs_from_recorded_hash", "missing"])
            self.assertFalse(report["safe_to_retry"])

    def test_junction_is_not_followed_for_hash(self):
        from win32_relative_directory import (
            directory_identity, open_trusted_root,
        )
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "target")
            external = os.path.join(base, "external")
            os.mkdir(root)
            os.mkdir(external)
            outside = os.path.join(external, "sentinel.txt")
            with open(outside, "wb") as out:
                out.write(b"UNCHANGED")
            link = os.path.join(root, "link")
            result = subprocess.run(["cmd", "/c", "mklink", "/J", link, external],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                self.skipTest("junction privilege unavailable")
            try:
                with open_trusted_root(root) as parent:
                    identity = directory_identity(parent)
                with mock.patch.object(effects, "_assert_protected_acl"):
                    scan = effects.inspect_nt_commit_write_effects(
                        root, identity, [write_entry("link/sentinel.txt",
                                                    b"UNCHANGED")])
                self.assertEqual(scan["steps"][0]["observation"], "unverifiable")
                with open(outside, "rb") as inp:
                    self.assertEqual(inp.read(), b"UNCHANGED")
            finally:
                if os.path.lexists(link):
                    os.rmdir(link)


if __name__ == "__main__":
    unittest.main()

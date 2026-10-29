#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression for pinned NT journal reconciliation (#63)."""
import json
import os
import tempfile
import unittest
from unittest import mock

import nt_overlay_journal_experimental as journal
from win32_relative_directory import open_trusted_root, directory_identity


ROOT = r"C:\Secure\Protected"
MAN = json.dumps({"v": 1, "root": ROOT, "entries": {}}).encode("utf-8")
RECORD = {"seq": 1, "op": "W", "p": "new.txt", "d": 0, "src": "0000000000000001"}
LINE = (json.dumps(RECORD) + "\n").encode("utf-8")
OPS = {"new.txt": (1, "W", 0)}
IDS = {"new.txt": "0000000000000001"}


class JournalReconciliationTests(unittest.TestCase):
    def test_valid_journal_maps_to_native_preflight(self):
        entries = journal._parse_pinned_metadata(
            MAN, LINE, ROOT, OPS, IDS, 1)
        self.assertEqual(entries, [
            (["new.txt"], "W", 0, "payloads/0000000000000001")])

    def test_late_corruption_never_trusts_core_in_memory_ops(self):
        changes = [
            LINE + b"{",
            LINE + LINE,
            LINE.replace(b"new.txt", b"../exit"),
            LINE.replace(b"0000000000000001", b"bad"),
            LINE.replace(b'"seq": 1', b'"seq": true'),
            b'{"seq":1,"seq":2,"op":"W","p":"new.txt","src":"01"}\n',
            b'{"seq":1,"op":"F","p":"new.txt","d":0}\n',
        ]
        for raw in changes:
            with self.subTest(journal=raw), self.assertRaises(ValueError):
                journal._parse_pinned_metadata(
                    MAN, raw, ROOT, OPS, IDS, 1)

    def test_memory_divergence_and_manifest_root_are_rejected(self):
        wrong_manifest = json.dumps(
            {"v": 1, "root": r"C:\Other", "entries": {}}).encode("utf-8")
        for man, ops, ids, seq in (
                (wrong_manifest, OPS, IDS, 1),
                (MAN, {"other.txt": (1, "W", 0)}, IDS, 1),
                (MAN, OPS, {"new.txt": "fake"}, 1),
                (MAN, OPS, IDS, 0),
                (MAN, OPS, IDS, 2)):
            with self.subTest(seq=seq), self.assertRaises(ValueError):
                journal._parse_pinned_metadata(
                    man, LINE, ROOT, ops, ids, seq)

    def test_mutable_legacy_payload_is_refused(self):
        legacy = (b'{"seq":1,"op":"W","p":"new.txt","d":0}\n')
        with self.assertRaises(ValueError):
            journal._parse_pinned_metadata(
                MAN, legacy, ROOT, OPS, {}, 1)

    def test_empty_journal_for_empty_overlay(self):
        self.assertEqual(journal._parse_pinned_metadata(
            MAN, b"", ROOT, {}, {}, 0), [])

    def test_pinned_identity_mismatch_refuses_before_metadata_read(self):
        with mock.patch.object(journal, "load_identity_from_store",
                               return_value=(1, 2, 3)):
            with mock.patch.object(journal, "open_trusted_root") as opener:
                with mock.patch.object(journal, "directory_identity",
                                       return_value=(1, 2, 4)):
                    with mock.patch.object(journal, "read_relative_file") as reader:
                        opener.return_value.__enter__.return_value = 42
                        with self.assertRaises(OSError):
                            journal.prepare_verified_journal_entries_experimental(
                                ROOT, r"C:\Overlay", r"C:\Store", OPS, IDS, 1)
                        reader.assert_not_called()

    def test_pinned_reader_checks_acl_and_each_metadata_handle(self):
        with mock.patch.object(journal, "load_identity_from_store",
                               return_value=(1, 2, 3)):
            with mock.patch.object(journal, "open_trusted_root") as opener:
                with mock.patch.object(journal, "directory_identity",
                                       return_value=(1, 2, 3)):
                    with mock.patch.object(journal, "_assert_protected_acl") as guard:
                        with mock.patch.object(journal, "read_relative_file",
                                               side_effect=[MAN, LINE]) as reader:
                            opener.return_value.__enter__.return_value = 42
                            result = journal.prepare_verified_journal_entries_experimental(
                                ROOT, r"C:\Overlay", r"C:\Store", OPS, IDS, 1)
                            self.assertEqual(len(result), 1)
                            guard.assert_called_once_with(42)
                            self.assertEqual(reader.call_args_list, [
                                mock.call(42, "manifest.json", max_bytes=16777216,
                                          handle_guard=journal._assert_protected_acl),
                                mock.call(42, "journal.log", max_bytes=16777216,
                                          handle_guard=journal._assert_protected_acl)])


class ReconciledNativeBridgeTests(unittest.TestCase):
    def test_refuses_to_apply_if_pinned_journal_disagrees(self):
        import nt_commit_bridge_experimental as bridge
        with mock.patch(
                "nt_overlay_journal_experimental.prepare_verified_journal_entries_experimental",
                side_effect=ValueError("journal mismatch")):
            with mock.patch("nt_enrollment_store_experimental.load_identity_from_store") as lookup:
                with mock.patch.object(
                        bridge, "apply_pinned_overlay_plan_experimental") as apply:
                    with self.assertRaises(ValueError):
                        bridge.apply_reconciled_plan_experimental(
                            ROOT, r"C:\Overlay", r"C:\Store", OPS, IDS, 1)
                    lookup.assert_not_called()
                    apply.assert_not_called()

    def test_reconciled_plan_passes_only_trusted_sources(self):
        import nt_commit_bridge_experimental as bridge
        with mock.patch(
                "nt_overlay_journal_experimental.prepare_verified_journal_entries_experimental",
                return_value=[(["new.txt"], "W", 0, "payloads/0000000000000001")]):
            with mock.patch("nt_enrollment_store_experimental.load_identity_from_store",
                            return_value=(1, 2, 3)):
                with mock.patch.object(
                        bridge, "apply_pinned_overlay_plan_experimental",
                        return_value=["new.txt"]) as apply:
                    result = bridge.apply_reconciled_plan_experimental(
                        ROOT, r"C:\Overlay", r"C:\Store", OPS, IDS, 1)
                    self.assertEqual(result, ["new.txt"])
                    apply.assert_called_once_with(
                        ROOT, [(["new.txt"], "W", 0, "payloads/0000000000000001")],
                        r"C:\Store", r"C:\Overlay", (1, 2, 3),
                        max_payload=16777216, max_total=67108864)


@unittest.skipUnless(os.name == "nt", "requires Windows handles")
class WindowsPinnedJournalTests(unittest.TestCase):
    def test_full_reconciled_handle_plan_writes_only_enrolled_target(self):
        import ntpath
        import nt_commit_bridge_experimental as bridge
        import nt_enrollment_store_experimental as store
        import nt_overlay_payload_experimental as payload
        with tempfile.TemporaryDirectory() as temp:
            target = os.path.join(temp, "protected")
            overlay_path = os.path.join(temp, "overlay")
            os.mkdir(target)
            os.mkdir(overlay_path)
            os.mkdir(os.path.join(overlay_path, "payloads"))
            with open_trusted_root(target) as handle:
                target_id = directory_identity(handle)
            with open_trusted_root(overlay_path) as handle:
                overlay_id = directory_identity(handle)
            manifest = json.dumps(
                {"v": 1, "root": target, "entries": {}}).encode("utf-8")
            for filename, data in (
                    ("manifest.json", manifest),
                    ("journal.log", LINE)):
                with open(os.path.join(overlay_path, filename), "wb") as out:
                    out.write(data)
            with open(os.path.join(overlay_path, "payloads",
                                   "0000000000000001"), "wb") as out:
                out.write(b"SAFE-COMMIT")
            def identity_for(path, _store):
                return (overlay_id if ntpath.normcase(path) ==
                        ntpath.normcase(overlay_path) else target_id)
            with mock.patch.object(
                    journal, "load_identity_from_store",
                    side_effect=identity_for):
                with mock.patch.object(
                        store, "load_identity_from_store",
                        side_effect=identity_for):
                    with mock.patch.object(journal, "_assert_protected_acl"):
                        with mock.patch.object(payload, "_assert_protected_acl"):
                            result = bridge.apply_reconciled_plan_experimental(
                                target, overlay_path, r"C:\Unused",
                                OPS, IDS, 1)
            self.assertEqual(result, ["new.txt"])
            with open(os.path.join(target, "new.txt"), "rb") as inp:
                self.assertEqual(inp.read(), b"SAFE-COMMIT")

    def test_disk_manifest_and_journal_match_pinned_core_state(self):
        with tempfile.TemporaryDirectory() as overlay:
            with open(os.path.join(overlay, "manifest.json"), "wb") as output:
                output.write(MAN)
            with open(os.path.join(overlay, "journal.log"), "wb") as output:
                output.write(LINE)
            with open_trusted_root(overlay) as handle:
                ident = directory_identity(handle)
            with mock.patch.object(journal, "load_identity_from_store",
                                   return_value=ident):
                with mock.patch.object(journal, "_assert_protected_acl"):
                    result = journal.prepare_verified_journal_entries_experimental(
                        ROOT, overlay, r"C:\unused", OPS, IDS, 1)
            self.assertEqual(result[0][3], "payloads/0000000000000001")


if __name__ == "__main__":
    unittest.main()

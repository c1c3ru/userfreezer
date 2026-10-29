#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crash-consistent intent/progress *visibility* tests for NT commit #63.

These are not rollback/transactional-atomicity claims.
"""
import json
import ntpath
import os
import tempfile
import unittest
from unittest import mock

import nt_commit_checkpoint_experimental as checkpoint

ROOT = r"C:\Protected"
OVERLAY = r"C:\Protected.dfreezer"
STORE = r"C:\Enrollment"
RID = (11, 22, 33)
OID = (44, 55, 66)
PLAN = [("W", "a.txt", b"A"), ("M", "sub", None),
        ("W", "sub/b.txt", b"B")]


def fixture():
    return checkpoint._intent_record(ROOT, OVERLAY, RID, OID, PLAN)


class CheckpointFormatTests(unittest.TestCase):
    def test_durable_intent_has_all_operation_hashes_and_binding(self):
        record, raw = fixture()
        self.assertEqual(checkpoint._parse_intent(raw, ROOT), record)
        self.assertEqual(record["steps"][0]["kind"], "W")
        self.assertEqual(record["steps"][0]["size"], 1)
        self.assertEqual(len(record["steps"][0]["sha256"]), 64)
        self.assertEqual(record["root_id"], list(RID))
        self.assertEqual(record["overlay_id"], list(OID))
        self.assertNotIn(b'"payload":', raw)

    def test_intent_digest_detects_tamper_and_truncation(self):
        _record, raw = fixture()
        for payload in (raw[:-1], raw[:-2] + b"\n",
                        raw.replace(b"a.txt", b"z.txt"), b"{}",
                        raw + b"\n"):
            with self.subTest(payload=payload[:32]):
                with self.assertRaises(ValueError):
                    checkpoint._parse_intent(payload, ROOT)

    def test_canonical_name_is_deterministic_and_target_bound(self):
        first = checkpoint._ledger_prefix(ROOT)
        self.assertEqual(first, checkpoint._ledger_prefix(r"c:\protected"))
        self.assertNotEqual(first, checkpoint._ledger_prefix(r"C:\Different"))
        self.assertEqual(len(first), 73)
        with self.assertRaises(ValueError):
            checkpoint._ledger_prefix(r"\\host\share")

    def test_store_and_overlay_cannot_be_nested_under_target(self):
        for root, overlay, store in (
                (ROOT, r"C:\Protected\overlay", STORE),
                (ROOT, OVERLAY, r"C:\Protected\admin"),
                (ROOT, STORE, STORE),
                (ROOT, OVERLAY, r"C:\Protected.dfreezer\store")):
            with self.subTest(root=root, overlay=overlay, store=store):
                with self.assertRaises(ValueError):
                    checkpoint._separate_roots(root, overlay, store)

    def test_maximum_steps_enforced_before_mutation(self):
        with self.assertRaises(ValueError):
            checkpoint._describe_plan([("M", "dir", None)] * 257)
        for plan in ([], [("W", "../escape", b"bad")],
                     [("W", "ok", "not-bytes")]):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                checkpoint._describe_plan(plan)


class CheckpointInspectionTests(unittest.TestCase):
    @staticmethod
    def _reader(files):
        def read(_parent, name, _max_bytes):
            return files.get(name)
        return read

    def test_no_intent_is_absent(self):
        with mock.patch.object(checkpoint, "_read_optional",
                               side_effect=self._reader({})):
            self.assertEqual(
                checkpoint._inspect_open_store(1, ROOT),
                {"state": "absent", "completed": 0, "total": 0})

    def test_started_without_done_is_uncertain_not_success(self):
        record, data = fixture()
        prefix = checkpoint._ledger_prefix(ROOT)
        files = {
            prefix + ".intent": data,
            prefix + ".00000.started": checkpoint._marker(
                0, "started", record["digest"]),
        }
        with mock.patch.object(checkpoint, "_read_optional",
                               side_effect=self._reader(files)):
            report = checkpoint._inspect_open_store(1, ROOT)
        self.assertEqual(report["state"], "uncertain")
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["uncertain_index"], 0)

    def test_partial_progress_is_not_a_safe_resume(self):
        record, data = fixture()
        prefix = checkpoint._ledger_prefix(ROOT)
        files = {prefix + ".intent": data}
        for kind in ("started", "done"):
            files[prefix + ".00000." + kind] = checkpoint._marker(
                0, kind, record["digest"])
        with mock.patch.object(checkpoint, "_read_optional",
                               side_effect=self._reader(files)):
            report = checkpoint._inspect_open_store(1, ROOT)
        self.assertEqual(report["state"], "incomplete")
        self.assertEqual(report["completed"], 1)

    def test_complete_only_after_every_done_marker(self):
        record, data = fixture()
        prefix = checkpoint._ledger_prefix(ROOT)
        files = {prefix + ".intent": data}
        for index in range(len(PLAN)):
            for kind in ("started", "done"):
                files[prefix + ".%05d.%s" % (index, kind)] = checkpoint._marker(
                    index, kind, record["digest"])
        files[prefix + ".complete"] = checkpoint._marker(
            len(PLAN), "complete", record["digest"])
        with mock.patch.object(checkpoint, "_read_optional",
                               side_effect=self._reader(files)):
            report = checkpoint._inspect_open_store(1, ROOT)
        self.assertEqual(report["state"], "complete")
        self.assertEqual(report["completed"], 3)

    def test_out_of_order_markers_fail_closed(self):
        record, data = fixture()
        prefix = checkpoint._ledger_prefix(ROOT)
        files = {
            prefix + ".intent": data,
            prefix + ".00001.started": checkpoint._marker(
                1, "started", record["digest"]),
        }
        with mock.patch.object(checkpoint, "_read_optional",
                               side_effect=self._reader(files)):
            with self.assertRaises(ValueError):
                checkpoint._inspect_open_store(1, ROOT)

    def test_forged_done_or_complete_is_rejected(self):
        record, data = fixture()
        prefix = checkpoint._ledger_prefix(ROOT)
        for files in (
                {prefix + ".intent": data,
                 prefix + ".00000.done": checkpoint._marker(
                     0, "done", record["digest"])},
                {prefix + ".intent": data,
                 prefix + ".complete": checkpoint._marker(
                     len(PLAN), "complete", record["digest"])},
                {prefix + ".intent": data,
                 prefix + ".00000.started": b"bad"}),
            with self.subTest(files=files):
                with mock.patch.object(checkpoint, "_read_optional",
                                       side_effect=self._reader(files)):
                    with self.assertRaises(ValueError):
                        checkpoint._inspect_open_store(1, ROOT)


class CheckpointBridgeTests(unittest.TestCase):
    def test_corrupt_journal_never_creates_intent(self):
        import nt_commit_bridge_experimental as bridge
        with mock.patch(
                "nt_overlay_journal_experimental.prepare_verified_journal_entries_experimental",
                side_effect=ValueError("corrupted journal")):
            with mock.patch(
                    "nt_commit_checkpoint_experimental.apply_checkpointed_plan_experimental"
                    ) as commit:
                with self.assertRaises(ValueError):
                    bridge.apply_reconciled_checkpointed_plan_experimental(
                        ROOT, OVERLAY, STORE, {}, {}, 0)
                commit.assert_not_called()

    def test_bridge_passes_verified_payload_to_checkpoint(self):
        import nt_commit_bridge_experimental as bridge
        with mock.patch(
                "nt_overlay_journal_experimental.prepare_verified_journal_entries_experimental",
                return_value=[(["a.txt"], "W", 0, "payloads/01")]):
            with mock.patch(
                    "nt_enrollment_store_experimental.load_identity_from_store",
                    return_value=OID):
                with mock.patch(
                        "nt_overlay_payload_experimental.pinned_overlay_payload_loader"
                        ) as loader:
                    loader.return_value.__enter__.return_value = (
                        lambda src, limit: b"SAFE")
                    with mock.patch(
                            "nt_commit_checkpoint_experimental.apply_checkpointed_plan_experimental",
                            return_value={"state": "complete"}) as commit:
                        result = bridge.apply_reconciled_checkpointed_plan_experimental(
                            ROOT, OVERLAY, STORE, {"a.txt": (1, "W", 0)},
                            {"a.txt": "01"}, 1)
                        self.assertEqual(result["state"], "complete")
                        commit.assert_called_once_with(
                            ROOT, OVERLAY, STORE, [("W", "a.txt", b"SAFE")])


@unittest.skipUnless(os.name == "nt", "requires Windows native NT handles")
class WindowsNativeCheckpointTests(unittest.TestCase):
    def setup_roots(self, directory):
        from win32_relative_directory import open_trusted_root, directory_identity
        root = os.path.join(directory, "root")
        overlay = os.path.join(directory, "overlay")
        store = os.path.join(directory, "store")
        for path in (root, overlay, store):
            os.mkdir(path)
        with open_trusted_root(root) as h:
            root_id = directory_identity(h)
        with open_trusted_root(overlay) as h:
            overlay_id = directory_identity(h)
        return root, overlay, store, root_id, overlay_id

    def test_real_nt_files_record_all_steps_and_prevent_replay(self):
        with tempfile.TemporaryDirectory() as base:
            root, overlay, store, root_id, overlay_id = self.setup_roots(base)
            def load(path, _store):
                return (overlay_id if ntpath.normcase(path) == ntpath.normcase(overlay)
                        else root_id)
            with mock.patch.object(checkpoint, "load_identity_from_store",
                                   side_effect=load):
                with mock.patch.object(checkpoint, "_assert_protected_acl"):
                    result = checkpoint.apply_checkpointed_plan_experimental(
                        root, overlay, store,
                        [("W", "first.txt", b"FIRST"),
                         ("M", "nested", None)])
                    self.assertEqual(result["state"], "complete")
                    report = checkpoint.inspect_nt_commit_checkpoint(root, store)
                    self.assertEqual(report["state"], "complete")
                    self.assertEqual(report["completed"], 2)
                    with self.assertRaises(checkpoint.PendingNTCommitError):
                        checkpoint.apply_checkpointed_plan_experimental(
                            root, overlay, store,
                            [("W", "another.txt", b"UNEXPECTED")])
            with open(os.path.join(root, "first.txt"), "rb") as stream:
                self.assertEqual(stream.read(), b"FIRST")
            self.assertFalse(os.path.exists(os.path.join(root, "another.txt")))

    def test_crash_window_after_mutation_is_reported_uncertain(self):
        with tempfile.TemporaryDirectory() as base:
            root, overlay, store, root_id, overlay_id = self.setup_roots(base)
            def load(path, _store):
                return (overlay_id if ntpath.normcase(path) == ntpath.normcase(overlay)
                        else root_id)
            def simulated_failure(_index, _name):
                raise SystemExit("injected crash after native write")
            with mock.patch.object(checkpoint, "load_identity_from_store",
                                   side_effect=load):
                with mock.patch.object(checkpoint, "_assert_protected_acl"):
                    with self.assertRaises(checkpoint.UncertainNTCommitError):
                        checkpoint.apply_checkpointed_plan_experimental(
                            root, overlay, store,
                            [("W", "first.txt", b"FIRST"),
                             ("W", "second.txt", b"SECOND")],
                            after_operation=simulated_failure)
                    report = checkpoint.inspect_nt_commit_checkpoint(root, store)
                    self.assertEqual(report["state"], "uncertain")
                    self.assertEqual(report["uncertain_index"], 0)
                    with self.assertRaises(checkpoint.PendingNTCommitError):
                        checkpoint.apply_checkpointed_plan_experimental(
                            root, overlay, store,
                            [("W", "first.txt", b"FIRST")])
            with open(os.path.join(root, "first.txt"), "rb") as stream:
                self.assertEqual(stream.read(), b"FIRST")
            self.assertFalse(os.path.exists(os.path.join(root, "second.txt")))

    def test_corrupted_prior_intent_cannot_be_overwritten(self):
        from win32_relative_directory import open_trusted_root, create_relative_file
        with tempfile.TemporaryDirectory() as base:
            root, overlay, store, root_id, overlay_id = self.setup_roots(base)
            with open_trusted_root(store) as parent:
                create_relative_file(
                    parent, checkpoint._ledger_prefix(root) + ".intent",
                    b"corrupt")
            with mock.patch.object(checkpoint, "_assert_protected_acl"):
                with self.assertRaises(ValueError):
                    checkpoint.inspect_nt_commit_checkpoint(root, store)
                with mock.patch.object(checkpoint, "load_identity_from_store",
                                       side_effect=lambda path, _store:
                                       overlay_id if ntpath.normcase(path) == ntpath.normcase(overlay)
                                       else root_id):
                    with self.assertRaises(checkpoint.PendingNTCommitError):
                        checkpoint.apply_checkpointed_plan_experimental(
                            root, overlay, store, [("W", "safe.txt", b"NO")])
            self.assertFalse(os.path.exists(os.path.join(root, "safe.txt")))


if __name__ == "__main__":
    unittest.main()

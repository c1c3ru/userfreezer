#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline Win7 NT reboot evidence verifier tests (portable Python 3.8+)."""
import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest


def _load():
    filename = os.path.join(os.path.dirname(__file__), "packaging",
                            "windows", "verify_nt_checkpoint_evidence.py")
    spec = importlib.util.spec_from_file_location("win7_evidence_verifier", filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures():
    report = {"state": "uncertain", "completed": 0, "total": 2,
              "uncertain_index": 0, "intent_sha256": "a" * 64}
    markers = {".intent": "b" * 64, ".00000.started": "c" * 64}
    version = {"major": 6, "minor": 1, "service_pack_major": 1,
               "build": 7601, "platform": "AMD64"}
    before = {
        "schema": 2, "base": r"C:\DF-Checkpoint-Probe",
        "windows_version": version, "marker_sha256": markers,
        "checkpoint": report, "child_exit_code": 1,
        "first_sha256": hashlib.sha256(b"FIRST").hexdigest(),
        "second_absent": True,
        "boot_before": "20261030080000.000000-180",
        "scope": "VM scratch only; native ACL/enrollment mocked",
    }
    after = {
        "result": "PASS_SCRATCH_CHECKPOINT_POST_REBOOT",
        "boot_before": "20261030080000.000000-180",
        "boot_after": "20261030090000.000000-180",
        "checkpoint": copy.deepcopy(report), "marker_sha256": copy.deepcopy(markers),
        "windows_version": copy.deepcopy(version),
        "scope": "VM scratch only; no production ACL/enrollment/recovery proof",
    }
    return before, after


class OfflineEvidenceVerification(unittest.TestCase):
    def setUp(self):
        self.verifier = _load()
        self.before, self.after = fixtures()

    def test_consistent_evidence_cannot_claim_vm_certification(self):
        report = self.verifier.verify_evidence(self.before, self.after)
        self.assertEqual(report["result"], "CONSISTENT_OFFLINE_EVIDENCE_ONLY")
        self.assertFalse(report["vm_or_reboot_independently_authenticated"])
        self.assertFalse(report["production_commit_certified"])
        self.assertFalse(report["automatic_retry_allowed"])

    def test_reboot_timestamp_must_change_and_be_dmtf(self):
        for stamp in ("20261030080000.000000-180",
                      "30/10/2026 09:00:00", "20261030090000"):
            with self.subTest(stamp=stamp):
                after = copy.deepcopy(self.after)
                after["boot_after"] = stamp
                with self.assertRaises(ValueError):
                    self.verifier.verify_evidence(self.before, after)

    def test_tampered_markers_and_intent_refuse(self):
        scenarios = (
            ("markers", lambda a: a["marker_sha256"].update(
                {".00000.started": "d" * 64})),
            ("missing_marker", lambda a: a["marker_sha256"].pop(".intent")),
            ("intent", lambda a: a["checkpoint"].update(
                {"intent_sha256": "e" * 64})),
            ("completed", lambda a: a["checkpoint"].update(
                {"completed": 1})),
            ("extra_field", lambda a: a.update({"replay_allowed": True})),
        )
        for name, mutate in scenarios:
            with self.subTest(name=name):
                after = copy.deepcopy(self.after)
                mutate(after)
                with self.assertRaises(ValueError):
                    self.verifier.verify_evidence(self.before, after)

    def test_wrong_os_and_fake_result_refuse(self):
        for name, mutate in (
            ("modern_windows", lambda a: a["windows_version"].update({"major": 10})),
            ("missing_sp1", lambda a: a["windows_version"].update(
                {"service_pack_major": 0})),
            ("fake_pass", lambda a: a.update({"result": "PASS"})),
        ):
            with self.subTest(name=name):
                after = copy.deepcopy(self.after)
                mutate(after)
                with self.assertRaises(ValueError):
                    self.verifier.verify_evidence(self.before, after)

    def test_missing_crash_and_sentinel_evidence_refuse(self):
        for key, value in (
            ("child_exit_code", 0),
            ("child_exit_code", True),
            ("second_absent", False),
            ("first_sha256", "0" * 64),
        ):
            with self.subTest(key=key, value=value):
                before = copy.deepcopy(self.before)
                before[key] = value
                with self.assertRaises(ValueError):
                    self.verifier.verify_evidence(before, self.after)

    def test_reads_json_and_rejects_duplicate_keys_or_oversize(self):
        with tempfile.TemporaryDirectory() as temp:
            filename = os.path.join(temp, "evidence.json")
            with open(filename, "w", encoding="utf-8") as stream:
                json.dump(self.before, stream)
            self.assertEqual(
                self.verifier.load_evidence(filename), self.before)
            with open(filename, "w", encoding="utf-8") as stream:
                stream.write('{"schema":2,"schema":2}')
            with self.assertRaisesRegex(ValueError, "duplicada"):
                self.verifier.load_evidence(filename)
            with open(filename, "wb") as stream:
                stream.write(b"x" * (1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "excede"):
                self.verifier.load_evidence(filename)


if __name__ == "__main__":
    unittest.main()

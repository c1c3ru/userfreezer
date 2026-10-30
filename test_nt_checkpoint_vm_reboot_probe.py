#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Proof that the reboot probe cannot report PASS on the same boot."""
import hashlib
import importlib.util
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


def _load_probe():
    path = os.path.join(os.path.dirname(__file__), "packaging", "windows",
                        "nt_checkpoint_vm_reboot_probe.py")
    spec = importlib.util.spec_from_file_location("nt_checkpoint_vm_reboot_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VMBootEvidenceTests(unittest.TestCase):
    def test_same_boot_refuses_success_even_if_checkpoint_looks_valid(self):
        probe = _load_probe()
        with tempfile.TemporaryDirectory() as temp:
            evidence = os.path.join(temp, "evidence.json")
            base = os.path.join(temp, "scratch")
            os.mkdir(base)
            with open(evidence, "w", encoding="utf-8") as out:
                json.dump({"schema": 2, "base": base,
                           "windows_version": {"major": 6, "minor": 1, "service_pack_major": 1, "build": 7601, "platform": "AMD64"},
                           "marker_sha256": {".intent": "a" * 64, ".00000.started": "b" * 64},
                           "boot_before": "20261029100000.000000-180",
                           "checkpoint": {"intent_sha256": "f" * 64}}, out)
            with mock.patch.object(probe, "_win7_sp1_version",
                                   return_value={"major": 6, "minor": 1, "service_pack_major": 1, "build": 7601, "platform": "AMD64"}):
             with mock.patch.object(probe, "_boot_stamp",
                                   return_value="20261029100000.000000-180"):
                with mock.patch.object(probe, "_inspect") as inspect:
                    with self.assertRaisesRegex(RuntimeError, "SEM REBOOT"):
                        probe._verify(base, evidence)
                    inspect.assert_not_called()

    def test_changed_boot_requires_exact_checkpoint_and_sentinal_hash(self):
        probe = _load_probe()
        with tempfile.TemporaryDirectory() as temp:
            evidence = os.path.join(temp, "evidence.json")
            base = os.path.join(temp, "scratch")
            root = os.path.join(base, "target")
            os.makedirs(root)
            with open(os.path.join(root, "first.txt"), "wb") as out:
                out.write(b"FIRST")
            record = {"state": "uncertain", "uncertain_index": 0,
                      "completed": 0, "total": 2, "intent_sha256": "a" * 64}
            with open(evidence, "w", encoding="utf-8") as out:
                json.dump({"schema": 1, "base": base,
                           "boot_before": "20261029100000.000000-180",
                           "checkpoint": record}, out)
            with mock.patch.object(probe, "_boot_stamp",
                                   return_value="20261029110000.000000-180"):
                with mock.patch.object(probe, "_inspect", return_value=record):
                    with mock.patch.object(probe, "_marker_fingerprints", return_value={".intent": "a" * 64, ".00000.started": "b" * 64}):
                        result = probe._verify(base, evidence)
                self.assertEqual(result["result"],
                                 "PASS_SCRATCH_CHECKPOINT_POST_REBOOT")
                self.assertNotIn("production", result["result"].lower())
                with open(os.path.join(root, "first.txt"), "wb") as out:
                    out.write(b"CORRUPTED")
                with mock.patch.object(probe, "_inspect", return_value=record):
                    with self.assertRaisesRegex(RuntimeError, "divergiram"):
                        probe._verify(base, evidence)
                with mock.patch.object(
                        probe, "_inspect",
                        return_value=dict(record, intent_sha256="b" * 64)):
                    with open(os.path.join(root, "first.txt"), "wb") as out:
                        out.write(b"FIRST")
                    with self.assertRaisesRegex(RuntimeError, "intencao mudou"):
                        probe._verify(base, evidence)


    def test_version_gate_refuses_windows_other_than_win7_sp1(self):
        probe = _load_probe()
        with mock.patch.object(probe.os, "name", "nt"):
            for major, minor, sp in ((10, 0, 0), (6, 1, 0), (6, 2, 0)):
                fake = SimpleNamespace(major=major, minor=minor,
                                       service_pack_major=sp, build=7601)
                with self.subTest(version=(major, minor, sp)):
                    with mock.patch.object(probe.sys, "getwindowsversion",
                                           return_value=fake, create=True):
                        with self.assertRaisesRegex(RuntimeError, "NAO e Windows 7 SP1"):
                            probe._win7_sp1_version()
            fake = SimpleNamespace(major=6, minor=1,
                                   service_pack_major=1, build=7601)
            with mock.patch.object(probe.sys, "getwindowsversion",
                                   return_value=fake, create=True):
                with mock.patch.object(probe.platform, "machine",
                                       return_value="AMD64"):
                    actual = probe._win7_sp1_version()
                    self.assertEqual(actual["build"], 7601)

    def test_post_reboot_rejects_tampered_marker_bytes(self):
        probe = _load_probe()
        with tempfile.TemporaryDirectory() as temp:
            base = os.path.join(temp, "scratch")
            root = os.path.join(base, "target")
            os.makedirs(root)
            with open(os.path.join(root, "first.txt"), "wb") as out:
                out.write(b"FIRST")
            evidence = os.path.join(temp, "before.json")
            record = {"state": "uncertain", "uncertain_index": 0,
                      "completed": 0, "total": 2, "intent_sha256": "a" * 64}
            version = {"major": 6, "minor": 1, "service_pack_major": 1,
                       "build": 7601, "platform": "AMD64"}
            with open(evidence, "w", encoding="utf-8") as out:
                json.dump({"schema": 2, "base": base, "checkpoint": record,
                           "windows_version": version, "boot_before": "old",
                           "marker_sha256": {".intent": "a" * 64}}, out)
            with mock.patch.object(probe, "_win7_sp1_version", return_value=version):
                with mock.patch.object(probe, "_boot_stamp", return_value="new"):
                    with mock.patch.object(probe, "_inspect", return_value=record):
                        with mock.patch.object(probe, "_marker_fingerprints",
                                               return_value={".intent": "b" * 64}):
                            with self.assertRaisesRegex(RuntimeError, "bytes dos marcadores"):
                                probe._verify(base, evidence)


if __name__ == "__main__":
    unittest.main()

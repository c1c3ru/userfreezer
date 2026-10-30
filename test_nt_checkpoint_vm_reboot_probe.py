#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression checks for Windows 7 SP1 two-phase crash/reboot evidence."""
import importlib.util
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


VERSION = {"major": 6, "minor": 1, "service_pack_major": 1,
           "build": 7601, "platform": "AMD64"}
MARKERS = {".intent": "a" * 64, ".00000.started": "b" * 64}
REPORT = {"state": "uncertain", "uncertain_index": 0,
          "completed": 0, "total": 2, "intent_sha256": "f" * 64}


def _load_probe():
    path = os.path.join(os.path.dirname(__file__), "packaging", "windows",
                        "nt_checkpoint_vm_reboot_probe.py")
    spec = importlib.util.spec_from_file_location("nt_checkpoint_vm_reboot_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(temp, create_first=True):
    base = os.path.join(temp, "scratch")
    target = os.path.join(base, "target")
    os.makedirs(target)
    if create_first:
        with open(os.path.join(target, "first.txt"), "wb") as out:
            out.write(b"FIRST")
    evidence = os.path.join(temp, "before.json")
    with open(evidence, "w", encoding="utf-8") as out:
        json.dump({"schema": 2, "base": base, "checkpoint": REPORT,
                   "windows_version": VERSION, "boot_before": "old",
                   "marker_sha256": MARKERS}, out)
    return base, target, evidence


class VMBootEvidenceTests(unittest.TestCase):
    def test_same_boot_refuses_even_if_checkpoint_looks_valid(self):
        probe = _load_probe()
        with tempfile.TemporaryDirectory() as temp:
            base, _target, evidence = _fixture(temp)
            with mock.patch.object(probe, "_win7_sp1_version", return_value=VERSION):
                with mock.patch.object(probe, "_boot_stamp", return_value="old"):
                    with mock.patch.object(probe, "_inspect") as inspect:
                        with self.assertRaisesRegex(RuntimeError, "SEM REBOOT"):
                            probe._verify(base, evidence)
                        inspect.assert_not_called()

    def test_changed_boot_requires_checkpoint_and_sentinel_hash(self):
        probe = _load_probe()
        with tempfile.TemporaryDirectory() as temp:
            base, target, evidence = _fixture(temp)
            with mock.patch.object(probe, "_win7_sp1_version", return_value=VERSION):
                with mock.patch.object(probe, "_boot_stamp", return_value="new"):
                    with mock.patch.object(probe, "_inspect", return_value=REPORT):
                        with mock.patch.object(probe, "_marker_fingerprints",
                                               return_value=MARKERS):
                            result = probe._verify(base, evidence)
                            self.assertEqual(
                                result["result"], "PASS_SCRATCH_CHECKPOINT_POST_REBOOT")
                            self.assertEqual(result["marker_sha256"], MARKERS)
                    with open(os.path.join(target, "first.txt"), "wb") as out:
                        out.write(b"CORRUPTED")
                    with mock.patch.object(probe, "_inspect", return_value=REPORT):
                        with self.assertRaisesRegex(RuntimeError, "divergiram"):
                            probe._verify(base, evidence)
                    with open(os.path.join(target, "first.txt"), "wb") as out:
                        out.write(b"FIRST")
                    with mock.patch.object(
                            probe, "_inspect",
                            return_value=dict(REPORT, intent_sha256="e" * 64)):
                        with self.assertRaisesRegex(RuntimeError, "intencao mudou"):
                            probe._verify(base, evidence)

    def test_marker_byte_change_does_not_pass_after_reboot(self):
        probe = _load_probe()
        with tempfile.TemporaryDirectory() as temp:
            base, _target, evidence = _fixture(temp)
            with mock.patch.object(probe, "_win7_sp1_version", return_value=VERSION):
                with mock.patch.object(probe, "_boot_stamp", return_value="new"):
                    with mock.patch.object(probe, "_inspect", return_value=REPORT):
                        with mock.patch.object(
                                probe, "_marker_fingerprints",
                                return_value=dict(MARKERS, **{".intent": "e" * 64})):
                            with self.assertRaisesRegex(
                                    RuntimeError, "bytes dos marcadores"):
                                probe._verify(base, evidence)

    def test_wrong_os_build_refuses_before_reading_markers(self):
        probe = _load_probe()
        with tempfile.TemporaryDirectory() as temp:
            base, _target, evidence = _fixture(temp)
            with mock.patch.object(
                    probe, "_win7_sp1_version",
                    return_value=dict(VERSION, build=9999)):
                with mock.patch.object(probe, "_inspect") as inspect:
                    with self.assertRaisesRegex(RuntimeError, "build/arquitetura"):
                        probe._verify(base, evidence)
                    inspect.assert_not_called()

    def test_boot_stamp_uses_locale_independent_wmi_dmtf(self):
        probe = _load_probe()
        with mock.patch.object(probe.subprocess, "run") as runner:
            runner.return_value.returncode = 0
            runner.return_value.stdout = "20261030090000.123456-180\n"
            runner.return_value.stderr = ""
            stamp = probe._boot_stamp()
            self.assertEqual(stamp, "20261030090000.123456-180")
            command = runner.call_args.args[0]
            self.assertIn("ManagementDateTimeConverter", command[-1])
            self.assertIn("Get-WmiObject", command[-1])
            self.assertIn("-NonInteractive", command)

    def test_localized_or_invalid_boot_timestamp_is_rejected(self):
        probe = _load_probe()
        for output in ("30/10/2026 09:00:00", "10/30/2026 9:00 AM",
                       "20261030090000", "20261030090000.123456+18",
                       "20261030090000.123456-180\\nsecond", ""):
            with self.subTest(output=output):
                with mock.patch.object(probe.subprocess, "run") as runner:
                    runner.return_value.returncode = 0
                    runner.return_value.stdout = output
                    runner.return_value.stderr = ""
                    with self.assertRaisesRegex(RuntimeError, "WMI DMTF"):
                        probe._boot_stamp()

    def test_powershell_failure_refuses_to_claim_boot(self):
        probe = _load_probe()
        with mock.patch.object(probe.subprocess, "run") as runner:
            runner.return_value.returncode = 1
            runner.return_value.stdout = ""
            runner.return_value.stderr = "WMI not available"
            with self.assertRaisesRegex(RuntimeError, "consulta ao boot WMI"):
                probe._boot_stamp()

    def test_win7_sp1_version_gate(self):
        probe = _load_probe()
        for major, minor, sp in ((10, 0, 0), (6, 1, 0), (6, 2, 0), (6, 1, 1)):
            fake = SimpleNamespace(major=major, minor=minor,
                                   service_pack_major=sp, build=7601)
            with self.subTest(major=major, minor=minor, sp=sp):
                with mock.patch.object(probe.os, "name", "nt"):
                    with mock.patch.object(probe.sys, "getwindowsversion",
                                           return_value=fake, create=True):
                        with mock.patch.object(probe.platform, "machine",
                                               return_value="AMD64"):
                            if (major, minor, sp) == (6, 1, 1):
                                self.assertEqual(
                                    probe._win7_sp1_version(), VERSION)
                            else:
                                with self.assertRaisesRegex(
                                        RuntimeError, "NAO e Windows 7 SP1"):
                                    probe._win7_sp1_version()


if __name__ == "__main__":
    unittest.main()

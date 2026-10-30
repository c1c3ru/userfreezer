#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-platform negative tests for Linux VM reboot proof (#49)."""
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock


def module():
    import sys
    path = os.path.join(os.path.dirname(__file__), "packaging", "linux",
                        "overlayfs_vm_reboot_probe.py")
    spec = importlib.util.spec_from_file_location("overlayfs_vm_reboot_probe", path)
    vm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vm)
    return vm


BOOT_ONE = "12345678-1234-1234-1234-1234567890ab"
BOOT_TWO = "12345678-1234-1234-1234-1234567890cd"


class LinuxVMRebootProbeTests(unittest.TestCase):
    def setUp(self):
        self.vm = module()

    def _paths(self, directory):
        target = os.path.join(directory, "test-target")
        os.mkdir(target)
        evidence = os.path.join(directory, "record.json")
        with open(os.path.join(target, "baseline.txt"), "wb") as f:
            f.write(b"BASELINE-SHOULD-PERSIST")
        return target, evidence

    def test_same_boot_never_reports_reboot_even_when_marker_disappears(self):
        with tempfile.TemporaryDirectory() as temp:
            target, evidence = self._paths(temp)
            with mock.patch.object(self.vm, "_check_environment",
                                   side_effect=lambda target, evidence: evidence):
                with mock.patch.object(self.vm, "_boot_id", return_value=BOOT_ONE):
                    record = self.vm.prepare(target, evidence)
                os.unlink(os.path.join(target, record["marker"]))
                with mock.patch.object(self.vm, "_boot_id", return_value=BOOT_ONE):
                    with self.assertRaisesRegex(RuntimeError, "SEM REBOOT"):
                        self.vm.verify_after_reboot(target, evidence)

    def test_reboot_id_change_and_no_external_write_is_observable(self):
        with tempfile.TemporaryDirectory() as temp:
            target, evidence = self._paths(temp)
            with mock.patch.object(self.vm, "_check_environment",
                                   side_effect=lambda target, evidence: evidence):
                with mock.patch.object(self.vm, "_boot_id", return_value=BOOT_ONE):
                    record = self.vm.prepare(target, evidence)
                with mock.patch.object(self.vm, "_boot_id", return_value=BOOT_TWO):
                    with self.assertRaisesRegex(RuntimeError, "NAO foi descartada"):
                        self.vm.verify_after_reboot(target, evidence)
                    os.unlink(os.path.join(target, record["marker"]))
                    verified = self.vm.verify_after_reboot(target, evidence)
                self.assertEqual(verified["result"],
                                 "OBSERVED_LINUX_DIRECTORY_ROLLBACK_AFTER_REBOOT")
                self.assertFalse(verified["independent_vm_attestation"])
                self.assertFalse(verified["rootfs_protection_verified"])
                self.assertFalse(verified["boot_ordering_verified"])

    def test_baseline_mutation_fails_even_if_boot_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            target, evidence = self._paths(temp)
            with mock.patch.object(self.vm, "_check_environment",
                                   side_effect=lambda target, evidence: evidence):
                with mock.patch.object(self.vm, "_boot_id", return_value=BOOT_ONE):
                    record = self.vm.prepare(target, evidence)
                os.unlink(os.path.join(target, record["marker"]))
                with open(os.path.join(target, "baseline.txt"), "wb") as output:
                    output.write(b"CHANGED")
                with mock.patch.object(self.vm, "_boot_id", return_value=BOOT_TWO):
                    with self.assertRaisesRegex(RuntimeError, "baseline difere"):
                        self.vm.verify_after_reboot(target, evidence)

    def test_corrupt_journal_and_traversal_marker_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            target, evidence = self._paths(temp)
            with mock.patch.object(self.vm, "_check_environment",
                                   side_effect=lambda target, evidence: evidence):
                with mock.patch.object(self.vm, "_boot_id", return_value=BOOT_ONE):
                    self.vm.prepare(target, evidence)
                with open(evidence, "r", encoding="utf-8") as stream:
                    valid = json.load(stream)
                for marker in ("../../outside.txt", "/tmp/outside.txt",
                               "df-external-INVALID.txt"):
                    bad = dict(valid, marker=marker)
                    with open(evidence, "w", encoding="utf-8") as stream:
                        json.dump(bad, stream)
                    with mock.patch.object(self.vm, "_boot_id",
                                           return_value=BOOT_TWO):
                        with self.assertRaises(ValueError):
                            self.vm.verify_after_reboot(target, evidence)
                with open(evidence, "w", encoding="utf-8") as stream:
                    stream.write('{"schema":1,"schema":1}')
                with self.assertRaisesRegex(ValueError, "JSON de evidencias"):
                    self.vm._json_file(evidence)

    def test_persistent_volume_and_overlay_mount_are_mandatory(self):
        if os.name != "posix":
            self.skipTest("Linux-specific mount validation")
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "result.json")
            vm = self.vm
            with mock.patch.object(vm.os, "geteuid", return_value=0):
                with mock.patch.object(vm, "_require_root_owned_directory"):
                    with mock.patch.object(vm, "_findmnt",
                                           side_effect=lambda path, option:
                                           "ext4" if option == "FSTYPE" else "/mnt/evidence"):
                        with self.assertRaisesRegex(RuntimeError, "OverlayFS"):
                            vm._check_environment(vm.TEST_ROOT, path)
                    with mock.patch.object(vm, "_findmnt",
                                           side_effect=lambda path, option:
                                           "overlay" if path == vm.TEST_ROOT else
                                           "/" if option == "TARGET" else "ext4"):
                        with self.assertRaisesRegex(RuntimeError, "persistente separado"):
                            vm._check_environment(vm.TEST_ROOT, path)
                    with mock.patch.object(vm, "_findmnt",
                                           side_effect=lambda path, option:
                                           "overlay" if path == vm.TEST_ROOT else
                                           "/mnt/evidence" if option == "TARGET" else "tmpfs"):
                        with self.assertRaisesRegex(RuntimeError, "nao e persistente"):
                            vm._check_environment(vm.TEST_ROOT, path)

    def test_original_evidence_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            target, evidence = self._paths(temp)
            with open(evidence, "wb") as out:
                out.write(b"PROTECT-EVIDENCE")
            with mock.patch.object(self.vm, "_check_environment",
                                   return_value=evidence):
                with self.assertRaisesRegex(RuntimeError, "preexistente"):
                    self.vm.prepare(target, evidence)
            with open(evidence, "rb") as reader:
                self.assertEqual(reader.read(), b"PROTECT-EVIDENCE")


if __name__ == "__main__":
    unittest.main()

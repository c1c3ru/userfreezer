#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kernel observer contract checks, no WDK/driver loading in CI."""
import io
import json
import os
import pathlib
import subprocess
import unittest
from unittest import mock
from contextlib import redirect_stdout
from types import SimpleNamespace

from native.windows import audit_probe


ROOT = pathlib.Path(__file__).resolve().parent


class NativeMinifilterAuditTests(unittest.TestCase):
    def test_source_requires_optin_and_exact_ntfs_lab_volume(self):
        code = (ROOT / "native/windows/uf_audit_minifilter.c").read_text(
            encoding="utf-8")
        for required in (
            "LabAuditEnabled", "LabVolumeNtName",
            "UfValidLabVolumeName", "FltGetVolumeName",
            "RtlEqualUnicodeString", "FLT_FSTYPE_NTFS",
            "STATUS_FLT_DO_NOT_ATTACH", "STATUS_ACCESS_DENIED",
            "FltRegisterFilter", "FltStartFiltering", "FltUnregisterFilter",
            "IRP_MJ_CREATE", "IRP_MJ_WRITE", "IRP_MJ_SET_INFORMATION",
            "FLT_PREOP_SUCCESS_NO_CALLBACK",
            "gLabConfigured", "ZwClose(parameters)",
        ):
            self.assertIn(required, code)
        for dangerous in (
            "FLT_PREOP_COMPLETE", "FLT_PREOP_PENDING",
            "IoCompleteRequest(", "FltWriteFile(", "FltSetInformationFile(",
            "FltCreateFile(", "FltAllocatePoolAlignedWithTag(",
            "FltGetFileNameInformation(", "FILE_OVERWRITE_IF",
            "IRP_MJ_OPERATION_END,",
        ):
            self.assertNotIn(dangerous, code)
        self.assertNotIn(".sys", (ROOT / ".gitignore").read_text(
            encoding="utf-8") if (ROOT / ".gitignore").exists() else "")

    def test_unverified_on_non_windows(self):
        result = audit_probe.inspect(system="posix")
        self.assertEqual(result["state"], "unsupported")
        self.assertFalse(result["observer_driver_loaded"])
        self.assertFalse(result["os_level_protection_active"])
        self.assertFalse(result["driver_callback_execution_verified"])

    def test_absent_driver_never_claims_loaded(self):
        output = "Filter Name  Num Instances  Altitude    Frame\nOther 1 125000.1 0\n"
        def runner(*a, **kw):
            self.assertEqual(a[0], ["fltmc.exe", "filters"])
            self.assertFalse(kw["check"])
            return SimpleNamespace(returncode=0, stdout=output)
        r = audit_probe.inspect(system="nt", runner=runner)
        self.assertEqual(r["state"], "not-loaded")
        self.assertFalse(r["os_level_protection_active"])

    def test_loaded_driver_not_confused_with_real_protection(self):
        output = ("Filter Name            Num Instances  Altitude      Frame\n"
                  "UserFreezerAudit             1          385000.5      0\n")
        r = audit_probe.inspect(system="nt", runner=lambda *a, **kw:
                                SimpleNamespace(returncode=0, stdout=output))
        self.assertEqual(r["state"], "observer-listed-not-protection")
        self.assertTrue(r["observer_driver_loaded"])
        self.assertEqual(r["instance_count_reported"], 1)
        self.assertEqual(r["altitude_reported"], "385000.5")
        self.assertFalse(r["kernel_write_redirection_verified"])
        self.assertFalse(r["reboot_rollback_verified"])
        self.assertFalse(r["os_level_protection_active"])

    def test_zero_instances_not_proof_of_attachment(self):
        r = audit_probe.inspect(system="nt", runner=lambda *a, **kw:
                                SimpleNamespace(returncode=0, stdout=
                                                "UserFreezerAudit 0 385000.5 0\n"))
        self.assertTrue(r["observer_driver_loaded"])
        self.assertEqual(r["instance_count_reported"], 0)
        self.assertFalse(r["driver_callback_execution_verified"])

    def test_rejects_substrings_duplicate_and_oversize(self):
        self.assertIsNone(audit_probe.parse_filters(
            "FooUserFreezerAudit 1 385000.5 0\n"))
        with self.assertRaises(ValueError):
            audit_probe.parse_filters("UserFreezerAudit 1 385000.5 0\n" * 2)
        with self.assertRaises(ValueError):
            audit_probe.parse_filters("x" * 262145)
        with self.assertRaises(ValueError):
            audit_probe.parse_filters("UserFreezerAudit 65536 385000.5 0")

    def test_failed_fl_tmc_not_healthy(self):
        for runner in (
            lambda *a, **kw: SimpleNamespace(returncode=1, stdout=""),
            lambda *a, **kw: (_ for _ in ()).throw(OSError("not found")),
            lambda *a, **kw: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("fltmc", 5)),
        ):
            with self.subTest(runner=runner):
                state = audit_probe.inspect(system="nt", runner=runner)
                self.assertEqual(state["state"], "error")
                self.assertFalse(state["os_level_protection_active"])

    def test_probe_cli_local_is_safely_conservative(self):
        synthetic = audit_probe.inspect(system="posix")
        with mock.patch.object(audit_probe, "inspect", return_value=synthetic):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(audit_probe.main([]), 0)
        doc = json.loads(output.getvalue())
        self.assertFalse(doc["os_level_protection_active"])
        self.assertFalse(doc["reboot_rollback_verified"])


if __name__ == "__main__":
    unittest.main()

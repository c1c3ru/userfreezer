#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline volume wizard security contracts. No Windows driver installed."""
import json
import os
import tempfile
import unittest

from ui.offline_protection_plan import (
    make_protection_plan, save_proposal_create_only,
)

CAPABILITY = {"strategy": "uwf"}


def plan(**kw):
    defaults = {
        "mode": "windows", "persistent_drive": "D:",
        "capability": CAPABILITY, "admin_consent": True,
        "backup_confirmed": True,
    }
    defaults.update(kw)
    return make_protection_plan(**defaults)


class OfflineProtectionProposalTests(unittest.TestCase):
    def test_default_windows_volume_different_from_persistent(self):
        value = plan()
        self.assertEqual(value["proposed_system_volume"], "C:")
        self.assertEqual(value["persistent_drive"], "D:")
        self.assertEqual(value["activation_state"], "NOT_STARTED")
        self.assertFalse(value["external_write_rollback_verified"])
        self.assertFalse(value["service_configuration_applied"])
        self.assertFalse(value["reboot_verified"])
        self.assertTrue(value["offline"])

    def test_consent_and_snapshot_both_required(self):
        for key in ("admin_consent", "backup_confirmed"):
            with self.subTest(key=key), self.assertRaises(PermissionError):
                plan(**{key: False})

    def test_cannot_call_user_profile_a_persistent_volume(self):
        for candidate in ("C:", "c:", r"C:\Users\test", "C", "\\\\server\\share",
                          "all", "", None):
            with self.subTest(value=candidate), self.assertRaises(ValueError):
                plan(persistent_drive=candidate)

    def test_unsupported_backend_never_becomes_approved(self):
        for strategy in ("unsupported", "vhdx_diff", "ewf_fbwf"):
            with self.subTest(strategy=strategy):
                item = plan(capability={"strategy": strategy})
                self.assertEqual(item["detected_backend"], strategy)
                self.assertEqual(item["activation_state"], "NOT_STARTED")
        with self.assertRaises(ValueError):
            plan(capability={"strategy": "unknown_backdoor"})

    def test_other_system_drive_is_not_implicitly_protected(self):
        with self.assertRaises(ValueError):
            plan(system_drive="E:")

    def test_folder_selection_is_not_file_filter_or_persistent_area(self):
        item = make_protection_plan(
            "folder", folder=r"C:\Users\lab\Documents",
            capability=CAPABILITY, admin_consent=True, backup_confirmed=True)
        self.assertEqual(item["selected_folder"], r"C:\Users\lab\Documents")
        self.assertIsNone(item["persistent_drive"])
        self.assertFalse(item["service_configuration_applied"])
        for bad in ("relative/path", r"\\server\share", r"C:\Users\..\Windows",
                    "C:", ""):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                make_protection_plan(
                    "folder", folder=bad, capability=CAPABILITY,
                    admin_consent=True, backup_confirmed=True)

    def test_export_never_overwrites_existing_consent_or_service_config(self):
        with tempfile.TemporaryDirectory() as td:
            output = os.path.join(td, "plan.json")
            saved = save_proposal_create_only(plan(), output)
            with open(output, "rb") as stream:
                data = stream.read()
            self.assertEqual(saved, len(data))
            self.assertEqual(json.loads(data)["activation_state"], "NOT_STARTED")
            with self.assertRaises(FileExistsError):
                save_proposal_create_only(plan(), output)
            with open(output, "rb") as stream:
                self.assertEqual(stream.read(), data)

    def test_stage_script_requires_disposable_vm_and_does_not_reboot(self):
        path = os.path.join(
            os.path.dirname(__file__), "packaging", "windows",
            "os_level", "uwf_lab_stage.ps1")
        with open(path, encoding="utf-8") as stream:
            script = stream.read()
        for required in (
            "ConfirmDisposableVM", "ConfirmBackupSnapshot",
            "ConfirmDiscardWritesAfterReboot",
            "UWF_Filter", "UWF_Volume", "filter enable",
            "volume protect", "Win32_LogicalDisk",
            "PENDING_REBOOT_NOT_PROTECTED_YET",
            "PROVA DE ROLLBACK EXTERNO: NAO EXECUTADA",
            "Windows Home/Pro nao suportado"):
            with self.subTest(field=required):
                self.assertIn(required, script)
        self.assertNotIn("Restart-Computer", script)
        self.assertNotIn("uwfmgr.exe filter restart", script)
        self.assertNotIn("New-Partition", script)
        self.assertNotIn("bcdedit.exe", script)


if __name__ == "__main__":
    unittest.main()

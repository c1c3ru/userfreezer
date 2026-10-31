#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Protect users against silent installation / misleading 'frozen' labels."""
import os
import unittest
from unittest import mock

from ui.protection_setup import capability_info, local_capability


_ROOT = os.path.dirname(os.path.abspath(__file__))


def _read(path):
    with open(os.path.join(_ROOT, path.replace("/", os.sep)), encoding="utf-8") as f:
        return f.read()


class WindowsProtectionModeTests(unittest.TestCase):
    def test_windows7_professional_no_external_write_filter(self):
        result = capability_info(7601, "Professional")
        self.assertEqual(result["strategy"], "unsupported")
        self.assertFalse(result["external_write_rollback_available"])
        self.assertFalse(result["os_filter_verified"])
        self.assertIn("Windows 7", result["description"])

    def test_windows7_embedded_is_possible_but_not_verified(self):
        result = capability_info(7601, "EmbeddedStandard")
        self.assertEqual(result["strategy"], "ewf_fbwf")
        self.assertFalse(result["external_write_rollback_available"])
        self.assertFalse(result["reboot_verified"])

    def test_uwf_possible_is_not_equivalent_to_enabled(self):
        result = capability_info(19045, "Enterprise")
        self.assertEqual(result["strategy"], "uwf")
        self.assertFalse(result["os_filter_verified"])
        self.assertFalse(result["external_write_rollback_available"])

    def test_home_pro_not_marked_protected_by_experimental_vhdx(self):
        result = capability_info(19045, "Professional")
        self.assertEqual(result["strategy"], "vhdx_diff")
        self.assertFalse(result["external_write_rollback_available"])

    def test_no_windows_never_reports_protection(self):
        if os.name == "nt":
            self.skipTest("non-Windows-only regression")
        result = local_capability()
        self.assertEqual(result["strategy"], "unsupported")
        self.assertFalse(result["external_write_rollback_available"])

    def test_installer_is_explicit_about_empty_targets(self):
        installer = _read("packaging/windows/install_service_exe.ps1")
        self.assertIn("'{\"targets\": []}'", installer)
        self.assertIn("NAO faz rollback", installer)
        self.assertIn("filtro OS-level", installer)
        self.assertIn("diagnose_protection.ps1", installer)

    def test_diagnostic_only_reads_status_and_configuration(self):
        diagnostic = _read("packaging/windows/diagnose_protection.ps1")
        self.assertIn("Get-Service", diagnostic)
        self.assertIn("Get-WmiObject", diagnostic)
        self.assertIn("uwfmgr.exe filter get-config", diagnostic)
        self.assertIn("SEM ALVOS", diagnostic)
        self.assertIn("NAO COMPROVADA", diagnostic)
        for banned in ("diskpart", "bcdedit.exe /set", "filter enable",
                       "volume protect", "Remove-Item", "New-Item",
                       "Start-Service", "ConvertFrom-Json"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, diagnostic)

    def test_ui_choice_does_not_write_config_or_enable_filter(self):
        gui = _read("ui/protection_setup.py")
        self.assertIn('value="windows"', gui)
        self.assertIn('value="profile"', gui)
        self.assertIn('value="folder"', gui)
        self.assertIn("Nao foi", gui)
        self.assertIn("NAO ATIVADO", gui)
        self.assertNotIn("subprocess.run(", gui)
        self.assertNotIn("winreg.SetValue", gui)

    def test_service_gui_entry_does_not_bypass_scm_enforcement(self):
        service = _read("packaging/windows/deepfreezer_service.py")
        self.assertIn('sys.argv[1] == "--ui"', service)
        self.assertIn("def _launch_admin_panel()", service)
        self.assertIn("servicemanager.StartServiceCtrlDispatcher()", service)
        workflow = _read(".github/workflows/build-packages.yml")
        self.assertEqual(workflow.count("--hidden-import ui.health_panel"), 2)
        self.assertEqual(workflow.count("--hidden-import ui.protection_setup"), 2)
        self.assertIn("packaging/windows/diagnose_protection.ps1", workflow)


if __name__ == "__main__":
    unittest.main()

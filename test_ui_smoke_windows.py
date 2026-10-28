#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Teste de interface REAL Tk Windows: multialvos, overlay custom, status.

Nao testa Windows 7 SP1 nem UAC (requer VM/sessao interativa manual).
A UI nao importa/configura o servico privilegiado nem executa mutacoes.
"""
import os
import unittest
from unittest import mock

try:
    import tkinter as tk
    from ui import health_panel
except ImportError:
    tk = None
    health_panel = None


@unittest.skipUnless(os.name == "nt", "GUI Windows")
@unittest.skipIf(tk is None or health_panel is None, "Tk nao instalado")
class WindowsPanelSmokeTests(unittest.TestCase):
    def test_painel_real_com_multiplos_alvos_e_kernel_independente(self):
        snapshot = {
            "state": "degraded", "timestamp": "2026-10-28T00:00:00Z",
            "scope": "application-level", "targets": [
                {
                    "target": r"C:\\LAB_A", "overlay": r"D:\\CUSTOM_A.dfz",
                    "state": "healthy", "frozen": True,
                    "baseline_paths": 42, "pending_ops": {"W": 2},
                    "overlay_bytes": 2048, "overlay_size_partial": False,
                    "os_level": {
                        "state": "unverified", "strategy": "unknown",
                        "scope": "unknown", "reboot_verified": False,
                    },
                },
                {
                    "target": r"C:\\LAB_B", "overlay": r"C:\\LAB_B.dfz",
                    "state": "error", "frozen": None, "baseline_paths": 0,
                    "pending_ops": {}, "overlay_bytes": None,
                    "overlay_size_partial": False, "error": "ACL recusada",
                    "os_level": {
                        "state": "unverified", "strategy": "unknown",
                        "scope": "unknown", "reboot_verified": False,
                    },
                },
            ],
        }
        root = tk.Tk()
        root.withdraw()
        try:
            with mock.patch.object(health_panel, "request",
                                   return_value={"ok": True, "result": snapshot}):
                panel = health_panel.AdminPanel(root)
                root.update_idletasks()
                rows = panel.table.get_children()
                self.assertEqual(len(rows), 2)
                self.assertEqual(
                    panel.table.set(rows[0], "target"), r"C:\\LAB_A")
                self.assertIn("D:\\CUSTOM_A.dfz",
                              panel.table.set(rows[0], "overlay"))
                self.assertIn("unverified",
                              panel.table.set(rows[0], "os_level"))
                self.assertIn("ACL recusada",
                              panel.table.set(rows[1], "error"))
                self.assertIn("degraded", panel.status.cget("text"))
                panel.table.selection_set(rows[1])
                self.assertEqual(panel.selected_target(), r"C:\\LAB_B")

                with mock.patch.object(health_panel, "run_admin_action") as elevation, \
                     mock.patch.object(health_panel.messagebox, "showerror") as alert:
                    panel.action("commit")
                elevation.assert_not_called()
                alert.assert_called_once()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()

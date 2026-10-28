#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testa a autorização de UI sem abrir sessão Tk nem elevar privilégios."""
import os
import unittest
from unittest import mock

try:
    from ui import health_panel
except ImportError:
    health_panel = None


@unittest.skipIf(health_panel is None, "Tkinter nao instalado neste runner")
class UIActionAuthorizationTests(unittest.TestCase):
    def panel(self):
        panel = object.__new__(health_panel.AdminPanel)
        panel.root = object()
        panel.selected_target = lambda: os.path.abspath("alvo-de-teste")
        panel.socket_path = None
        panel.refresh = mock.Mock()
        return panel

    @unittest.skipUnless(os.name == "nt", "bloqueio Win32")
    def test_commit_windows_nao_eleva_nem_executa_acao(self):
        panel = self.panel()
        with mock.patch.object(health_panel, "run_admin_action") as elevate, \
             mock.patch.object(health_panel.messagebox, "showerror") as error, \
             mock.patch.object(health_panel.simpledialog, "askstring") as confirm:
            panel.action("commit")
        elevate.assert_not_called()
        confirm.assert_not_called()
        error.assert_called_once()

    def test_cancelar_operacao_destrutiva_nao_executa_helper(self):
        panel = self.panel()
        with mock.patch.object(health_panel, "run_admin_action") as elevate, \
             mock.patch.object(health_panel.messagebox, "showerror"), \
             mock.patch.object(health_panel.simpledialog, "askstring",
                               return_value="NAO CONFIRMADO"):
            panel.action("discard")
        elevate.assert_not_called()

    def test_freeze_cancelado_nao_solicita_elevacao(self):
        panel = self.panel()
        with mock.patch.object(health_panel, "run_admin_action") as elevate, \
             mock.patch.object(health_panel.messagebox, "askyesno",
                               return_value=False):
            panel.action("freeze")
        elevate.assert_not_called()

    def test_freeze_aprovado_delega_ao_helper(self):
        panel = self.panel()
        with mock.patch.object(health_panel, "run_admin_action",
                               return_value=True) as elevate, \
             mock.patch.object(health_panel.messagebox, "askyesno",
                               return_value=True), \
             mock.patch.object(health_panel.messagebox, "showinfo"):
            panel.action("freeze")
        elevate.assert_called_once_with("freeze", panel.selected_target(), None)
        panel.refresh.assert_called_once()


if __name__ == "__main__":
    unittest.main()

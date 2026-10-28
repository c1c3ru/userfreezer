#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Autostart deve agir SOMENTE no perfil do usuario, sem root/UAC."""
import os
import tempfile
import unittest
from unittest import mock
from ui import autostart


class AutostartTests(unittest.TestCase):
    def test_desktop_entry_escapa_argumentos_e_nao_executa_shell(self):
        data = autostart.desktop_entry("/bin/python3",
                                       '/home/user/dir $(touch bad);%/tray.py')
        self.assertIn('Exec="/bin/python3"', data)
        self.assertIn('\\$(', data)
        self.assertIn('%%', data)
        self.assertIn("Terminal=false", data)
        self.assertNotIn("/bin/sh", data)

    @unittest.skipIf(os.name == "nt", "XDG Linux")
    def test_install_remove_no_perfil_sem_escrever_sistema(self):
        with tempfile.TemporaryDirectory() as tmp:
            tray = os.path.join(tmp, "tray.py")
            with open(tray, "w", encoding="utf-8") as out:
                out.write("pass\n")
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                path = autostart.install(tray_path=tray)
                self.assertTrue(path.startswith(tmp))
                self.assertTrue(os.path.isfile(path))
                with open(path, encoding="utf-8") as f:
                    self.assertIn("Exec=", f.read())
                self.assertFalse(os.stat(path).st_mode & 0o077)
                self.assertTrue(autostart.remove())
                self.assertFalse(autostart.remove())
                self.assertFalse(os.path.exists(path))

    @unittest.skipIf(os.name == "nt", "XDG Linux")
    def test_xdg_relativo_negado(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}):
            with self.assertRaises(ValueError):
                autostart.remove()

    @unittest.skipUnless(os.name == "nt", "registro Windows")
    def test_registro_somente_hkcu_sem_sistema(self):
        import types
        context = mock.MagicMock()
        fake = types.SimpleNamespace(
            HKEY_CURRENT_USER=1234, KEY_SET_VALUE=0x2, REG_SZ=1,
            CreateKeyEx=mock.Mock(return_value=context),
            SetValueEx=mock.Mock())
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict("sys.modules", {"winreg": fake}):
            tray = os.path.join(tmp, "tray.py")
            with open(tray, "w", encoding="utf-8") as out:
                out.write("pass\n")
            autostart.install(tray_path=tray)
        args = fake.CreateKeyEx.call_args[0]
        self.assertEqual(args[0], fake.HKEY_CURRENT_USER)
        self.assertEqual(args[1], autostart.RUN_KEY)
        fake.SetValueEx.assert_called_once()


if __name__ == "__main__":
    unittest.main()

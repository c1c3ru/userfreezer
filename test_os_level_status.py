#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prova de estado OS-level separado de saúde da API."""
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from os_level_status import probe_target


class OSLevelRuntimeStatusTests(unittest.TestCase):
    def test_windows_sem_filtro_comprovado_nao_diz_active(self):
        r = probe_target(r"C:\\Teste", system="nt")
        self.assertEqual(r["state"], "unverified")
        self.assertFalse(r["reboot_verified"])
        self.assertEqual(r["scope"], "unknown")

    @unittest.skipIf(os.name == "nt", "Linux path")
    def test_mount_overlay_do_kernel_e_active_somente_por_diretorio(self):
        with tempfile.TemporaryDirectory() as root:
            run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="overlay\n"))
            r = probe_target(root, system="posix", runner=run)
            self.assertEqual(r["state"], "active")
            self.assertEqual(r["strategy"], "overlayfs")
            self.assertEqual(r["scope"], "os-level-directory")
            self.assertFalse(r["reboot_verified"])
            self.assertEqual(run.call_args[0][0][-1], root)

    @unittest.skipIf(os.name == "nt", "Linux path")
    def test_diretorio_comum_ou_mount_nao_overlay_e_inactive(self):
        with tempfile.TemporaryDirectory() as root:
            for rc, fs in ((1, ""), (0, "ext4\n"), (0, "tmpfs\n")):
                with self.subTest(rc=rc, fs=fs):
                    r = probe_target(root, "posix", lambda *a, **kw:
                                     SimpleNamespace(returncode=rc, stdout=fs))
                    self.assertEqual(r["state"], "inactive")
                    self.assertFalse(r["reboot_verified"])

    @unittest.skipIf(os.name == "nt", "Linux path")
    def test_symlink_e_diretorio_inexistente_nao_reutiliza_status(self):
        with tempfile.TemporaryDirectory() as root:
            link = os.path.join(root, "link")
            os.symlink(root, link)
            self.assertEqual(probe_target(link, "posix")["state"], "error")
            self.assertEqual(probe_target(os.path.join(root, "missing"), "posix")["state"], "error")

    @unittest.skipIf(os.name == "nt", "Linux path")
    def test_findmnt_timeout_falha_fechado(self):
        with tempfile.TemporaryDirectory() as root:
            def failing(*a, **kw):
                raise subprocess.TimeoutExpired("findmnt", 2)
            r = probe_target(root, "posix", failing)
            self.assertEqual(r["state"], "error")
            self.assertNotEqual(r["error"], "")

    @unittest.skipIf(os.name == "nt", "Linux path")
    def test_findmnt_erro_nao_e_healthy(self):
        with tempfile.TemporaryDirectory() as root:
            r = probe_target(root, "posix", lambda *a, **kw:
                             SimpleNamespace(returncode=2, stdout=""))
            self.assertEqual(r["state"], "error")


if __name__ == "__main__":
    unittest.main()

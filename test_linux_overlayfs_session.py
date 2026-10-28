#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import importlib.util
import os
import tempfile
import unittest
from unittest import mock

PATH = os.path.join(os.path.dirname(__file__), "packaging", "linux", "overlayfs_session.py")
spec = importlib.util.spec_from_file_location("df_linux_overlayfs", PATH)
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)


class OverlayFsSafetyTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "path de teste somente Linux")
    def test_dry_run_nao_monta_e_nao_exige_root(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "alvo")
            os.mkdir(target)
            with mock.patch.object(overlay, "_mount") as mount:
                plan = overlay.activate(target, 64, dry_run=True)
            self.assertEqual(plan["state"], "pending-activation")
            self.assertEqual(plan["scope"], "os-level-directory")
            self.assertEqual(len(plan["commands"]), 2)
            self.assertIn("lowerdir=", plan["commands"][1][4])
            mount.assert_not_called()

    @unittest.skipIf(os.name == "nt", "path de teste somente Linux")
    def test_negar_montagem_sem_aceite_explicito(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "alvo")
            os.mkdir(target)
            with self.assertRaises(overlay.OSLevelError):
                overlay.activate(target, accepted=False)

    @unittest.skipIf(os.name == "nt", "path de teste somente Linux")
    def test_rejeita_symlink_e_delimitador_de_mount(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "alvo")
            os.mkdir(target)
            symlink = os.path.join(root, "link")
            os.symlink(target, symlink)
            for bad in (symlink, target + ",upperdir=/etc",
                        "/", "/etc", root + "/../etc", "relativo"):
                with self.subTest(path=bad):
                    with self.assertRaises(overlay.OSLevelError):
                        overlay.activate(bad, dry_run=True)

    def test_status_usa_findmnt_em_vez_de_status_da_api(self):
        with mock.patch.object(overlay.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "overlay\n"
            self.assertEqual(overlay.protection_status("/srv/test"), "active")
            run.return_value.stdout = "ext4\n"
            self.assertEqual(overlay.protection_status("/srv/test"), "unsupported")

    def test_diretorio_normal_nao_e_reportado_como_protegido(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(overlay.subprocess, "run") as run:
                run.return_value.returncode = 1
                run.return_value.stdout = ""
                self.assertEqual(overlay.protection_status(root), "inactive")
                self.assertEqual(
                    overlay.protection_status(os.path.join(root, "ausente")),
                    "error")

    @unittest.skipIf(os.name == "nt", "Linux")
    def test_recusa_sobreposicao_com_daemon_application_level(self):
        import json
        with tempfile.TemporaryDirectory() as root:
            cfg = os.path.join(root, "config.json")
            target = os.path.join(root, "target")
            os.makedirs(os.path.join(target, "child"))
            for configured in (target, root, os.path.join(target, "child")):
                with self.subTest(configured=configured):
                    with open(cfg, "w", encoding="utf-8") as out:
                        json.dump({"targets": [{"target": configured}]}, out)
                    with self.assertRaises(overlay.OSLevelError):
                        overlay.reject_api_target_overlap(target, cfg)
            with open(cfg, "w", encoding="utf-8") as out:
                json.dump({"targets": [{"target": "/srv/another"}]}, out)
            overlay.reject_api_target_overlap(target, cfg)

    def test_guard_config_corrompida_falha_fechado(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "broken.json")
            with open(path, "w", encoding="utf-8") as out:
                out.write("{invalid")
            with self.assertRaises(overlay.OSLevelError):
                overlay.reject_api_target_overlap("/srv/alvo", path)

    def test_unit_boot_nao_tem_start_automatico_na_politica(self):
        path = os.path.join(os.path.dirname(__file__), "packaging",
                            "linux", "deepfreezer-overlayfs@.service")
        with open(path, encoding="utf-8") as out:
            unit = out.read()
        for token in ("Type=oneshot", "RemainAfterExit=yes",
                      "--target %f", "--guard-config /etc/deepfreezer/config.json",
                      "--i-accept-volatile-protection"):
            self.assertIn(token, unit)
        self.assertNotIn("ExecStop=", unit)

    def test_limites_da_memoria_da_montagem(self):
        with mock.patch.object(overlay, "_safe_absolute", return_value="/srv/alvo"):
            for size in (-1, 0, 15, 4097):
                with self.assertRaises(overlay.OSLevelError):
                    overlay.activate("/srv/alvo", size, dry_run=True)


if __name__ == "__main__":
    unittest.main()

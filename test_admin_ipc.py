#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import uuid

from admin_ipc import (Broker, ProtocolError, decode_message, request_unix,
                       serve_unix)


def msg(action, target=None, confirm=None):
    obj = {"v": 1, "id": str(uuid.uuid4()), "action": action}
    if target is not None:
        obj["target"] = target
    if confirm is not None:
        obj["confirm"] = confirm
    return json.dumps(obj).encode("utf-8")


class BrokerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = os.path.join(self.temp.name, "alvo")
        os.makedirs(self.target)
        self.config = os.path.join(self.temp.name, "config.json")
        self.status = os.path.join(self.temp.name, "status.json")
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump({"targets": [{"target": self.target,
                                     "overlay": os.path.join(self.temp.name, "custom.dfz")}]}, f)
        with open(self.status, "w", encoding="utf-8") as f:
            json.dump({"state": "healthy", "protection_scope": "application-level",
                       "last_enforcement_utc": "2026-10-28T00:00:00Z",
                       "targets": [{"target": self.target, "state": "healthy"}]}, f)
        self.audit = []
        self.broker = Broker(self.config, self.status, audit=self.audit.append)

    def test_overlay_usage_limita_sem_seguir_symlinks(self):
        from admin_ipc import overlay_usage
        root = os.path.join(self.temp.name, "payloads")
        os.mkdir(root)
        with open(os.path.join(root, "a.txt"), "wb") as f:
            f.write(b"1234567")
        self.assertEqual(overlay_usage(root), (7, False))
        self.assertEqual(overlay_usage(root, file_limit=0), (0, True))

    def test_resposta_status_sem_segredos_e_com_overlay_personalizado(self):
        response = self.broker.process(msg("status"), is_admin=False, identity="uid=1000")
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["scope"], "application-level")
        self.assertEqual(response["result"]["targets"][0]["overlay"],
                         os.path.join(self.temp.name, "custom.dfz"))

    def test_status_os_level_independente_de_healthy(self):
        from unittest import mock
        observation = {
            "state": "active", "strategy": "overlayfs",
            "scope": "os-level-directory", "source": "kernel-findmnt",
            "reboot_verified": False, "error": "",
        }
        with mock.patch("admin_ipc.probe_target", return_value=observation):
            reply = self.broker.process(msg("status"), is_admin=False)
        self.assertTrue(reply["ok"], reply)
        row = reply["result"]["targets"][0]
        self.assertEqual(row["state"], "healthy")
        self.assertEqual(row["os_level"]["state"], "active")
        self.assertEqual(row["os_level"]["scope"], "os-level-directory")
        self.assertFalse(row["os_level"]["reboot_verified"])
        self.assertEqual(reply["result"]["scope"], "application-level")

    def test_windows_sem_sinal_kernel_deve_ser_unverified(self):
        from unittest import mock
        observation = {
            "state": "unverified", "strategy": "unknown",
            "scope": "unknown", "source": "not-checked",
            "reboot_verified": False,
            "error": "filtro Windows nao consultado",
        }
        with mock.patch("admin_ipc.probe_target", return_value=observation):
            reply = self.broker.process(msg("status"))
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["result"]["targets"][0]["os_level"]["state"],
                         "unverified")

    def test_usuario_normal_nao_pode_mutar_mesmo_que_forje_confirmacao(self):
        for action in ("freeze", "discard", "commit"):
            with self.subTest(action=action):
                response = self.broker.process(
                    msg(action, self.target, action.upper() + " " + self.target),
                    is_admin=False, identity="uid=1000")
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "PermissionError")
        self.assertFalse(os.path.exists(os.path.join(self.temp.name, "custom.dfz")))

    def test_admin_freeze_discard_aceita_somente_alvos_cadastrados(self):
        other = os.path.join(self.temp.name, "outro")
        os.makedirs(other)
        bad = self.broker.process(msg("freeze", other), is_admin=True)
        self.assertFalse(bad["ok"])
        a = self.broker.process(msg("freeze", self.target), is_admin=True)
        self.assertTrue(a["ok"], a)
        self.assertTrue(a["result"]["frozen"])
        b = self.broker.process(msg("discard", self.target), is_admin=True)
        self.assertFalse(b["ok"], "Precisa de confirmacao explicita")
        prepare = json.dumps({"v": 1, "id": str(uuid.uuid4()),
                              "action": "prepare", "operation": "discard",
                              "target": self.target}).encode("utf-8")
        chall = self.broker.process(prepare, is_admin=True, identity="uid=0")
        self.assertTrue(chall["ok"], chall)
        token = chall["result"]["token"]
        c = self.broker.process(msg("discard", self.target, token),
                                is_admin=True, identity="uid=0")
        self.assertTrue(c["ok"], c)
        self.assertFalse(c["result"]["frozen"])
        replay = self.broker.process(msg("discard", self.target, token),
                                     is_admin=True, identity="uid=0")
        self.assertFalse(replay["ok"], "nonce nao pode ser reutilizado")

    def test_nonce_vinculado_ao_peer_e_acao(self):
        prepare = json.dumps({"v": 1, "id": str(uuid.uuid4()),
                              "action": "prepare", "operation": "commit",
                              "target": self.target}).encode("utf-8")
        a = self.broker.process(prepare, True, "uid=0")
        self.assertTrue(a["ok"], a)
        token = a["result"]["token"]
        b = self.broker.process(msg("commit", self.target, token),
                                True, "uid=999")
        self.assertFalse(b["ok"])
        c = self.broker.process(msg("commit", self.target, token),
                                True, "uid=0")
        self.assertFalse(c["ok"], "token consumido mesmo se usuario incorreto")

    def test_duplicate_fields_json_and_path_not_trusted(self):
        invalid = [
            b'{"v":1,"v":1,"id":"bad","action":"status"}',
            b'{"v":1,"id":"bad","action":"status"}',
            msg("freeze", self.target) + b" " * 17000,
            b'["not","a","request"]',
            msg("unknown"),
        ]
        for raw in invalid:
            with self.subTest(raw=raw[:25]):
                with self.assertRaises(ProtocolError):
                    decode_message(raw)

    @unittest.skipIf(os.name == "nt", "Unix socket")
    def test_socket_recusa_diretorio_gravavel_por_outros(self):
        from admin_ipc import _validate_unix_socket_directory
        folder = os.path.join(self.temp.name, "unsafe")
        os.mkdir(folder)
        os.chmod(folder, 0o777)
        try:
            with self.assertRaises(RuntimeError):
                _validate_unix_socket_directory(folder)
            with self.assertRaises(RuntimeError):
                serve_unix(self.broker, os.path.join(folder, "admin.sock"),
                           threading.Event())
        finally:
            os.chmod(folder, 0o700)

    @unittest.skipIf(os.name == "nt", "Unix socket")
    def test_socket_recusa_ancestral_symlink(self):
        from admin_ipc import _validate_unix_socket_directory
        original = os.path.join(self.temp.name, "real")
        linked = os.path.join(self.temp.name, "link")
        os.mkdir(original)
        os.symlink(original, linked)
        with self.assertRaises(RuntimeError):
            _validate_unix_socket_directory(linked)
        with self.assertRaises(RuntimeError):
            serve_unix(self.broker, os.path.join(linked, "admin.sock"),
                       threading.Event())

    @unittest.skipIf(os.name == "nt", "Unix socket")
    def test_socket_aceita_diretorio_privado(self):
        from admin_ipc import _validate_unix_socket_directory
        _validate_unix_socket_directory(self.temp.name)

    @unittest.skipIf(os.name == "nt", "Unix socket")
    def test_unix_socket_peercred_status_para_nao_root(self):
        path = os.path.join(self.temp.name, "admin.sock")
        stop = threading.Event()
        errors = []
        def run():
            try:
                serve_unix(self.broker, path, stop)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()
        for _ in range(100):
            if os.path.exists(path):
                break
            time.sleep(0.01)
        try:
            self.assertTrue(os.path.exists(path))
            reply = request_unix(path)
            self.assertTrue(reply["ok"], reply)
            # O teste SO_PEERCRED usa o UID real do runner; em UID 0 o
            # usuario e efetivamente admin, caso contrario deve negar.
            resp = request_unix(path, "freeze", self.target)
            self.assertEqual(resp["ok"], os.geteuid() == 0)
        finally:
            stop.set()
            thread.join(timeout=3)
        self.assertFalse(errors, errors)


if __name__ == "__main__":
    unittest.main()

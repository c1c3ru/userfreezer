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

    def test_resposta_status_sem_segredos_e_com_overlay_personalizado(self):
        response = self.broker.process(msg("status"), is_admin=False, identity="uid=1000")
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["scope"], "application-level")
        self.assertEqual(response["result"]["targets"][0]["overlay"],
                         os.path.join(self.temp.name, "custom.dfz"))

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
        c = self.broker.process(
            msg("discard", self.target, "DISCARD " + self.target), is_admin=True)
        self.assertTrue(c["ok"], c)
        self.assertFalse(c["result"]["frozen"])

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

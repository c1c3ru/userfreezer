#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import admin_client
from ui.admin_elevation import _client_args, trusted_linux_client


class ElevationContractTests(unittest.TestCase):
    def test_paths_nao_sao_executados_pelo_shell(self):
        target = r"C:\Safe Folder\with spaces"
        if os.name != "nt":
            target = "/tmp/safe folder"
        self.assertEqual(_client_args("commit", target),
                         ["approve-commit", "--target", target])
        self.assertEqual(_client_args("discard", target),
                         ["approve-discard", "--target", target])
        with self.assertRaises(ValueError):
            _client_args("arbitrary-action", target)

    @unittest.skipIf(os.name == "nt", "Linux trusted client")
    def test_script_de_origem_nao_pode_ser_elevado(self):
        with tempfile.TemporaryDirectory() as temp:
            file_path = os.path.join(temp, "client.py")
            with open(file_path, "w") as fh:
                fh.write("# untrusted")
            self.assertFalse(trusted_linux_client(file_path))

    def test_cliente_elevado_usa_nonce_mesmo_processo(self):
        target = os.path.abspath(os.path.join(os.getcwd(), "safe-test"))
        responses = []
        def fake_request(action="status", target=None, confirm=None,
                         operation=None, socket_path=None):
            responses.append((action, target, confirm, operation))
            if action == "prepare":
                return {"ok": True, "result": {"token": "one-time-token"}}
            return {"ok": True, "result": {"action": action}}
        with mock.patch.object(admin_client, "request", side_effect=fake_request):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = admin_client.main(["approve-commit", "--target", target])
        self.assertEqual(rc, 0)
        self.assertEqual(responses[0], ("prepare", target, None, "commit"))
        self.assertEqual(responses[1], ("commit", target, "one-time-token", None))

    def test_cliente_nao_envia_comando_quando_prepare_negado(self):
        target = os.path.abspath("test")
        with mock.patch.object(admin_client, "request",
                               return_value={"ok": False,
                                             "error": {"message": "denied"}}) as f:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = admin_client.main(["approve-discard", "--target", target])
        self.assertEqual(rc, 1)
        self.assertEqual(f.call_count, 1)


if __name__ == "__main__":
    unittest.main()

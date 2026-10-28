#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke real named pipe + identidade do kernel nos runners Windows."""
import json
import logging
import os
import tempfile
import threading
import time
import unittest
import uuid

from admin_ipc import Broker


@unittest.skipUnless(os.name == "nt", "Named pipes Win32 apenas Windows")
class WindowsPipeIntegrationTests(unittest.TestCase):
    def test_pipe_acl_and_two_clients(self):
        try:
            import win32pipe
            import admin_ipc_win as ipc
        except ImportError:
            self.skipTest("pywin32 nao instalado no ambiente de testes")
        name = ipc.PIPE_NAME
        ipc.PIPE_NAME = r"\\.\pipe\DeepFreezer-Test-" + str(uuid.uuid4())
        stop = threading.Event()
        errors = []
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "target")
            os.mkdir(root)
            cfg = os.path.join(tmp, "cfg.json")
            stat = os.path.join(tmp, "state.json")
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump({"targets": [{"target": root}]}, f)
            with open(stat, "w", encoding="utf-8") as f:
                json.dump({"protection_scope": "application-level",
                           "state": "healthy", "targets": [
                               {"target": root, "state": "healthy"}]}, f)
            broker = Broker(cfg, stat)
            def run():
                try:
                    ipc.serve_windows(broker, stop, logging.getLogger(__name__))
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=run)
            thread.daemon = True
            thread.start()
            try:
                # Probe de status pode conectar e fechar sem enviar JSON;
                # isso nao deve matar a thread do servico.
                import win32file
                import win32con
                win32pipe.WaitNamedPipe(ipc.PIPE_NAME, 5000)
                probe = win32file.CreateFile(
                    ipc.PIPE_NAME, win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                    0, None, win32con.OPEN_EXISTING, 0, None)
                win32file.CloseHandle(probe)
                time.sleep(0.1)
                # A primeira chamada testa autenticação por token após
                # ReadFile. A segunda exige reutilizacao do handle seguro.
                for attempt in range(20):
                    try:
                        a = ipc.request_windows()
                        break
                    except (OSError, ValueError):
                        if errors:
                            break
                        time.sleep(0.1)
                else:
                    self.fail("named pipe nao iniciou")
                self.assertFalse(errors, errors)
                self.assertTrue(a.get("ok"), a)
                self.assertEqual(a["result"]["scope"], "application-level")
                b = ipc.request_windows()
                self.assertTrue(b.get("ok"), b)
            finally:
                stop.set()
                try:
                    ipc.request_windows()
                except Exception:
                    pass
                thread.join(timeout=3)
                ipc.PIPE_NAME = name
            self.assertFalse(errors, errors)


if __name__ == "__main__":
    unittest.main()

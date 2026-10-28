#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from enforcement_health import health_summary, publish_health


class HealthReportTests(unittest.TestCase):
    def test_snapshot_por_alvo(self):
        ok = {"target": "A", "state": "healthy"}
        bad = {"target": "B", "state": "error", "error": "ACL"}
        self.assertEqual(health_summary([ok])["state"], "healthy")
        self.assertEqual(health_summary([ok, bad])["state"], "degraded")
        self.assertEqual(health_summary([bad])["state"], "error")
        self.assertEqual(health_summary([], "config ausente")["state"], "error")
        self.assertEqual(health_summary([ok])["protection_scope"], "application-level")

    def test_atomicidade_e_permissoes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "private", "status.json")
            expected = publish_health(path, [{"target": "a", "state": "healthy"}])
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), expected)
            if os.name != "nt":
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
                self.assertEqual(os.stat(os.path.dirname(path)).st_mode & 0o777, 0o700)

    def test_acl_insegura_nao_publica_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "health.json")
            publish_health(path, [{"target": "antes", "state": "healthy"}])
            def deny(_path):
                raise PermissionError("ACL")
            with self.assertRaises(PermissionError):
                publish_health(path, [{"target": "depois", "state": "healthy"}],
                               hardener=deny)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["targets"][0]["target"], "antes")
            self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(tmp)))


if __name__ == "__main__":
    unittest.main()

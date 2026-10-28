#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from ui.health_model import load_health_report, parse_health_report


def payload():
    return {"schema_version": 1, "protection_scope": "application-level",
            "state": "degraded", "last_enforcement_utc": "2026-10-28T12:00:00+00:00",
            "targets": [
                {"target": "C:/alvo-A", "state": "healthy",
                 "baseline_paths": 12, "overlay": "C:/alvo-A.dfreezer"},
                {"target": "C:/alvo-B", "state": "error",
                 "error": "acesso negado"}]}


class HealthPanelDataTests(unittest.TestCase):
    def test_multiples_alvos_somente_leitura(self):
        obj = parse_health_report(payload())
        self.assertEqual(obj["state"], "degraded")
        self.assertEqual(len(obj["targets"]), 2)
        self.assertEqual(obj["targets"][0]["target"], "C:/alvo-A")
        self.assertEqual(obj["targets"][1]["message"], "acesso negado")
        self.assertEqual(obj["scope"], "application-level")

    def test_rejeita_formato_inesperado(self):
        for problem in ({"schema_version": 100}, [],
                        dict(payload(), protection_scope="os-level"),
                        dict(payload(), targets="sem lista")):
            with self.assertRaises(ValueError):
                parse_health_report(problem)

    def test_leitura_sem_escrever_ou_alterar_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "status.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload(), f)
            with open(path, "rb") as f:
                before = f.read()
            self.assertEqual(len(load_health_report(path)["targets"]), 2)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), before)


if __name__ == "__main__":
    unittest.main()

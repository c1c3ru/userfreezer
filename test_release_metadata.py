#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression test do gerador de assets; Python 3.8 e Windows 7 compat."""
import importlib.util
import json
import os
import tempfile
import unittest

_SCRIPT = os.path.join(os.path.dirname(__file__), ".github",
                       "scripts", "release_metadata.py")
spec = importlib.util.spec_from_file_location("release_metadata", _SCRIPT)
release_metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_metadata)


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifacts = os.path.join(self.temp.name, "artifacts")
        os.makedirs(self.artifacts)
        self.output = os.path.join(self.temp.name, "metadata")

    def fill(self, version="0.1.9"):
        names = [
            "deepfreezer_%s_all.deb" % version,
            "deepfreezer_service_windows-10-11.exe",
            "deepfreezer_service_windows-7-8.exe",
            "deepfreezer-windows-service-scripts.zip",
            "deepfreezer-windows-os-level.zip",
        ]
        for name in names:
            with open(os.path.join(self.artifacts, name), "wb") as f:
                f.write(("fixture-" + name).encode("utf-8"))

    def test_hashes_e_spdx_da_release(self):
        self.fill()
        hashes = release_metadata.make_metadata(self.artifacts,
                                                 self.output, "0.1.9")
        self.assertEqual(len(hashes), 5)
        with open(os.path.join(self.output, "SHA256SUMS"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 5)
        with open(os.path.join(self.output, "release.spdx.json"),
                  encoding="utf-8") as f:
            sbom = json.load(f)
        self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
        self.assertEqual(len(sbom["packages"]), 5)

    def test_rejeita_artefato_deb_com_versao_incorreta(self):
        self.fill("0.1.8")
        with self.assertRaises(ValueError):
            release_metadata.make_metadata(self.artifacts, self.output, "0.1.9")

    def test_rejeita_ausencia_do_exe_win7(self):
        self.fill()
        os.unlink(os.path.join(self.artifacts,
                               "deepfreezer_service_windows-7-8.exe"))
        with self.assertRaises(ValueError):
            release_metadata.make_metadata(self.artifacts, self.output, "0.1.9")


if __name__ == "__main__":
    unittest.main()

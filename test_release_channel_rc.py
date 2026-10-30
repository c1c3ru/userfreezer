#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0.2.0 prerelease safety gates and Debian upgrade regression."""
import importlib.util
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr

ROOT = os.path.dirname(__file__)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


channel = load(os.path.join("packaging", "release_channel.py"), "release_channel_test")
gate = load(os.path.join("packaging", "release_acceptance_gate.py"), "release_acceptance_test")


class ReleaseCandidateTests(unittest.TestCase):
    def test_current_version_and_tag(self):
        with open(os.path.join(ROOT, "VERSION"), encoding="ascii") as stream:
            self.assertEqual(stream.read().strip(), "0.2.0~rc1")
        data = channel.get_channel("0.2.0~rc1")
        self.assertEqual(data["tag"], "v0.2.0-rc.1")
        self.assertEqual(data["prerelease"], "true")

    def test_stable_versions_are_not_prereleases(self):
        for v in ("0.2.0", "0.1.13"):
            with self.subTest(version=v):
                meta = channel.get_channel(v)
                self.assertEqual(meta["tag"], "v" + v)
                self.assertEqual(meta["prerelease"], "false")

    def test_malformed_versions_denied(self):
        for v in ("0.2.0-rc.1", "0.2.0~rc0", "0.2.0~rc01",
                  "0.2.0~dev", "0.2.0~rc1\nfoo", "v0.2.0",
                  "0.2.0\n", "0.2.0/test"):
            with self.subTest(version=v), self.assertRaises(ValueError):
                channel.get_channel(v)

    def test_dpkg_candidate_precedes_stable(self):
        if sys.platform != "linux":
            self.skipTest("only Linux package builds")
        try:
            result = subprocess.run(
                ["dpkg", "--compare-versions", "0.2.0~rc1",
                 "lt", "0.2.0"], timeout=10)
        except OSError:
            self.skipTest("dpkg absent")
        self.assertEqual(result.returncode, 0)

    def test_workflow_marks_rc_prerelease_and_retains_stable_gate(self):
        with open(os.path.join(ROOT, ".github", "workflows",
                               "build-packages.yml"), encoding="utf-8") as src:
            workflow = src.read()
        self.assertIn("packaging/release_channel.py", workflow)
        self.assertIn("packaging/release_acceptance_gate.py", workflow)
        self.assertIn("prerelease: " + "$" + "{{ steps.metadata.outputs.prerelease == 'true' }}", workflow)
        self.assertIn("make_latest: " + "$" + "{{ steps.metadata.outputs.prerelease != 'true' }}", workflow)
        self.assertLess(workflow.index("packaging/release_acceptance_gate.py"),
                        workflow.index("softprops/action-gh-release@v2"))

    def test_rc_does_not_unlock_unverified_stable(self):
        path = os.path.join(ROOT, "docs", "V020_RELEASE_ACCEPTANCE.json")
        self.assertEqual(gate.validate_v020_acceptance(gate.read_manifest(path)),
                         ["63", "49", "54", "56", "review"])
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(gate.main(["--version", "0.2.0", "--record", path]), 2)
        self.assertIn("RELEASE BLOCKED", err.getvalue())
        self.assertEqual(gate.main(["--version", "0.2.0~rc1", "--record", path]), 0)

    def test_rc_changelog_exists(self):
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as stream:
            self.assertIn("## v0.2.0-rc.1\n", stream.read())


if __name__ == "__main__":
    unittest.main()

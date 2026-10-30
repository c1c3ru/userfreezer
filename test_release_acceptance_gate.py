#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Release v0.2.0 must not publish before real VM acceptance is reviewed."""
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

def _load_gate():
    path = os.path.join(os.path.dirname(__file__), "packaging",
                        "release_acceptance_gate.py")
    spec = importlib.util.spec_from_file_location("df_release_gate", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


gate = _load_gate()


def fixture():
    return {
        "schema": 1, "version": "0.2.0",
        "issues": {
            issue: {
                "state": "verified",
                "evidence": [
                    "https://github.com/c1c3ru/userfreezer/issues/%s#issuecomment-12345" %
                    issue],
            } for issue in gate.REQUIRED
        },
        "review": {
            "approved": True, "reviewer": "authorized-reviewer",
            "approval_url":
                "https://github.com/c1c3ru/userfreezer/issues/63#issuecomment-98765",
        },
    }


class ReleaseEvidenceGateTests(unittest.TestCase):
    def test_current_unverified_manifest_blocks_v020(self):
        actual = os.path.join(
            os.path.dirname(__file__), "docs", "V020_RELEASE_ACCEPTANCE.json")
        self.assertEqual(
            gate.validate_v020_acceptance(gate.read_manifest(actual)),
            ["63", "49", "54", "56", "review"])
        with redirect_stderr(io.StringIO()) as output:
            self.assertEqual(
                gate.main(["--version", "0.2.0", "--record", actual]), 2)
        self.assertIn("RELEASE BLOCKED", output.getvalue())

    def test_previous_release_unaffected_by_new_v020_gate(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main([
                "--version", "0.1.13", "--record", "/does/not/exist"]), 0)

    def test_all_evidence_and_explicit_review_required(self):
        self.assertEqual(gate.validate_v020_acceptance(fixture()), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "approved.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(fixture(), stream)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(gate.main([
                    "--version", "0.2.0", "--record", path]), 0)

    def test_cross_issue_evidence_does_not_satisfy_criteria(self):
        data = fixture()
        data["issues"]["54"]["evidence"] = data["issues"]["63"]["evidence"]
        with self.assertRaises(ValueError):
            gate.validate_v020_acceptance(data)

    def test_verified_without_external_evidence_blocks(self):
        data = fixture()
        data["issues"]["56"]["evidence"] = []
        self.assertEqual(gate.validate_v020_acceptance(data), ["56"])

    def test_approval_cannot_be_guessed_or_forged_by_boolean_coercion(self):
        for bad in (1, "true", "false", None):
            with self.subTest(bad=bad):
                data = fixture()
                data["review"]["approved"] = bad
                with self.assertRaises(ValueError):
                    gate.validate_v020_acceptance(data)
        data = fixture()
        data["review"]["approved"] = False
        with self.assertRaises(ValueError):
            gate.validate_v020_acceptance(data)

    def test_unknown_issue_or_state_cannot_bypass(self):
        for change in ("unknown-issue", "extra-field", "fake-state", "wrong-schema"):
            with self.subTest(change=change):
                data = fixture()
                if change == "unknown-issue":
                    data["issues"].pop("49")
                elif change == "extra-field":
                    data["issues"]["54"]["ignore_vm"] = True
                elif change == "fake-state":
                    data["issues"]["54"]["state"] = "skipped"
                else:
                    data["schema"] = True
                with self.assertRaises(ValueError):
                    gate.validate_v020_acceptance(data)

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "record.json")
            with open(path, "wb") as stream:
                stream.write(b'{"schema":1,"schema":1}')
            with self.assertRaises(ValueError):
                gate.read_manifest(path)

    def test_release_workflow_invokes_guard_before_publishing(self):
        workflow = os.path.join(
            os.path.dirname(__file__), ".github", "workflows",
            "build-packages.yml")
        with open(workflow, "r", encoding="utf-8") as stream:
            data = stream.read()
        guard = data.index("packaging/release_acceptance_gate.py")
        publish = data.index("softprops/action-gh-release@v2")
        self.assertLess(guard, publish)


if __name__ == "__main__":
    unittest.main()

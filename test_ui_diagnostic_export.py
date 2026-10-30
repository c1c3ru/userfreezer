#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostic export must never publish local identities or IPC secrets."""
import json
import os
import tempfile
import unittest
from unittest import mock

from ui.diagnostic_export import (
    export_sanitized_diagnostic, sanitize_diagnostic,
    MAX_TARGETS,
)


def sample():
    return {
        "state": "degraded", "timestamp": "2026-10-30T12:00:00Z",
        "session_token": "NEVER-EXPORT-THIS-SESSION-TOKEN",
        "targets": [
            {
                "target": r"C:\Users\private-user\secret",
                "overlay": r"D:\Confidential\overlay",
                "state": "healthy", "frozen": True,
                "baseline_paths": 14, "pending_ops": {"W": 2, "D": 1},
                "overlay_bytes": 256, "overlay_size_partial": False,
                "runtime_error": "token=SECRETVALUE in C:\\Users\\private-user",
                "os_level": {
                    "state": "unverified", "scope": "directory",
                    "strategy": "overlayfs", "reboot_verified": False,
                    "error": "password=SHOULD_NOT_LEAK",
                },
                "nonce": "DO-NOT-EXPORT",
            },
            {
                "target": "/home/another-user/sensitive",
                "overlay": "/tmp/custom-overlay",
                "state": "error", "frozen": None,
                "pending_ops": {}, "error": "access denied /home/another-user",
            },
        ],
    }


class SanitizedExportTests(unittest.TestCase):
    def test_whitelist_omits_paths_credentials_and_errors(self):
        original = sample()
        snapshot = json.loads(json.dumps(original))
        clean = sanitize_diagnostic(snapshot)
        encoded = json.dumps(clean)
        self.assertEqual(clean["target_count"], 2)
        self.assertEqual(clean["targets"][0]["id"], "target-001")
        self.assertEqual(clean["targets"][1]["id"], "target-002")
        self.assertEqual(clean["targets"][0]["pending_ops"]["W"], 2)
        self.assertEqual(clean["targets"][0]["overlay_bytes"], 256)
        self.assertEqual(clean["targets"][0]["os_level"]["state"], "unverified")
        self.assertTrue(clean["targets"][0]["error_present"])
        for secret in ("private-user", "another-user", "SECRETVALUE",
                       "SHOULD_NOT_LEAK", "NEVER-EXPORT", "DO-NOT-EXPORT",
                       "D:\\Confidential", "/tmp/custom-overlay"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, encoded)
        self.assertEqual(snapshot, original, "status source must not be mutated")

    def test_future_ipc_fields_are_not_exported(self):
        source = sample()
        source["future"] = {"api_key": "SUPER-SECRET"}
        source["targets"][0]["future"] = {"auth": "VERY-SECRET"}
        safe = sanitize_diagnostic(source)
        self.assertNotIn("SUPER-SECRET", json.dumps(safe))
        self.assertNotIn("VERY-SECRET", json.dumps(safe))

    def test_invalid_counts_and_untrusted_enums_fail_closed(self):
        source = sample()
        entry = source["targets"][0]
        entry["baseline_paths"] = True
        entry["overlay_bytes"] = -1
        entry["pending_ops"] = {"W": "10", "D": 10**19}
        entry["state"] = "healthy SECRET-TRAIL"
        entry["os_level"]["strategy"] = "token=SECRET-TRAIL"
        source["timestamp"] = "token=CREDENTIAL"
        clean = sanitize_diagnostic(source)
        self.assertIsNone(clean["targets"][0]["baseline_paths"])
        self.assertIsNone(clean["targets"][0]["overlay_bytes"])
        self.assertIsNone(clean["targets"][0]["pending_ops"]["W"])
        self.assertIsNone(clean["targets"][0]["pending_ops"]["D"])
        self.assertEqual(clean["targets"][0]["api_state"], "unknown")
        self.assertEqual(clean["targets"][0]["os_level"]["strategy"], "unknown")
        self.assertIsNone(clean["last_enforcement_utc"])
        self.assertNotIn("SECRET-TRAIL", json.dumps(clean))

    def test_unexpected_snapshot_shape_is_rejected(self):
        for source in (
                None, [], {"targets": "wrong"}, {"targets": [None]},
                {"targets": [{}] * (MAX_TARGETS + 1)}):
            with self.subTest(shape=type(source).__name__):
                with self.assertRaises(ValueError):
                    sanitize_diagnostic(source)

    def test_atomic_export_is_valid_json_and_single_newline(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "report.json")
            with open(path, "wb") as stream:
                stream.write(b"old-data")
            expected = export_sanitized_diagnostic(sample(), path)
            with open(path, "rb") as stream:
                raw = stream.read()
            self.assertTrue(raw.endswith(b"}\n"))
            self.assertFalse(raw.endswith(b"}\\n"))
            self.assertEqual(json.loads(raw.decode("utf-8")), expected)
            self.assertEqual(os.listdir(temp), ["report.json"])

    def test_failure_to_replace_preserves_existing_report_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "report.json")
            with open(path, "wb") as stream:
                stream.write(b"previous")
            with mock.patch("ui.diagnostic_export.os.replace",
                            side_effect=OSError("write denied")):
                with self.assertRaises(OSError):
                    export_sanitized_diagnostic(sample(), path)
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), b"previous")
            self.assertEqual(os.listdir(temp), ["report.json"])

    def test_invalid_destination_rejected_without_writing(self):
        for destination in (None, 42, "", b"bytes.json"):
            with self.subTest(destination=destination):
                with self.assertRaises(ValueError):
                    export_sanitized_diagnostic(sample(), destination)

    def test_oversized_report_denied_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "report.json")
            with mock.patch("ui.diagnostic_export.MAX_EXPORT_BYTES", 4):
                with self.assertRaises(ValueError):
                    export_sanitized_diagnostic(sample(), path)
            self.assertFalse(os.path.exists(path))


class GUIExportBindingTests(unittest.TestCase):
    def test_panel_routes_to_sanitizer_not_raw_json(self):
        from ui import health_panel
        panel = health_panel.AdminPanel.__new__(health_panel.AdminPanel)
        panel.root = mock.Mock()
        panel.last_snapshot = sample()
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "panel.json")
            with mock.patch.object(health_panel.filedialog, "asksaveasfilename",
                                   return_value=path):
                with mock.patch.object(health_panel.messagebox, "showinfo") as show:
                    panel.export()
                show.assert_called_once()
            with open(path, "rb") as stream:
                data = stream.read().decode("utf-8")
            self.assertNotIn("private-user", data)
            self.assertNotIn("NEVER-EXPORT", data)
            self.assertTrue(json.loads(data)["redacted"])


if __name__ == "__main__":
    unittest.main()

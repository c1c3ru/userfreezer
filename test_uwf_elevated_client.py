#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UWF elevated CLI never stages without explicit flags and an IPC nonce."""
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import admin_client


class ElevatedUwfClientTests(unittest.TestCase):
    def test_missing_consent_never_calls_service(self):
        with mock.patch.object(admin_client, "request") as request:
            with redirect_stdout(io.StringIO()):
                rc = admin_client.main([
                    "approve-uwf-stage", "--target", "C:",
                    "--persistent-volume", "D:"])
            self.assertEqual(rc, 2)
            request.assert_not_called()

    def test_rejected_prepare_never_stages(self):
        with mock.patch.object(admin_client, "request",
                               return_value={"ok": False,
                                             "error": {"message": "disabled"}}) as req:
            with redirect_stdout(io.StringIO()):
                rc = admin_client.main([
                    "approve-uwf-stage", "--target", "C:",
                    "--persistent-volume", "D:",
                    "--acknowledge-vm-snapshot",
                    "--acknowledge-discard-writes"])
            self.assertEqual(rc, 1)
            req.assert_called_once_with(
                "uwf-prepare", "C:", operation="D:", socket_path=None)

    def test_same_elevated_process_prepares_and_stages_with_nonce(self):
        with mock.patch.object(admin_client, "request",
                               side_effect=[
                                   {"ok": True, "result": {"token": "secret"}},
                                   {"ok": True, "result": {"status": "next"}},
                               ]) as req:
            with redirect_stdout(io.StringIO()):
                rc = admin_client.main([
                    "approve-uwf-stage", "--target", "C:",
                    "--persistent-volume", "D:",
                    "--acknowledge-vm-snapshot",
                    "--acknowledge-discard-writes"])
            self.assertEqual(rc, 0)
            self.assertEqual(req.call_count, 2)
            self.assertEqual(req.call_args.args, ("uwf-stage", "C:"))
            self.assertEqual(req.call_args.kwargs["confirm"], "secret")
            self.assertEqual(req.call_args.kwargs["operation"], "D:")

    def test_fake_drive_rejected_before_request(self):
        with mock.patch.object(admin_client, "request") as req:
            with redirect_stdout(io.StringIO()):
                rc = admin_client.main([
                    "approve-uwf-stage", "--target", "C:",
                    "--persistent-volume", "C:",
                    "--acknowledge-vm-snapshot",
                    "--acknowledge-discard-writes"])
            self.assertEqual(rc, 2)
            req.assert_not_called()


if __name__ == "__main__":
    unittest.main()

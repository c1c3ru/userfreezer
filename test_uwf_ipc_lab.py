#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UWF lab IPC security: privileged peer identity, nonce, exact volumes."""
import json
import unittest
import uuid
from unittest import mock

from admin_ipc import Broker
import uwf_ipc_lab as lab


def message(action, target="C:", operation="D:", confirm=None):
    obj = {"v": 1, "id": str(uuid.uuid4()), "action": action,
           "target": target, "operation": operation}
    if confirm is not None:
        obj["confirm"] = confirm
    return json.dumps(obj).encode("utf-8")


CLEAN = {
    "status": "not_protected", "current_filter_enabled": False,
    "next_filter_enabled": False, "current_c_protected": False,
    "next_c_protected": False, "persistent_volume_unprotected": True,
}


class BrokerUwfTests(unittest.TestCase):
    def broker(self, enabled=False):
        return Broker("/must/not/load/config", "/must/not/load/status",
                      uwf_lab_enabled=enabled)

    def test_uwf_disabled_by_default_even_admin_cannot_prepare(self):
        service = self.broker()
        with mock.patch("admin_ipc.os.name", "nt"):
            with mock.patch.object(lab, "inspect_uwf") as inspect:
                result = service.process(message("uwf-prepare"),
                                         is_admin=True, identity="S-1-5-21-10")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "PermissionError")
        inspect.assert_not_called()

    def test_unprivileged_user_cannot_prepare_or_stage(self):
        service = self.broker(enabled=True)
        with mock.patch("admin_ipc.os.name", "nt"):
            with mock.patch.object(lab, "stage_uwf_lab") as mutate:
                for action in ("uwf-prepare", "uwf-stage"):
                    result = service.process(message(action, confirm="fake"),
                                             is_admin=False, identity="user")
                    self.assertFalse(result["ok"])
                mutate.assert_not_called()

    def test_read_only_state_can_be_read_without_targets_config(self):
        service = self.broker()
        with mock.patch("admin_ipc.os.name", "nt"):
            with mock.patch.object(lab, "inspect_uwf", return_value=dict(CLEAN)):
                result = service.process(message("uwf-status"), identity="user")
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["result"]["lab_staging_enabled"])

    def test_stage_requires_raised_peer_and_fresh_one_time_nonce(self):
        service = self.broker(enabled=True)
        with mock.patch("admin_ipc.os.name", "nt"):
            with mock.patch.object(lab, "inspect_uwf", return_value=dict(CLEAN)):
                with mock.patch.object(
                        lab, "stage_uwf_lab",
                        return_value={"status": "configured_for_next_boot_not_yet_verified"}) as stage:
                    first = service.process(message("uwf-prepare"), True, "admin-A")
                    self.assertTrue(first["ok"], first)
                    token = first["result"]["token"]
                    wrong = service.process(message("uwf-stage", confirm=token),
                                            True, "admin-B")
                    self.assertFalse(wrong["ok"])
                    replay = service.process(message("uwf-stage", confirm=token),
                                             True, "admin-A")
                    self.assertFalse(replay["ok"], "nonce consumed on wrong peer")
                    again = service.process(message("uwf-prepare"), True, "admin-A")
                    token2 = again["result"]["token"]
                    valid = service.process(message("uwf-stage", confirm=token2),
                                            True, "admin-A")
                    self.assertTrue(valid["ok"], valid)
                    duplicate = service.process(message("uwf-stage", confirm=token2),
                                                True, "admin-A")
                    self.assertFalse(duplicate["ok"])
                    stage.assert_called_once_with("C:", "D:", enabled=True)

    def test_nonce_binds_both_c_and_persistent_drive(self):
        service = self.broker(enabled=True)
        with mock.patch("admin_ipc.os.name", "nt"):
            with mock.patch.object(lab, "inspect_uwf", return_value=dict(CLEAN)):
                with mock.patch.object(lab, "stage_uwf_lab") as stage:
                    prepared = service.process(message("uwf-prepare"), True, "admin")
                    t = prepared["result"]["token"]
                    other = service.process(
                        message("uwf-stage", operation="E:", confirm=t), True, "admin")
                    self.assertFalse(other["ok"])
                    stage.assert_not_called()

    def test_windows7_and_linux_never_accepted(self):
        service = self.broker(enabled=True)
        result = service.process(message("uwf-prepare"), True, "root")
        if __import__("os").name != "nt":
            self.assertFalse(result["ok"])

    def test_reject_nonlocal_or_c_as_data_volume_before_inspection(self):
        service = self.broker(enabled=True)
        with mock.patch("admin_ipc.os.name", "nt"):
            with mock.patch.object(lab, "inspect_uwf") as inspect:
                for target, persistent in (
                        ("D:", "E:"), ("C:", "C:"), ("C:", "../D:"),
                        ("C:", r"\\server\share"), ("C:", "d:"),
                        ("C:", "C:\\Windows")):
                    with self.subTest(target=target, persistent=persistent):
                        result = service.process(
                            message("uwf-prepare", target, persistent),
                            True, "admin")
                        self.assertFalse(result["ok"])
                inspect.assert_not_called()

    def test_existing_uwf_never_overwritten(self):
        service = self.broker(enabled=True)
        previous = dict(CLEAN, current_filter_enabled=True)
        with mock.patch("admin_ipc.os.name", "nt"):
            with mock.patch.object(lab, "inspect_uwf", return_value=previous):
                result = service.process(message("uwf-prepare"), True, "admin")
        self.assertFalse(result["ok"])


class NativeUwfPlanTests(unittest.TestCase):
    def test_no_mutation_on_unsupported_or_disabled_platform(self):
        with self.assertRaises(ValueError):
            lab._validate_volumes("C:", "C:")
        with self.assertRaises(ValueError):
            lab._validate_volumes("D:", "E:")
        with mock.patch.object(lab, "inspect_uwf") as inspect:
            with self.assertRaises(PermissionError):
                lab.stage_uwf_lab("C:", "D:", enabled=False)
            inspect.assert_not_called()

    def test_wmi_state_is_not_misrepresented_as_reboot_proof(self):
        with mock.patch.object(lab, "_preconditions"):
            with mock.patch.object(lab, "_provider_snapshot",
                                   return_value={
                                       "current_filter_enabled": True,
                                       "next_filter_enabled": True,
                                       "current_c_protected": True,
                                       "next_c_protected": True,
                                       "persistent_volume_unprotected": True,
                                   }):
                result = lab.inspect_uwf("C:", "D:")
        self.assertEqual(result["status"], "native_filter_currently_enabled")
        self.assertFalse(result["vm_reboot_verified"])
        self.assertFalse(result["external_write_rollback_verified"])

    def test_native_stage_rechecks_wmi_and_never_reports_frozen(self):
        before = dict(CLEAN)
        after = dict(CLEAN, next_filter_enabled=True, next_c_protected=True)
        with mock.patch.object(lab, "inspect_uwf", side_effect=[before, after]):
            with mock.patch.object(lab, "_uwfmgr_path", return_value="trusted.exe"):
                with mock.patch.object(lab, "_native_call") as native:
                    result = lab.stage_uwf_lab("C:", "D:", enabled=True)
        self.assertEqual(native.call_count, 2)
        self.assertTrue(result["reboot_required"])
        self.assertFalse(result["external_write_rollback_verified"])


if __name__ == "__main__":
    unittest.main()

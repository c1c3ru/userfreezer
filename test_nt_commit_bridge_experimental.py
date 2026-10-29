#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for isolated core-to-NT commit preflight (#63)."""
import os
import tempfile
import unittest
from unittest import mock

from nt_commit_bridge_experimental import (
    prepare_native_plan, apply_prepared_plan_experimental,
    MAX_PLAN_ITEMS,
)


class NativeBridgePreflightTests(unittest.TestCase):
    @staticmethod
    def _loader(src, limit):
        payloads = {"write-a": b"alpha", "write-b": b"beta"}
        payload = payloads[src]
        if len(payload) > limit:
            raise ValueError("payload oversized")
        return payload

    def test_converts_all_native_kinds_and_preserves_order(self):
        entries = [
            (["a.txt"], "W", 0, "write-a"),
            (["nested"], "M", 1, None),
            (["nested", "b.txt"], "W", 0, "write-b"),
            (["old.txt"], "D", 0, None),
            (["obsolete"], "D", 1, None),
        ]
        self.assertEqual(
            prepare_native_plan(entries, self._loader),
            [("W", "a.txt", b"alpha"), ("M", "nested", None),
             ("W", "nested/b.txt", b"beta"),
             ("F", "old.txt", None), ("D", "obsolete", None)])

    def test_bad_final_path_rejected_before_reading_any_payload(self):
        entries = [
            (["a.txt"], "W", 0, "write-a"),
            (["safe"], "M", 1, None),
            (["..", "external"], "D", 1, None),
        ]
        with mock.patch.object(
                __import__("nt_commit_bridge_experimental"),
                "apply_prepared_plan_experimental") as apply:
            loader = mock.Mock(side_effect=AssertionError("loader must not run"))
            with self.assertRaises(ValueError):
                prepare_native_plan(entries, loader)
            loader.assert_not_called()
            apply.assert_not_called()

    def test_all_input_shape_failures_are_fail_closed(self):
        invalid = [
            (["a"], "Z", 0, None),
            (["a"], "W", 1, "payload"),
            (["a"], "W", 0, None),
            (["a"], "M", 0, None),
            (["a"], "M", 1, "unexpected"),
            (["a"], "D", 0, "unexpected"),
            (["a"], "D", True, None),
            ([], "W", 0, "payload"),
            (["a", None], "D", 1, None),
            (["a"], "W", 0),
        ]
        for invalid_item in invalid:
            with self.subTest(item=invalid_item):
                loader = mock.Mock()
                with self.assertRaises(ValueError):
                    prepare_native_plan(
                        [(["good.txt"], "W", 0, "write-a"),
                         invalid_item], loader)
                loader.assert_not_called()

    def test_no_unbounded_plan_or_payloads(self):
        with self.assertRaises(ValueError):
            prepare_native_plan(
                [(["dir"], "M", 1, None)] * (MAX_PLAN_ITEMS + 1),
                self._loader)
        with self.assertRaises(ValueError):
            prepare_native_plan(
                [(["a"], "W", 0, "write-a")],
                lambda _src, _limit: b"123456",
                max_payload=5)
        with self.assertRaises(ValueError):
            prepare_native_plan(
                [(["a"], "W", 0, "write-a"),
                 (["b"], "W", 0, "write-b")],
                self._loader, max_total=8)
        for size in (0, True, -1, 0x10000000):
            with self.subTest(limit=size), self.assertRaises(ValueError):
                prepare_native_plan(
                    [(["a"], "M", 1, None)], self._loader,
                    max_payload=size)

    def test_nonbytes_payload_refuses_before_native_backend(self):
        with mock.patch("nt_enrollment_store_experimental.apply_stored_plan_experimental") as apply:
            with self.assertRaises(ValueError):
                apply_prepared_plan_experimental(
                    "C:\\Protected", [(["a"], "W", 0, "payload")],
                    "C:\\SecureStore",
                    lambda _src, _limit: "wrong-type")
            apply.assert_not_called()

    def test_strict_backend_called_only_after_complete_preflight(self):
        with mock.patch("nt_enrollment_store_experimental.apply_stored_plan_experimental",
                        return_value=["a.txt"]) as apply:
            entries = [(["a.txt"], "W", 0, "write-a")]
            out = apply_prepared_plan_experimental(
                "C:\\Protected", entries, "C:\\SecureStore", self._loader)
            self.assertEqual(out, ["a.txt"])
            apply.assert_called_once_with(
                "C:\\Protected", [("W", "a.txt", b"alpha")],
                "C:\\SecureStore")

    def test_no_core_production_enablement(self):
        import inspect
        import deepfreezer
        source = inspect.getsource(deepfreezer.DeepFreezer._apply_commit)
        self.assertIn('if os.name == "nt" and self.ops:', source)
        self.assertNotIn("nt_commit_bridge_experimental", source)


@unittest.skipUnless(os.name == "nt", "requires Windows native NT backend")
class WindowsNativeBridgeTests(unittest.TestCase):
    def test_full_plan_replays_under_pinned_root_with_enrolled_identity(self):
        import nt_enrollment_store_experimental as store
        from win32_relative_directory import directory_identity, open_trusted_root
        with tempfile.TemporaryDirectory() as root:
            old = os.path.join(root, "old.txt")
            with open(old, "wb") as stream:
                stream.write(b"old")
            with open_trusted_root(root) as handle:
                expected = directory_identity(handle)
            entries = [
                (["new"], "M", 1, None),
                (["new", "saved.txt"], "W", 0, "payload"),
                (["old.txt"], "D", 0, None),
            ]
            with mock.patch.object(store, "load_identity_from_store",
                                   return_value=expected):
                result = apply_prepared_plan_experimental(
                    root, entries, r"C:\unused-test-store",
                    lambda source, limit: b"saved" if source == "payload" else b"")
            self.assertEqual(result, ["new", "new/saved.txt", "old.txt"])
            with open(os.path.join(root, "new", "saved.txt"), "rb") as stream:
                self.assertEqual(stream.read(), b"saved")
            self.assertFalse(os.path.exists(old))


if __name__ == "__main__":
    unittest.main()

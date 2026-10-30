#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline consistency checks for two-phase Windows 7 SP1 NT crash evidence.

This checks the evidence format and cross-file consistency, NOT authenticity
of the host, actual reboot, ACL authorization, signed approval, durability
under power loss or safe recovery. Users must independently authenticate the
VM identity, boot logs and snapshots before treating results as real evidence.

Python 3.8+; portable (no pywin32 or NT libraries required).
"""
import argparse
import hashlib
import json
import re
import sys

MAX_JSON_SIZE = 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
DMTF = re.compile(r"\d{14}\.\d{6}[+-]\d{3}\Z")

EXPECTED_MARKERS = {".intent", ".00000.started"}
EXPECTED_REPORT_FIELDS = {
    "state", "completed", "total", "uncertain_index", "intent_sha256",
}
EXPECTED_VERSION_FIELDS = {
    "major", "minor", "service_pack_major", "build", "platform",
}
BEFORE_FIELDS = {
    "schema", "base", "windows_version", "marker_sha256", "checkpoint",
    "child_exit_code", "first_sha256", "second_absent", "scope", "boot_before",
}
AFTER_FIELDS = {
    "result", "boot_before", "boot_after", "checkpoint", "marker_sha256",
    "windows_version", "scope",
}


def _unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("chave duplicada em evidencia: " + key)
        obj[key] = value
    return obj


def load_evidence(path):
    """Bound size and reject duplicate JSON keys; no external file access."""
    with open(path, "rb") as stream:
        raw = stream.read(MAX_JSON_SIZE + 1)
    if not raw or len(raw) > MAX_JSON_SIZE:
        raise ValueError("JSON de evidencia vazio ou excede 1 MiB")
    try:
        value = json.loads(raw.decode("utf-8"),
                           object_pairs_hook=_unique_pairs)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("JSON de evidencia invalido") from exc
    if not isinstance(value, dict):
        raise ValueError("evidencia deve ser objeto JSON")
    return value


def _sha(value, field):
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValueError("SHA-256 invalido em " + field)


def _dmtf(value, field):
    if not isinstance(value, str) or DMTF.fullmatch(value) is None:
        raise ValueError("timestamp WMI DMTF invalido em " + field)


def _assert_fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("campos inesperados em " + label)


def _validate_checkpoint(value):
    _assert_fields(value, EXPECTED_REPORT_FIELDS, "checkpoint")
    if (value["state"] != "uncertain"
            or type(value["uncertain_index"]) is not int
            or value["uncertain_index"] != 0
            or type(value["completed"]) is not int or value["completed"] != 0
            or type(value["total"]) is not int or value["total"] != 2):
        raise ValueError("checkpoint nao representa crash apos STARTED(0)")
    _sha(value["intent_sha256"], "checkpoint.intent_sha256")


def _validate_version(value):
    _assert_fields(value, EXPECTED_VERSION_FIELDS, "windows_version")
    if (type(value["major"]) is not int or value["major"] != 6
            or type(value["minor"]) is not int or value["minor"] != 1
            or type(value["service_pack_major"]) is not int
            or value["service_pack_major"] != 1
            or type(value["build"]) is not int or value["build"] < 7601
            or not isinstance(value["platform"], str)
            or not value["platform"]):
        raise ValueError("evidencia nao identifica Windows 7 SP1")


def _validate_markers(value):
    if not isinstance(value, dict) or set(value) != EXPECTED_MARKERS:
        raise ValueError("marcadores esperados INTENT/STARTED nao correspondem")
    for marker, digest in value.items():
        _sha(digest, marker)


def verify_evidence(before, after):
    """Validate the recorded pair; NEVER return a VM certification."""
    _assert_fields(before, BEFORE_FIELDS, "before")
    _assert_fields(after, AFTER_FIELDS, "after")
    if type(before["schema"]) is not int or before["schema"] != 2:
        raise ValueError("schema de evidencia anterior invalido")
    if not isinstance(before["base"], str) or not before["base"]:
        raise ValueError("raiz do ensaio invalida")
    if (type(before["child_exit_code"]) is not int
            or before["child_exit_code"] == 0
            or before["second_absent"] is not True):
        raise ValueError("encerramento abrupto / segundo arquivo nao confirmado")
    _sha(before["first_sha256"], "before.first_sha256")
    if before["first_sha256"] != hashlib.sha256(b"FIRST").hexdigest():
        raise ValueError("sentinela inicial nao corresponde ao teste")
    if before["scope"] != "VM scratch only; native ACL/enrollment mocked":
        raise ValueError("escopo do ensaio anterior incorreto")
    if after["scope"] != (
            "VM scratch only; no production ACL/enrollment/recovery proof"):
        raise ValueError("escopo do ensaio posterior incorreto")
    _validate_version(before["windows_version"])
    _validate_version(after["windows_version"])
    if before["windows_version"] != after["windows_version"]:
        raise ValueError("Windows build/arquitetura mudaram entre fases")
    _dmtf(before["boot_before"], "before.boot_before")
    _dmtf(after["boot_before"], "after.boot_before")
    _dmtf(after["boot_after"], "after.boot_after")
    if before["boot_before"] != after["boot_before"]:
        raise ValueError("boot_before difere entre evidencias")
    if after["boot_after"] == after["boot_before"]:
        raise ValueError("nao ha indicacao de um novo boot")
    if after["result"] != "PASS_SCRATCH_CHECKPOINT_POST_REBOOT":
        raise ValueError("resultado do ensaio posterior nao e PASS")
    _validate_checkpoint(before["checkpoint"])
    _validate_checkpoint(after["checkpoint"])
    _validate_markers(before["marker_sha256"])
    _validate_markers(after["marker_sha256"])
    if before["checkpoint"] != after["checkpoint"]:
        raise ValueError("checkpoint alterado entre as fases")
    if before["marker_sha256"] != after["marker_sha256"]:
        raise ValueError("bytes dos marcadores alterados entre as fases")
    return {
        "result": "CONSISTENT_OFFLINE_EVIDENCE_ONLY",
        "claimed_platform": "Windows 7 SP1",
        "intent_sha256": before["checkpoint"]["intent_sha256"],
        "markers_compared": sorted(EXPECTED_MARKERS),
        "boot_changed_in_records": True,
        "vm_or_reboot_independently_authenticated": False,
        "production_commit_certified": False,
        "automatic_retry_allowed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validar consistencia offline dos dois JSONs de VM Win7 SP1")
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args(argv)
    try:
        before, after = load_evidence(args.before), load_evidence(args.after)
        result = verify_evidence(before, after)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"result": "FAIL", "retry_allowed": False,
                          "error": str(exc)}, sort_keys=True),
              file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

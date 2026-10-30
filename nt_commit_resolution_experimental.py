#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Experimental write-once administrative incident resolution for NT #63.

Only annotates a previously reviewed interrupted checkpoint. NEVER clears
INTENT/STARTED/DONE, reenables thaw, starts a new epoch, repairs files, or
claims that external evidence proves data correctness. This is an explicit
administrative assertion, not automatic verification of a restoration.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from nt_commit_checkpoint_experimental import (
    _inspect_open_store, _json, _ledger_prefix, _read_optional,
    _write_verified,
)
from nt_commit_forensics_experimental import inspect_nt_commit_for_operator
from nt_enrollment_experimental import _canonical_root
from nt_enrollment_store_experimental import (
    _assert_protected_acl, _require_privileged_enroller,
)
from win32_relative_directory import open_trusted_root

REVIEW_MAX_BYTES = 4096
RESOLUTION_MAX_BYTES = 4096
DECISIONS = ("restored_from_verified_snapshot", "manually_reconciled")


def _ticket(value):
    if (not isinstance(value, str) or
            re.fullmatch(r"[A-Za-z0-9_-]{6,64}", value) is None):
        raise ValueError("identificador de incidente/aprovacao invalido")
    return value


def _digest(value):
    if (not isinstance(value, str) or
            re.fullmatch(r"[0-9a-f]{64}", value) is None):
        raise ValueError("SHA-256 externo invalido")
    return value


def _read_review(store, root):
    raw = _read_optional(
        store, _ledger_prefix(root) + ".review", REVIEW_MAX_BYTES)
    if raw is None:
        raise ValueError("REVIEW anterior obrigatorio para encerrar incidente")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("REVIEW invalido") from exc
    required = {"v", "root", "intent_sha256", "observed_state",
                "case_id", "evidence_sha256", "time_utc", "action"}
    if (not isinstance(value, dict) or set(value) != required or
            type(value["v"]) is not int or value["v"] != 1 or
            value["root"] != _canonical_root(root) or
            value["action"] != "review-recorded-no-retry-no-unlock" or
            value["observed_state"] not in ("uncertain", "incomplete") or
            not isinstance(value["time_utc"], str) or
            not value["time_utc"] or _json(value) != raw):
        raise ValueError("REVIEW nao corresponde ao protocolo NT")
    _ticket(value["case_id"])
    _digest(value["intent_sha256"])
    _digest(value["evidence_sha256"])
    return value, hashlib.sha256(raw).hexdigest()


def _check_review_against_current(store, root, expected, case_id):
    report = _inspect_open_store(store, root)
    if (report["state"] not in ("uncertain", "incomplete") or
            report["state"] != expected["state"] or
            report["intent_sha256"] != expected["intent_sha256"] or
            report.get("completed") != expected.get("completed") or
            report.get("uncertain_index") != expected.get("uncertain_index")):
        raise OSError("checkpoint NT mudou ou nao e incidente interrompido")
    review, review_hash = _read_review(store, root)
    if (review["case_id"] != case_id or
            review["intent_sha256"] != report["intent_sha256"] or
            review["observed_state"] != report["state"]):
        raise OSError("REVIEW difere do incidente/estado NT atual")
    return review, review_hash


def record_nt_incident_resolution_experimental(
        root, store_directory, case_id, approval_id, recovery_evidence_sha256,
        decision):
    """Write one immutable resolution assertion; never unlock any commit.

    The approval and recovery evidence referenced here MUST be collected and
    approved out of band. Their validity is NOT cryptographically verified.
    """
    root = _canonical_root(root)
    store_directory = _canonical_root(store_directory)
    _ticket(case_id)
    _ticket(approval_id)
    _digest(recovery_evidence_sha256)
    if decision not in DECISIONS:
        raise ValueError("decisao de resolucao NT nao permitida")
    _require_privileged_enroller()
    report = inspect_nt_commit_for_operator(root, store_directory)
    if report["state"] not in ("uncertain", "incomplete"):
        raise ValueError("somente incidente interrompido pode ser encerrado")
    with open_trusted_root(store_directory, read_control=True) as store:
        _assert_protected_acl(store)
        review, review_hash = _check_review_against_current(
            store, root, report, case_id)
        payload = {
            "v": 1,
            "root": root,
            "intent_sha256": report["intent_sha256"],
            "observed_state": report["state"],
            "case_id": case_id,
            "review_sha256": review_hash,
            "initial_evidence_sha256": review["evidence_sha256"],
            "recovery_evidence_sha256": recovery_evidence_sha256,
            "approval_id": approval_id,
            "decision": decision,
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "action": "administratively-recorded-no-retry-no-unlock",
            "retry_allowed": False,
        }
        data = _json(payload)
        if len(data) > RESOLUTION_MAX_BYTES:
            raise ValueError("resolucao NT excede limite")
        # Create-only NT handle operation, never deletes or renames
        # original intent, step markers, review or previous resolutions.
        _write_verified(store, _ledger_prefix(root) + ".resolution", data)
    return payload


def inspect_nt_incident_resolution_experimental(root, store_directory):
    """Read-only status. Absence or existence never authorizes a new epoch."""
    root = _canonical_root(root)
    store_directory = _canonical_root(store_directory)
    report = inspect_nt_commit_for_operator(root, store_directory)
    if report["state"] == "absent":
        return {"status": "absent", "retry_allowed": False}
    with open_trusted_root(store_directory, read_control=True) as store:
        _assert_protected_acl(store)
        raw = _read_optional(
            store, _ledger_prefix(root) + ".resolution",
            RESOLUTION_MAX_BYTES)
        if raw is None:
            return {"status": "not_recorded", "retry_allowed": False}
        try:
            record = json.loads(raw.decode("ascii"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("resolucao administrativa NT invalida") from exc
        required = {"v", "root", "intent_sha256", "observed_state",
                    "case_id", "review_sha256", "initial_evidence_sha256",
                    "recovery_evidence_sha256", "approval_id", "decision",
                    "recorded_utc", "action", "retry_allowed"}
        if (not isinstance(record, dict) or set(record) != required or
                type(record["v"]) is not int or record["v"] != 1 or
                record["root"] != root or
                record["intent_sha256"] != report["intent_sha256"] or
                record["observed_state"] != report["state"] or
                record["action"] != "administratively-recorded-no-retry-no-unlock" or
                record["retry_allowed"] is not False or
                record["decision"] not in DECISIONS or
                not isinstance(record["recorded_utc"], str) or
                not record["recorded_utc"] or _json(record) != raw):
            raise ValueError("registro de resolucao NT invalido ou divergente")
        _ticket(record["case_id"])
        _ticket(record["approval_id"])
        _digest(record["initial_evidence_sha256"])
        _digest(record["recovery_evidence_sha256"])
        _digest(record["review_sha256"])
        review, review_hash = _check_review_against_current(
            store, root, report, record["case_id"])
        if (review_hash != record["review_sha256"] or
                review["evidence_sha256"] != record["initial_evidence_sha256"]):
            raise ValueError("cadeia REVIEW/RESOLUTION NT inconsistente")
        return {
            "status": "administrative_resolution_recorded",
            "intent_sha256": report["intent_sha256"],
            "review_sha256": review_hash,
            "resolution_sha256": hashlib.sha256(raw).hexdigest(),
            "decision": record["decision"],
            "retry_allowed": False, "new_epoch_allowed": False,
            "automatic_recovery_verified": False,
        }

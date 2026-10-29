#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Forensic NT checkpoint inspection and append-only review annotation (#63).

This is NOT a recovery/clear/retry command. Every observed object must match
the pre-enrolled Windows identity; an untrusted or missing object fails closed.
"""
from nt_commit_checkpoint_experimental import (
    _parse_intent, _read_optional, _ledger_prefix, _inspect_open_store,
    _write_verified, _json, MAX_INTENT_BYTES,
)
from nt_enrollment_experimental import _canonical_root
from nt_enrollment_store_experimental import (
    _assert_protected_acl, _require_privileged_enroller,
    load_identity_from_store,
)
from win32_relative_directory import (
    directory_identity, open_trusted_root,
)


def inspect_nt_commit_for_operator(root, store_directory):
    """Return a forensic view without modifying target, overlay or journal.

    A marker is evidence of execution boundaries, NOT proof that the target
    currently contains the same bytes. Never mark a commit safe to resume.
    """
    _canonical_root(root)
    _canonical_root(store_directory)
    root_id = load_identity_from_store(root, store_directory)
    with open_trusted_root(root, read_control=True) as pinned:
        if directory_identity(pinned) != root_id:
            raise OSError("identidade NT do alvo difere do cadastro")
        _assert_protected_acl(pinned)
    with open_trusted_root(store_directory, read_control=True) as store:
        _assert_protected_acl(store)
        state = _inspect_open_store(store, root)
        if state["state"] == "absent":
            return {"state": "absent", "replay_allowed": False,
                    "evidence": "nenhuma intencao visivel; nao prova ausencia de mutacao"}
        raw = _read_optional(
            store, _ledger_prefix(root) + ".intent", MAX_INTENT_BYTES)
        intent = _parse_intent(raw, root)
        if intent["root_id"] != list(root_id):
            raise OSError("identidade do alvo no INTENT nao corresponde ao cadastro")
    overlay = intent["overlay"]
    overlay_id = load_identity_from_store(overlay, store_directory)
    if intent["overlay_id"] != list(overlay_id):
        raise OSError("identidade do overlay no INTENT difere do cadastro")
    with open_trusted_root(overlay, read_control=True) as pinned:
        if directory_identity(pinned) != overlay_id:
            raise OSError("identidade fisica do overlay NT divergente")
        _assert_protected_acl(pinned)

    return {
        "state": state["state"], "completed": state["completed"],
        "total": state["total"],
        "uncertain_index": state.get("uncertain_index"),
        "intent_sha256": state["intent_sha256"],
        "root": intent["root"], "overlay": overlay,
        "steps": intent["steps"],
        "replay_allowed": False,
        "evidence": "marcadores verificados; nao autoriza retry, thaw ou rollback",
    }



def record_nt_commit_review_experimental(
        root, store_directory, case_id, evidence_sha256):
    """Create one immutable admin review annotation; NEVER unlock/replay.

    The case ID must reference a separately retained recovery dossier
    (snapshots, paths, identity, timestamps and signed human decision).
    Review only acknowledges evidence, it does not assert file recovery.
    """
    import re
    from datetime import datetime, timezone

    if (not isinstance(case_id, str) or
            re.fullmatch(r"[A-Za-z0-9_-]{6,64}", case_id) is None):
        raise ValueError("identificador de incidente administrativo invalido")
    if (not isinstance(evidence_sha256, str) or
            re.fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None):
        raise ValueError("SHA-256 de evidencias invalido")

    _require_privileged_enroller()
    report = inspect_nt_commit_for_operator(root, store_directory)
    if report["state"] == "absent":
        raise ValueError("sem INTENT nao ha commit para revisar")
    annotation = {
        "v": 1, "root": _canonical_root(root),
        "intent_sha256": report["intent_sha256"],
        "observed_state": report["state"],
        "case_id": case_id, "evidence_sha256": evidence_sha256,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "action": "review-recorded-no-retry-no-unlock",
    }
    payload = _json(annotation)
    with open_trusted_root(store_directory, read_control=True) as store:
        _assert_protected_acl(store)
        fresh = _inspect_open_store(store, root)
        if (fresh["state"] != report["state"] or
                fresh.get("intent_sha256") != report["intent_sha256"]):
            raise OSError("checkpoint mudou durante auditoria; anotacao recusada")
        _write_verified(store, _ledger_prefix(root) + ".review", payload)
    return annotation

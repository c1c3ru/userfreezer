#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXPERIMENTAL NT commit progress ledger (#63), deliberately fail-closed.

A pre-provisioned, ACL-checked store receives immutable files created with
NtCreateFile(FILE_CREATE); each is flushed before target mutations proceed.
The sequence is INTENT -> STARTED(i) -> native operation -> DONE(i), with a
final COMPLETE marker. No automatic retry, rollback or cleanup is offered.
A crash after STARTED but before DONE is INDETERMINATE, not a safe resume.
This module must NEVER be called from production thaw/CLI/IPC until reviewed.
"""
import hashlib
import json
import ntpath
import os

from nt_commit_experimental import _validate_plan
from nt_enrollment_experimental import _canonical_root, _checked_identity
from nt_enrollment_store_experimental import (
    _assert_protected_acl, load_identity_from_store,
)
from win32_relative_directory import (
    create_relative_file, directory_identity, open_trusted_root,
    read_relative_file,
)

SCHEMA = 1
MAX_STEPS = 256
MAX_INTENT_BYTES = 512 * 1024


class PendingNTCommitError(RuntimeError):
    """Checkpoint already exists: never overwrite or assume safe resume."""


class UncertainNTCommitError(RuntimeError):
    """Some operations may already have modified the target."""
    def __init__(self, index, path, cause):
        self.index = index
        self.path = path
        self.cause = cause
        super(UncertainNTCommitError, self).__init__(
            "commit NT possivelmente parcial na etapa %s (%s): %s; "
            "requer auditoria manual, sem rollback automatico" %
            (index, path, cause))


def _json(data):
    return (json.dumps(data, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def _ledger_prefix(root):
    return hashlib.sha256(_canonical_root(root).encode("utf-8")).hexdigest() + ".ntcommit"


def _separate_roots(root, overlay_root, store_directory):
    roots = [_canonical_root(value)
             for value in (root, overlay_root, store_directory)]
    for i in range(len(roots)):
        for j in range(i + 1, len(roots)):
            try:
                common = ntpath.commonpath((roots[i], roots[j]))
            except ValueError:
                continue  # different volumes
            if common in (roots[i], roots[j]):
                raise ValueError("alvo, overlay e cadastro NT devem ser separados")
    return roots


def _describe_plan(plan):
    checked = _validate_plan(plan)
    if not checked or len(checked) > MAX_STEPS:
        raise ValueError("plano de commit experimental vazio ou extenso")
    return [
        {"kind": kind, "path": rel,
         "size": len(payload) if payload is not None else 0,
         "sha256": hashlib.sha256(payload).hexdigest()
         if payload is not None else None}
        for kind, rel, _parts, payload in checked
    ]


def _intent_record(root, overlay, root_id, overlay_id, plan):
    steps = _describe_plan(plan)
    body = {
        "v": SCHEMA, "root": _canonical_root(root),
        "overlay": _canonical_root(overlay),
        "root_id": list(_checked_identity(root_id)),
        "overlay_id": list(_checked_identity(overlay_id)),
        "steps": steps,
    }
    body["digest"] = hashlib.sha256(_json(body)).hexdigest()
    data = _json(body)
    if len(data) > MAX_INTENT_BYTES:
        raise ValueError("intencao NT excede limite")
    return body, data


def _marker(index, kind, digest):
    return _json({"v": SCHEMA, "index": index, "kind": kind,
                  "intent_sha256": digest})


def _write_verified(parent, name, data):
    """Create exclusively, fsync file, reopen, check ACL and exact contents."""
    create_relative_file(parent, name, data)
    observed = read_relative_file(parent, name,
                                  max_bytes=max(1, len(data)),
                                  handle_guard=_assert_protected_acl)
    if observed != data:
        raise OSError("checkpoint NT diverge da gravacao confirmada")


def _read_optional(parent, name, max_bytes):
    try:
        return read_relative_file(parent, name, max_bytes=max_bytes,
                                  handle_guard=_assert_protected_acl)
    except OSError as exc:
        if getattr(exc, "winerror", None) in (2, 3):
            return None
        raise


def _parse_intent(data, expected_root):
    if not data or len(data) > MAX_INTENT_BYTES or not data.endswith(b"\n"):
        raise ValueError("intencao NT ausente, truncada ou extensa")
    try:
        record = json.loads(data.decode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("checkpoint NT invalido") from exc
    if (not isinstance(record, dict) or
            set(record) != {"v", "root", "overlay", "root_id",
                            "overlay_id", "steps", "digest"} or
            type(record["v"]) is not int or record["v"] != SCHEMA or
            record["root"] != _canonical_root(expected_root) or
            not isinstance(record["steps"], list) or
            not 1 <= len(record["steps"]) <= MAX_STEPS):
        raise ValueError("metadados da intencao NT invalidos")
    try:
        _canonical_root(record["overlay"])
        _checked_identity(tuple(record["root_id"]))
        _checked_identity(tuple(record["overlay_id"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("identidade/overlay do checkpoint invalido") from exc
    for step in record["steps"]:
        if (not isinstance(step, dict) or
                set(step) != {"kind", "path", "size", "sha256"} or
                type(step["size"]) is not int or step["size"] < 0):
            raise ValueError("etapa do checkpoint invalida")
        # No target mutation; validates canonical native path and kind.
        try:
            _validate_plan([(
                step["kind"], step["path"],
                b"" if step["kind"] == "W" else None)])
        except (TypeError, ValueError) as exc:
            raise ValueError("caminho do checkpoint invalido") from exc
        if (step["kind"] == "W" and
                (not isinstance(step["sha256"], str) or
                 len(step["sha256"]) != 64 or
                 any(c not in "0123456789abcdef" for c in step["sha256"]))):
            raise ValueError("hash do checkpoint invalido")
        if (step["kind"] != "W" and
                (step["size"] != 0 or step["sha256"] is not None)):
            raise ValueError("etapa nao-write tem dados")
    digest = record["digest"]
    unsigned = dict(record)
    unsigned.pop("digest")
    if (not isinstance(digest, str) or
            hashlib.sha256(_json(unsigned)).hexdigest() != digest or
            _json(record) != data):
        raise ValueError("checksum ou representacao de intencao invalida")
    return record


def _inspect_open_store(store_handle, root):
    prefix = _ledger_prefix(root)
    raw = _read_optional(store_handle, prefix + ".intent", MAX_INTENT_BYTES)
    if raw is None:
        return {"state": "absent", "completed": 0, "total": 0}
    intent = _parse_intent(raw, root)
    digest = intent["digest"]
    completed = 0
    active = None
    for index, _step in enumerate(intent["steps"]):
        started = _read_optional(store_handle, prefix + ".%05d.started" % index, 2048)
        done = _read_optional(store_handle, prefix + ".%05d.done" % index, 2048)
        if started is not None and started != _marker(index, "started", digest):
            raise ValueError("checkpoint STARTED adulterado")
        if done is not None and done != _marker(index, "done", digest):
            raise ValueError("checkpoint DONE adulterado")
        if done is not None and started is None:
            raise ValueError("DONE sem STARTED")
        if done is not None:
            if active is not None:
                raise ValueError("DONE posterior a etapa inconclusa")
            completed += 1
        elif started is not None:
            if active is not None:
                raise ValueError("multiplas etapas em curso")
            active = index
    complete = _read_optional(store_handle, prefix + ".complete", 2048)
    if complete is not None and complete != _marker(len(intent["steps"]), "complete", digest):
        raise ValueError("checkpoint COMPLETE adulterado")
    if complete is not None and (active is not None or completed != len(intent["steps"])):
        raise ValueError("COMPLETE sem todas as etapas confirmadas")
    if complete is not None:
        state = "complete"
    elif active is not None:
        state = "uncertain"
    else:
        state = "incomplete"
    return {"state": state, "completed": completed,
            "total": len(intent["steps"]), "uncertain_index": active,
            "intent_sha256": digest}


def inspect_nt_commit_checkpoint(root, store_directory):
    """Read-only inspection. Never assumes that 'done' means rollback."""
    _canonical_root(root)
    _canonical_root(store_directory)
    with open_trusted_root(store_directory, read_control=True) as store:
        _assert_protected_acl(store)
        return _inspect_open_store(store, root)


def apply_checkpointed_plan_experimental(
        root, overlay_root, store_directory, plan,
        after_operation=None):
    """Crash-conservative experimental NT executor with durable markers.

    A pre-existing intent blocks ALL new executions, even if COMPLETE.
    If a STARTED marker survives without DONE, effects are UNKNOWN.
    The store directory must have been provisioned with strict inherited
    SYSTEM/Administrators ACL, and both roots must be DPAPI-enrolled.
    """
    if os.name != "nt":
        raise OSError("checkpoint de commit NT exige Windows")
    root, overlay_root, store_directory = _separate_roots(
        root, overlay_root, store_directory)
    if after_operation is not None and not callable(after_operation):
        raise ValueError("callback de teste invalido")
    # Validate complete plan before opening checkpoint files.
    _describe_plan(plan)
    root_id = load_identity_from_store(root, store_directory)
    overlay_id = load_identity_from_store(overlay_root, store_directory)
    record, intent = _intent_record(root, overlay_root, root_id, overlay_id, plan)
    with open_trusted_root(root) as pinned:
        if directory_identity(pinned) != root_id:
            raise OSError("identidade da raiz NT divergente antes do commit")
    with open_trusted_root(overlay_root, read_control=True) as pinned:
        if directory_identity(pinned) != overlay_id:
            raise OSError("identidade do overlay NT divergente antes do commit")
        _assert_protected_acl(pinned)

    prefix = _ledger_prefix(root)
    from nt_commit_experimental import apply_enrolled_plan_experimental
    with open_trusted_root(store_directory, read_control=True) as store:
        _assert_protected_acl(store)
        # FILE_CREATE ensures an existing intent blocks *all* executions;
        # even a corrupted/truncated pending record is never overwritten.
        try:
            _write_verified(store, prefix + ".intent", intent)
        except OSError as exc:
            if getattr(exc, "winerror", None) in (80, 183):
                raise PendingNTCommitError(
                    "registro NT existente; consultar checkpoint, sem auto-retomada") from exc
            raise
        for index, step in enumerate(plan):
            name = record["steps"][index]["path"]
            try:
                _write_verified(store, prefix + ".%05d.started" % index,
                                _marker(index, "started", record["digest"]))
                apply_enrolled_plan_experimental(root, [step], root_id)
                if after_operation is not None:
                    after_operation(index, name)
                _write_verified(store, prefix + ".%05d.done" % index,
                                _marker(index, "done", record["digest"]))
            except BaseException as exc:
                # Never retry: native operation might have happened before
                # error/crash, including if the DONE marker write fails.
                raise UncertainNTCommitError(index, name, exc) from exc
        try:
            _write_verified(store, prefix + ".complete",
                            _marker(len(plan), "complete", record["digest"]))
        except BaseException as exc:
            raise UncertainNTCommitError(len(plan), "(complete)", exc) from exc
    return {"state": "complete", "completed": len(plan),
            "total": len(plan), "intent_sha256": record["digest"]}

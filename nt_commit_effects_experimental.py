#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only, handle-pinned NT commit effect observations (#63).

An observed SHA-256 match is NOT evidence of who wrote the bytes, NTFS
durability, successful commit, safe retry or successful recovery. This
component opens no destination via a pathname and changes no files.
"""
import contextlib
import hashlib

from nt_commit_experimental import _validate_plan
from nt_enrollment_experimental import _canonical_root, _checked_identity
from nt_enrollment_store_experimental import _assert_protected_acl
from win32_relative_directory import (
    directory_identity, open_trusted_root, open_relative_directory,
    read_relative_file,
)

MAX_SCAN_FILE_BYTES = 16 * 1024 * 1024
MAX_SCAN_TOTAL_BYTES = 64 * 1024 * 1024
_MISSING_ERRORS = (2, 3)


def _read_write_effect(pinned_root, rel, max_bytes):
    """Return bytes or None for proven absence; raise on any other failure."""
    _validate_plan([("W", rel, b"")])
    components = rel.split("/")
    with contextlib.ExitStack() as stack:
        parent = pinned_root
        for name in components[:-1]:
            try:
                parent = stack.enter_context(
                    open_relative_directory(parent, name, read_control=True))
            except OSError as exc:
                if getattr(exc, "winerror", None) in _MISSING_ERRORS:
                    return None
                raise
            _assert_protected_acl(parent)
        try:
            return read_relative_file(
                parent, components[-1], max_bytes=max_bytes,
                handle_guard=_assert_protected_acl)
        except OSError as exc:
            if getattr(exc, "winerror", None) in _MISSING_ERRORS:
                return None
            raise


def inspect_nt_commit_write_effects(root, expected_root_identity, steps):
    """Inspect W writes on a freshly pinned, enrolled NT root.

    Never examines M/F/D as if a pathname's current presence could prove
    the operation was performed. Any access/ACL/reparse/size failure is
    recorded as unverifiable; it does not make a transaction retryable.
    """
    _canonical_root(root)
    _checked_identity(expected_root_identity)
    if not isinstance(steps, list) or len(steps) > 256:
        raise ValueError("etapas de auditoria NT invalidas")
    if any(not isinstance(step, dict) or
           not {"kind", "path", "size", "sha256"}.issubset(step)
           for step in steps):
        raise ValueError("etapa de auditoria NT malformada")

    observations = []
    total = 0
    with open_trusted_root(root, read_control=True) as pinned:
        if directory_identity(pinned) != expected_root_identity:
            raise OSError("raiz NT alterada antes de ler efeitos do commit")
        _assert_protected_acl(pinned)
        for index, step in enumerate(steps):
            kind, rel = step["kind"], step["path"]
            if kind != "W":
                observations.append({
                    "index": index, "kind": kind, "path": rel,
                    "observation": "not_verified_for_nonwrite"})
                continue
            _validate_plan([("W", rel, b"")])
            size = step["size"]
            digest = step["sha256"]
            if (type(size) is not int or size < 0 or
                    not isinstance(digest, str) or len(digest) != 64):
                raise ValueError("metadados de write NT invalidos")
            if (size > MAX_SCAN_FILE_BYTES or total + size > MAX_SCAN_TOTAL_BYTES
                    or total >= MAX_SCAN_TOTAL_BYTES):
                observations.append({
                    "index": index, "kind": kind, "path": rel,
                    "observation": "not_verified_budget"})
                continue
            try:
                data = _read_write_effect(
                    pinned, rel,
                    min(MAX_SCAN_FILE_BYTES, MAX_SCAN_TOTAL_BYTES - total))
                if data is None:
                    status = "missing"
                else:
                    total += len(data)
                    status = ("matches_recorded_hash"
                              if len(data) == size and
                              hashlib.sha256(data).hexdigest() == digest
                              else "differs_from_recorded_hash")
            except (OSError, ValueError, PermissionError):
                # Includes ACL violation, reparse point, sharing violations,
                # file larger than bounded limit, and unexpected file type.
                status = "unverifiable"
            observations.append({
                "index": index, "kind": kind, "path": rel,
                "observation": status})
    return {
        "steps": observations,
        "bytes_scanned": total,
        "safe_to_retry": False,
        "evidence": "fotografia de leitura, sem prova de origem nem durabilidade",
    }

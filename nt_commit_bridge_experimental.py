#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXPERIMENTAL: build a complete native NT plan from core journal entries.

This adapter is NOT used by DeepFreezer._apply_commit, CLI or IPC.
The caller must supply a trusted, verified payload loader; this module cannot
authenticate overlay payload pathnames or their ACLs. No Windows production
commit is enabled. The native backend is not transactional and may partially
complete after preflight succeeds. See issue #63.
"""

from nt_commit_experimental import _validate_plan

MAX_PLAN_ITEMS = 10000
MAX_PAYLOAD = 16 * 1024 * 1024
MAX_TOTAL_PAYLOAD = 64 * 1024 * 1024


def prepare_native_plan(entries, payload_loader,
                        max_payload=MAX_PAYLOAD,
                        max_total=MAX_TOTAL_PAYLOAD):
    """Validate EVERY journal record before loading any write payload.

    Each input entry is (parts, kind, is_dir, source), matching the shape
    assembled by the core, but source must come from trusted code.
    W -> NT W with bytes; M -> NT M; D -> NT F or NT D by is_dir.
    Nothing is applied until every item, path and payload passes preflight.
    """
    if not isinstance(entries, (list, tuple)) or len(entries) > MAX_PLAN_ITEMS:
        raise ValueError("plano do core invalido ou extenso")
    if not callable(payload_loader):
        raise ValueError("leitor de payload obrigatorio")
    if (type(max_payload) is not int or
            not 1 <= max_payload <= MAX_PAYLOAD or
            type(max_total) is not int or
            not 1 <= max_total <= MAX_TOTAL_PAYLOAD):
        raise ValueError("limite de payload NT invalido")

    metadata = []
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) != 4:
            raise ValueError("entrada do core invalida")
        parts, kind, is_dir, source = entry
        if (not isinstance(parts, (list, tuple)) or not parts or
                not all(isinstance(p, str) for p in parts)):
            raise ValueError("componentes do plano NT invalidos")
        if type(is_dir) is not int or is_dir not in (0, 1):
            raise ValueError("flag de diretorio invalida")
        relative = "/".join(parts)
        if kind == "W":
            if is_dir != 0 or not isinstance(source, str) or not source:
                raise ValueError("origem de escrita invalida")
            native_kind = "W"
        elif kind == "M":
            if is_dir != 1 or source is not None:
                raise ValueError("mkdir com metadados invalidos")
            native_kind = "M"
        elif kind == "D":
            if source is not None:
                raise ValueError("delete com payload invalido")
            native_kind = "D" if is_dir else "F"
        else:
            raise ValueError("tipo de journal invalido")
        metadata.append((native_kind, relative, source))
    # Enforce native Windows path rules on the whole plan before invoking
    # any external payload loader.
    _validate_plan([
        (kind, relative, b"" if kind == "W" else None)
        for kind, relative, _source in metadata
    ])

    plan = []
    total = 0
    for kind, relative, source in metadata:
        if kind == "W":
            payload = payload_loader(source, min(max_payload, max_total - total))
            if not isinstance(payload, bytes):
                raise ValueError("payload NT deve ser bytes")
            if len(payload) > max_payload or total + len(payload) > max_total:
                raise ValueError("limite total de payload NT excedido")
            total += len(payload)
        else:
            payload = None
        plan.append((kind, relative, payload))

    # Validate the final assembled plan, not just its metadata.
    _validate_plan(plan)
    return plan


def apply_prepared_plan_experimental(
        root, entries, store_directory, payload_loader,
        max_payload=MAX_PAYLOAD, max_total=MAX_TOTAL_PAYLOAD):
    """Experimental only: preflight ALL operations before native mutation.

    Store identity verification happens in the isolated enrollment layer.
    This method is intentionally not imported by the production core.
    """
    plan = prepare_native_plan(
        entries, payload_loader, max_payload=max_payload, max_total=max_total)
    from nt_enrollment_store_experimental import apply_stored_plan_experimental
    return apply_stored_plan_experimental(root, plan, store_directory)



def apply_pinned_overlay_plan_experimental(
        root, entries, store_directory, overlay_root,
        expected_overlay_identity,
        max_payload=MAX_PAYLOAD, max_total=MAX_TOTAL_PAYLOAD):
    """Use a pinned ACL-checked overlay reader for the native plan.

    Source entries are relative names under payloads/ or files/, NOT
    absolute pathname strings from the core. Still isolated from production.
    There is no durable journal progress or rollback after partial failure.
    """
    from nt_overlay_payload_experimental import pinned_overlay_payload_loader
    from nt_enrollment_store_experimental import apply_stored_plan_experimental
    with pinned_overlay_payload_loader(
            overlay_root, expected_overlay_identity) as loader:
        plan = prepare_native_plan(
            entries, loader, max_payload=max_payload, max_total=max_total)
        return apply_stored_plan_experimental(root, plan, store_directory)



def apply_reconciled_plan_experimental(
        root, overlay_root, store_directory,
        core_ops, core_payload_ids, core_seq,
        max_payload=MAX_PAYLOAD, max_total=MAX_TOTAL_PAYLOAD):
    """Pinned journal + pinned payload + enrolled target, all experimental.

    The in-memory plan is never authoritative on its own. Journal and
    manifest are reread by a handle and compared to core state before
    preparing any native operations. Not wired into DeepFreezer.thaw().
    """
    from nt_overlay_journal_experimental import (
        prepare_verified_journal_entries_experimental,
    )
    from nt_enrollment_store_experimental import load_identity_from_store
    entries = prepare_verified_journal_entries_experimental(
        root, overlay_root, store_directory,
        core_ops, core_payload_ids, core_seq)
    overlay_id = load_identity_from_store(overlay_root, store_directory)
    return apply_pinned_overlay_plan_experimental(
        root, entries, store_directory, overlay_root, overlay_id,
        max_payload=max_payload, max_total=max_total)

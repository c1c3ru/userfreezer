#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only forensic NT checkpoint inspection (#63).

This is NOT a recovery/clear/retry command. Every observed object must match
the pre-enrolled Windows identity; an untrusted or missing object fails closed.
"""
from nt_commit_checkpoint_experimental import (
    _parse_intent, _read_optional, _ledger_prefix, _inspect_open_store,
    MAX_INTENT_BYTES,
)
from nt_enrollment_experimental import _canonical_root
from nt_enrollment_store_experimental import (
    _assert_protected_acl, load_identity_from_store,
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXPERIMENTAL: create-once/read NT enrollment with strict handle ACL checks.

The experimental first-enrollment operation creates only a new record in a
PRE-PROVISIONED protected store (no overwrite), requiring an effective elevated
administrator or SYSTEM token. No directory provisioning, privileged IPC,
anti-replay, rollback, or Windows 7 SP1 VM evidence is provided.

The directory and file handles are opened without following reparse points.
Only owner SYSTEM/Administrators and allow ACEs for those two SIDs pass.
Other ACLs are rejected, including unknown ACE types and NULL DACLs.
No service, CLI or production commit path imports this enrollment API.
"""
import hashlib

from nt_enrollment_experimental import (_canonical_root, seal_root_identity,
                                        unseal_root_identity)
from win32_relative_directory import (open_trusted_root, read_relative_file,
                                      directory_identity, create_relative_file)

_SYSTEM = "S-1-5-18"
_ADMINS = "S-1-5-32-544"
_TRUSTED = (_SYSTEM, _ADMINS)


def record_name_for_root(root):
    """Deterministic opaque filename; never accept caller-supplied filenames."""
    root = _canonical_root(root)
    return hashlib.sha256(root.encode("utf-8")).hexdigest() + ".dpapi"


def _validate_acl_entries(owner_sid, entries):
    """Conservative ACL policy: only SYSTEM and local Administrators allowed.

    Entries are (type, SID) pairs. ACE type 0 is allow, type 1 is deny;
    callback/object ACE types fail closed, as their semantics need audit.
    """
    if owner_sid not in _TRUSTED or not isinstance(entries, (list, tuple)):
        raise PermissionError("owner ou DACL de enrollment nao confiavel")
    if not any(typ == 0 and sid in _TRUSTED for typ, sid in entries):
        raise PermissionError("enrollment sem acesso de conta confiavel")
    for typ, sid in entries:
        if type(typ) is not int or typ not in (0, 1):
            raise PermissionError("tipo ACE de enrollment nao auditado")
        if typ == 0 and sid not in _TRUSTED:
            raise PermissionError("DACL concede acesso a identidade nao confiavel")
    return True


def _assert_protected_acl(handle):
    """Read owner and DACL from the *opened handle*, never by pathname."""
    try:
        import win32security as security
    except ImportError as exc:
        raise RuntimeError("pywin32 e necessario para conferir ACL NT") from exc
    raw = handle.value if hasattr(handle, "value") else int(handle)
    info = (security.OWNER_SECURITY_INFORMATION |
            security.DACL_SECURITY_INFORMATION)
    descriptor = security.GetSecurityInfo(raw, security.SE_FILE_OBJECT, info)
    owner = descriptor.GetSecurityDescriptorOwner()
    acl = descriptor.GetSecurityDescriptorDacl()
    if owner is None or acl is None:
        raise PermissionError("owner/DACL ausentes no enrollment")
    entries = []
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if len(ace) < 3 or len(ace[0]) < 1:
            raise PermissionError("ACE invalida no enrollment")
        entries.append((ace[0][0], security.ConvertSidToStringSid(ace[2])))
    _validate_acl_entries(security.ConvertSidToStringSid(owner), entries)


def _require_privileged_enroller():
    """Authorize against effective Windows token, including impersonation.

    A filtered UAC token or unprivileged impersonated named-pipe caller must
    not enroll a root, even if the service process itself runs as SYSTEM.
    """
    import os
    if os.name != "nt":
        raise PermissionError("enrollment administrativo exige Windows")
    import pywintypes
    import win32api
    import win32con
    import win32security as sec
    try:
        token = sec.OpenThreadToken(
            win32api.GetCurrentThread(), win32con.TOKEN_QUERY, True)
    except pywintypes.error as exc:
        if exc.winerror != 1008:  # ERROR_NO_TOKEN, not an auth failure
            raise
        token = sec.OpenProcessToken(
            win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user_sid = sec.GetTokenInformation(token, sec.TokenUser)[0]
        if sec.ConvertSidToStringSid(user_sid) == _SYSTEM:
            return
        admin_sid = sec.CreateWellKnownSid(
            sec.WinBuiltinAdministratorsSid, None)
        if not sec.CheckTokenMembership(token, admin_sid):
            raise PermissionError("token elevado de administrador exigido")
    finally:
        token.Close()


def enroll_root_once_experimental(root, store_directory):
    """Create a first enrollment without ever replacing an existing record.

    The store directory must already exist and pass the strict handle ACL
    policy. The caller must execute under the same privileged Windows account
    that will later unseal the DPAPI blob; this does NOT provision the store.
    No automatic rollback: on failed verification, the newly created file
    might require an operator to inspect it. Never called by service or CLI.
    """
    _canonical_root(root)
    _canonical_root(store_directory)
    name = record_name_for_root(root)
    _require_privileged_enroller()
    with open_trusted_root(store_directory, read_control=True) as store:
        _assert_protected_acl(store)
        with open_trusted_root(root) as pinned:
            enrolled = directory_identity(pinned)
            sealed = seal_root_identity(root, enrolled)
        if not isinstance(sealed, bytes) or not 1 <= len(sealed) <= 16384:
            raise ValueError("blob DPAPI de cadastro invalido")
        # FILE_CREATE is an atomic create-only operation. Existing or stale
        # records must NEVER be replaced by an implicit re-enrollment.
        create_relative_file(store, name, sealed)
        # Reopen the new record by a pinned parent, verify its inherited ACL
        # and read back the DPAPI identity before declaring enrollment valid.
        observed_blob = read_relative_file(
            store, name, max_bytes=16384,
            handle_guard=_assert_protected_acl)
        if unseal_root_identity(root, observed_blob) != enrolled:
            raise OSError("identidade do enrollment gravado diverge")
        return enrolled


def load_identity_from_store(root, store_directory):
    """Load a sealed root identity from an already-provisioned protected store.

    The account executing this function must match the DPAPI principal that
    created the envelope. No mkdir, file creation, ACL mutation or fallback.
    """
    _canonical_root(store_directory)
    name = record_name_for_root(root)
    with open_trusted_root(store_directory, read_control=True) as directory:
        _assert_protected_acl(directory)
        sealed = read_relative_file(
            directory, name, max_bytes=16384,
            handle_guard=_assert_protected_acl)
    return unseal_root_identity(root, sealed)


def apply_stored_plan_experimental(root, plan, store_directory):
    """Experimental strict commit entry; never wired to the official core."""
    identity = load_identity_from_store(root, store_directory)
    from nt_commit_experimental import apply_enrolled_plan_experimental
    return apply_enrolled_plan_experimental(root, plan, identity)

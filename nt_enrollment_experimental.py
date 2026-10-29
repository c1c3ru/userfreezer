#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXPERIMENTAL: DPAPI-bound NT root identity envelope (#63).

No disk persistence, ACL enrollment, privileged IPC or production commit
integration is provided here. DPAPI uses the *current Windows account*
(no LOCAL_MACHINE flag): a blob sealed by the service account is not a
caller-controlled identity tuple. The caller must still guarantee that
enrollment was authorized and that the blob is stored without replay or
replacement by untrusted users. This alone does not resolve issue #63.
"""
import hmac
import json
import ntpath
import os

from win32_relative_directory import _validate_component

_ENTROPY = b"UserFreezer/NT-root-identity/enrollment-v1"
_FORMAT = 1
_MAX_BLOB = 16384
_MAX_RECORD = 4096
_NO_UI = 0x1  # CRYPTPROTECT_UI_FORBIDDEN, supported since Windows XP.


def _canonical_root(root):
    if not isinstance(root, str) or not root or len(root) > 2048:
        raise ValueError("raiz NT invalida")
    drive, tail = ntpath.splitdrive(root)
    if (len(drive) != 2 or drive[1] != ":"
            or not drive[0].isascii() or not drive[0].isalpha()
            or not tail.startswith("\\")
            or root.startswith("\\\\")
            or "/" in root or ntpath.normpath(root) != root):
        raise ValueError("raiz NT precisa ser caminho local canonico")
    parts = [p for p in tail.split("\\") if p]
    if not parts:
        raise ValueError("nao e permitido cadastrar raiz inteira do volume")
    for part in parts:
        _validate_component(part)
    return ntpath.normcase(root)


def _checked_identity(identity):
    if (not isinstance(identity, tuple) or len(identity) != 3
            or any(not isinstance(x, int) or isinstance(x, bool)
                   or not 0 <= x <= 0xffffffff for x in identity)):
        raise ValueError("identidade NT invalida")
    return identity


def _dpapi():
    if os.name != "nt":
        raise OSError("DPAPI NT exige Windows")
    try:
        import win32crypt
    except ImportError as exc:
        raise RuntimeError("win32crypt (pywin32) necessario") from exc
    return win32crypt


def seal_root_identity(root, identity):
    """Seal identity with current Windows principal, not machine-wide DPAPI.

    Invoke during an explicit authenticated privileged enrollment, never
    by reading root identity at the moment an operation is requested.
    """
    canonical = _canonical_root(root)
    identity = _checked_identity(identity)
    raw = json.dumps(
        {"v": _FORMAT, "root": canonical, "identity": list(identity)},
        separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > _MAX_RECORD:
        raise ValueError("registro NT extenso")
    return _dpapi().CryptProtectData(
        raw, "UserFreezer NT root identity v1", _ENTROPY,
        None, None, _NO_UI)


def unseal_root_identity(root, sealed):
    """Validate DPAPI, bind root pathname and return enrolled object ID."""
    canonical = _canonical_root(root)
    if not isinstance(sealed, bytes) or not 1 <= len(sealed) <= _MAX_BLOB:
        raise ValueError("envelope NT ausente ou invalido")
    try:
        _description, raw = _dpapi().CryptUnprotectData(
            sealed, _ENTROPY, None, None, _NO_UI)
    except Exception as exc:
        raise OSError("envelope NT nao autenticado neste contexto") from exc
    if not isinstance(raw, bytes) or len(raw) > _MAX_RECORD:
        raise ValueError("registro NT corrompido")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("JSON de enrollment NT invalido") from exc
    if not isinstance(record, dict) or set(record) != {"v", "root", "identity"}:
        raise ValueError("formato de enrollment NT invalido")
    if type(record["v"]) is not int or record["v"] != _FORMAT:
        raise ValueError("versao de enrollment NT invalida")
    if (not isinstance(record["root"], str)
            or not hmac.compare_digest(record["root"], canonical)):
        raise ValueError("enrollment pertence a outra raiz NT")
    identity = record["identity"]
    if not isinstance(identity, list):
        raise ValueError("identidade do enrollment nao e lista")
    return _checked_identity(tuple(identity))


def apply_sealed_plan_experimental(root, plan, sealed):
    """Only an authentic enrolled identity may reach the strict NT plan.

    Not wired to the service, user interface, or official commit.
    """
    identity = unseal_root_identity(root, sealed)
    from nt_commit_experimental import apply_enrolled_plan_experimental
    return apply_enrolled_plan_experimental(root, plan, identity)

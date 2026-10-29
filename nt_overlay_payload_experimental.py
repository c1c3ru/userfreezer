#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXPERIMENTAL pinned NT overlay reader (#63), not production commit.

A trusted pre-enrolled overlay identity is mandatory. Paths are overlay
relative; any path to payloads outside the pinned handle tree is refused.
Handle ACL checks reject ordinary-user writes. Windows 7 SP1, ACL policy
and journal provenance still require independent VM review.
"""
import contextlib

from nt_enrollment_experimental import _canonical_root, _checked_identity
from nt_enrollment_store_experimental import _assert_protected_acl
from win32_relative_directory import (
    _validate_component, directory_identity, open_trusted_root,
    open_relative_directory, read_relative_file,
)

MAX_PAYLOAD_BYTES = 16 * 1024 * 1024


def _parse_overlay_source(source):
    """Accept only immutable journal payload IDs or explicit legacy paths."""
    if not isinstance(source, str) or not source or len(source) > 2048:
        raise ValueError("fonte de payload NT invalida")
    parts = source.split("/")
    if (len(parts) < 2 or parts[0] not in ("payloads", "files")
            or any(not part for part in parts)):
        raise ValueError("payload deve estar abaixo de payloads/ ou files/")
    for part in parts:
        _validate_component(part)
    if parts[0] == "payloads":
        ident = parts[1]
        if (len(parts) != 2 or not 1 <= len(ident) <= 32
                or not ident.isascii() or not ident.isdigit()):
            raise ValueError("ID imutavel do payload invalido")
    return parts


@contextlib.contextmanager
def pinned_overlay_payload_loader(overlay_root, expected_overlay_identity):
    """Yield a bounded loader rooted in handles, checking each ACL.

    Enrollment of overlay identity must happen when freezing under a trusted
    token, independently of the pathname used at commit time. This module
    has NO enrollment or permissions to bypass missing identity.
    """
    _canonical_root(overlay_root)
    expected = _checked_identity(expected_overlay_identity)
    with open_trusted_root(overlay_root, read_control=True) as root:
        if directory_identity(root) != expected:
            raise OSError("identidade do overlay NT diverge do cadastro")
        _assert_protected_acl(root)

        def load(source, limit):
            parts = _parse_overlay_source(source)
            if (type(limit) is not int or
                    not 1 <= limit <= MAX_PAYLOAD_BYTES):
                raise ValueError("limite de payload NT invalido")
            with contextlib.ExitStack() as stack:
                parent = root
                for component in parts[:-1]:
                    parent = stack.enter_context(
                        open_relative_directory(
                            parent, component, read_control=True))
                    _assert_protected_acl(parent)
                return read_relative_file(
                    parent, parts[-1], max_bytes=limit,
                    handle_guard=_assert_protected_acl)
        yield load

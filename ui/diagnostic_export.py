#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Allowlisted, privacy-preserving IPC status export for the unprivileged UI.

Never serialize the raw broker snapshot: target/overlay paths, error messages,
future IPC fields, authorization tokens and internal service data may contain
secrets or local identities. This module has no privileged operations.
Python 3.8+ and Windows 7 compatible.
"""
import json
import os
import re
import tempfile


MAX_TARGETS = 256
MAX_EXPORT_BYTES = 128 * 1024
MAX_COUNT = 10**12
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
    r"(?:Z|[+-]\d{2}:\d{2})\Z"
)
_TARGET_STATES = frozenset(("healthy", "degraded", "error",
                            "unknown", "unavailable", "frozen",
                            "thawed", "pending"))
_OS_STATES = frozenset(("configured", "pending", "pending_reboot", "active",
                        "failed", "unverified", "unknown", "disabled"))
_OS_SCOPES = frozenset(("directory", "volume", "rootfs", "unknown",
                        "application-level", "os-level"))
_OS_STRATEGIES = frozenset(("overlayfs", "uwf", "ewf", "fbwf", "vhdx",
                            "unknown", "none"))
_PENDING_TYPES = ("W", "M", "D")


def _enum(value, allowed, default="unknown"):
    return value if isinstance(value, str) and value in allowed else default


def _count(value):
    # bool is an int subclass, but not a meaningful byte/path count.
    return value if type(value) is int and 0 <= value <= MAX_COUNT else None


def _timestamp(value):
    return value if isinstance(value, str) and _TIMESTAMP.fullmatch(value) else None


def sanitize_diagnostic(snapshot):
    """Copy *only* explicitly approved scalars, never raw IPC objects.

    Stable target IDs refer only to this single exported report; no target,
    overlay or other local paths are retained. Errors are reduced to a flag
    rather than arbitrary strings that may contain usernames/tokens.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("resposta IPC nao e objeto")
    targets = snapshot.get("targets")
    if not isinstance(targets, list) or len(targets) > MAX_TARGETS:
        raise ValueError("lista de alvos de diagnostico invalida")
    safe = {
        "schema_version": 1,
        "redacted": True,
        "scope": "application-level",
        "service_state": _enum(snapshot.get("state"), _TARGET_STATES),
        "last_enforcement_utc": _timestamp(snapshot.get("timestamp")),
        "target_count": len(targets),
        "targets": [],
    }
    for i, entry in enumerate(targets, 1):
        if not isinstance(entry, dict):
            raise ValueError("alvo IPC de diagnostico invalido")
        os_level = entry.get("os_level")
        if not isinstance(os_level, dict):
            os_level = {}
        pending = entry.get("pending_ops")
        if not isinstance(pending, dict):
            pending = {}
        safe["targets"].append({
            "id": "target-%03d" % i,
            "api_state": _enum(entry.get("state"), _TARGET_STATES),
            "frozen": entry.get("frozen")
            if type(entry.get("frozen")) is bool else None,
            "baseline_paths": _count(entry.get("baseline_paths")),
            "overlay_bytes": _count(entry.get("overlay_bytes")),
            "overlay_size_partial": entry.get("overlay_size_partial") is True,
            "pending_ops": {
                key: _count(pending.get(key)) for key in _PENDING_TYPES
            },
            "error_present": bool(entry.get("error") or
                                  entry.get("runtime_error") or
                                  os_level.get("error")),
            "os_level": {
                "state": _enum(os_level.get("state"), _OS_STATES, "unverified"),
                "strategy": _enum(os_level.get("strategy"), _OS_STRATEGIES),
                "scope": _enum(os_level.get("scope"), _OS_SCOPES),
                "reboot_verified": os_level.get("reboot_verified") is True,
            },
        })
    return safe


def export_sanitized_diagnostic(snapshot, destination):
    """Atomic export (private temporary file where supported); reject oversized reports.

    os.replace() replaces the selected destination only after bytes are
    flushed. An existing symlink is replaced, not followed. The caller
    decides where to save; no directory creation or privilege elevation.
    """
    if not isinstance(destination, str):
        raise ValueError("destino de diagnostico invalido")
    final_path = destination
    if not final_path:
        raise ValueError("destino de diagnostico vazio")
    safe = sanitize_diagnostic(snapshot)
    data = (json.dumps(safe, sort_keys=True, indent=2,
                       ensure_ascii=False) + "\n").encode("utf-8")
    if len(data) > MAX_EXPORT_BYTES:
        raise ValueError("diagnostico excede limite seguro")
    directory = os.path.dirname(os.path.abspath(final_path))
    fd, temporary = tempfile.mkstemp(
        prefix=".deepfreezer-diagnostic-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, final_path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    return safe

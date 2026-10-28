#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Snapshot de saude do enforcement (NAO comprova protecao OS-level).

Python 3.8+/Windows 7, somente biblioteca padrao.
"""
import datetime
import json
import os


def health_summary(targets, config_error=None):
    targets = list(targets)
    good = sum(1 for item in targets if item.get("state") == "healthy")
    if config_error or not targets or good == 0:
        state = "error"
    elif good != len(targets):
        state = "degraded"
    else:
        state = "healthy"
    return {
        "schema_version": 1,
        "last_enforcement_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "protection_scope": "application-level",
        "state": state,
        "successful_targets": good,
        "total_targets": len(targets),
        "config_error": config_error,
        "targets": targets,
    }


def publish_health(path, targets, config_error=None, hardener=None):
    """Grava snapshot com fsync + replace; hardener protege ANTES da troca."""
    report = health_summary(targets, config_error)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, mode=0o700, exist_ok=True)
    if os.name != "nt":
        os.chmod(folder, 0o700)
    tmp = os.path.join(folder, ".deepfreezer-status-%d.tmp" % os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(report, out, sort_keys=True, ensure_ascii=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        if hardener is not None:
            hardener(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)
    return report

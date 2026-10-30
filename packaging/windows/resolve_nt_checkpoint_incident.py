#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Administrative NT incident closure record (does not enable retry)."""
import argparse
import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Registrar resolucao administrativa NT sem desbloquear commit")
    parser.add_argument("--target", required=True)
    parser.add_argument("--store", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--inspect", action="store_true")
    group.add_argument("--record", action="store_true")
    parser.add_argument("--incident")
    parser.add_argument("--approval-id")
    parser.add_argument("--recovery-evidence-sha256")
    parser.add_argument("--decision", choices=(
        "restored_from_verified_snapshot", "manually_reconciled"))
    parser.add_argument("--acknowledge-no-retry", action="store_true")
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("somente Windows")
    from nt_commit_resolution_experimental import (
        inspect_nt_incident_resolution_experimental,
        record_nt_incident_resolution_experimental,
    )
    if args.record and (
            not args.acknowledge_no_retry or not args.incident or
            not args.approval_id or not args.recovery_evidence_sha256 or
            not args.decision):
        parser.error("registro exige incidente, aprovacao, evidencia, decisao e "
                     "--acknowledge-no-retry")
    try:
        if args.record:
            item = record_nt_incident_resolution_experimental(
                args.target, args.store, args.incident, args.approval_id,
                args.recovery_evidence_sha256, args.decision)
            payload = {"recorded": True, "retry_allowed": False,
                       "resolution": item}
        else:
            payload = inspect_nt_incident_resolution_experimental(
                args.target, args.store)
    except (OSError, ValueError, PermissionError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "retry_allowed": False,
                          "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

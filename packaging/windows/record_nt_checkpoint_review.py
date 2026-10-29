#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append-only administrative acknowledgement of an NT commit incident.

Requires a Windows elevated SYSTEM/Administrator effective token and
independent, immutable recovery evidence. NEVER unlocks or retries commit.
"""
import argparse
import json
import os
import sys


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--incident", required=True,
                        help="opaque external incident ID, 6..64 ASCII chars")
    parser.add_argument("--evidence-sha256", required=True,
                        help="SHA-256 of external incident evidence bundle")
    parser.add_argument("--acknowledge-no-unlock", action="store_true")
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("somente Windows")
    if not args.acknowledge_no_unlock:
        parser.error("exige --acknowledge-no-unlock (NÃO autoriza retry)")
    from nt_commit_forensics_experimental import (
        record_nt_commit_review_experimental,
    )
    try:
        review = record_nt_commit_review_experimental(
            args.target, args.store, args.incident, args.evidence_sha256)
    except (OSError, ValueError, RuntimeError, PermissionError) as exc:
        print(json.dumps({"recorded": False, "retry_authorized": False,
                          "error": str(exc)}, sort_keys=True),
              file=sys.stderr)
        return 2
    print(json.dumps({"recorded": True, "retry_authorized": False,
                      "review": review}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

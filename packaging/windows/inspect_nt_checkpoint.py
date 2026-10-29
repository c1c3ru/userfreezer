#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Windows NT checkpoint forensic report for an administrator.

This script DOES NOT resume, rollback, remove markers or alter the target.
Run using the same Windows account that holds the DPAPI root enrollments.
"""
import argparse
import json
import os
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Inspecionar checkpoint NT sem mutacoes (issue #63)")
    parser.add_argument("--target", required=True,
                        help="raiz NT cadastrada (ex.: C:\\Lab\\Protected)")
    parser.add_argument("--store", required=True,
                        help="diretorio protegido e preprovisionado de cadastros")
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("somente Windows")
    from nt_commit_forensics_experimental import (
        inspect_nt_commit_for_operator,
    )
    try:
        result = inspect_nt_commit_for_operator(args.target, args.store)
    except (OSError, ValueError, PermissionError, RuntimeError) as exc:
        print(json.dumps({
            "inspection": "error", "resume_allowed": False,
            "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"inspection": "read-only", "resume_allowed": False,
                      "report": result}, sort_keys=True, indent=2))
    # Exit 0 means the report was obtained, NEVER that commit/recovery passed.
    return 0


if __name__ == "__main__":
    sys.exit(main())

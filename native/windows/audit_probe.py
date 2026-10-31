#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only local Filter Manager inspection for the Windows LAB observer.

'Loaded' and 'attached' are NOT proof of write redirection or reboot rollback.
Does not install/start/stop drivers. Python 3.8+ stdlib.
"""
import argparse
import json
import os
import re
import subprocess
import sys

FILTER_NAME = "UserFreezerAudit"
LINE = re.compile(
    r"^\s*UserFreezerAudit\s+(?P<count>[0-9]+)\s+"
    r"(?P<altitude>[0-9]+(?:\.[0-9]+)?)\s+(?P<frame>[0-9]+)\s*$",
    re.IGNORECASE,
)


def parse_filters(stdout):
    """Return only an exact Filter Manager list entry, never substring matches."""
    if not isinstance(stdout, str) or len(stdout) > 262144:
        raise ValueError("Invalid fltmc output")
    matches = [m for line in stdout.splitlines()
               for m in [LINE.fullmatch(line)] if m]
    if len(matches) > 1:
        raise ValueError("Duplicate driver name in Filter Manager listing")
    if not matches:
        return None
    match = matches[0]
    count = int(match.group("count"))
    if count > 65535:
        raise ValueError("Invalid instance count")
    return {
        "filter_name": FILTER_NAME,
        "instances_reported": count,
        "altitude_reported": match.group("altitude"),
        "frame_reported": int(match.group("frame")),
    }


def inspect(system=None, runner=None):
    observed_platform = os.name if system is None else system
    result = {
        "schema": "uf-native-audit-probe-v1",
        "state": "unsupported" if observed_platform != "nt" else "unverified",
        "observer_driver_loaded": False,
        "instance_count_reported": None,
        "driver_callback_execution_verified": False,
        "kernel_write_redirection_verified": False,
        "reboot_rollback_verified": False,
        "os_level_protection_active": False,
        "source": "fltmc-read-only" if observed_platform == "nt" else "windows-only",
    }
    if observed_platform != "nt":
        return result
    call = runner or subprocess.run
    try:
        check = call(
            ["fltmc.exe", "filters"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, universal_newlines=True,
            timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        result["state"] = "error"
        result["error"] = "fltmc indisponivel ou expirou"
        return result
    if check.returncode != 0:
        result["state"] = "error"
        result["error"] = "falha na consulta do Filter Manager"
        return result
    try:
        parsed = parse_filters(check.stdout)
    except ValueError:
        result["state"] = "error"
        result["error"] = "resposta fltmc invalida ou ambigua"
        return result
    if parsed is None:
        result["state"] = "not-loaded"
        return result
    result["state"] = "observer-listed-not-protection"
    result["observer_driver_loaded"] = True
    result["instance_count_reported"] = parsed["instances_reported"]
    result["altitude_reported"] = parsed["altitude_reported"]
    result["frame_reported"] = parsed["frame_reported"]
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", help="Caminho privado opcional para JSON somente de estado")
    args = p.parse_args(argv)
    result = inspect()
    text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.json:
        with open(args.json, "x", encoding="utf-8") as out:
            out.write(text)
    else:
        print(text, end="")
    return 0 if result["state"] != "error" else 2


if __name__ == "__main__":
    sys.exit(main())

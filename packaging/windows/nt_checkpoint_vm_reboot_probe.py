#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two-phase, disposable-VM-only NT checkpoint crash/reboot probe (#63).

Does NOT reboot automatically. Deliberately uses mocked ACL/enrollment checks
only for scratch directories, never for a production service or real target.
The evidence destination MUST be on another drive, outside the test tree.
"""
import argparse
import hashlib
import json
import platform
import re
import ntpath
import os
import subprocess
import sys
from unittest import mock

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _win7_sp1_version():
    """Refuse to label any newer/older runner a Win7 SP1 VM test."""
    if os.name != "nt":
        raise RuntimeError("probe Win7 SP1 requer Windows real")
    version = sys.getwindowsversion()
    if (version.major, version.minor, version.service_pack_major) != (6, 1, 1):
        raise RuntimeError("ambiente NAO e Windows 7 SP1 (6.1 SP1)")
    return {
        "major": version.major, "minor": version.minor,
        "service_pack_major": version.service_pack_major,
        "build": version.build, "platform": platform.machine(),
    }


def _marker_fingerprints(root, store):
    """Read exact scratch ledger bytes by pinned handles; hash each marker.

    No ACL assertions: the scratch fixture deliberately does not implement
    privileged real-store provisioning. Only use in disposable VM probe.
    """
    from nt_commit_checkpoint_experimental import _ledger_prefix
    from win32_relative_directory import open_trusted_root, read_relative_file
    prefix = _ledger_prefix(root)
    expected = (
        (".intent", 524288), (".00000.started", 2048),
    )
    absent = (
        ".00000.done", ".00001.started", ".00001.done", ".complete",
    )
    fingerprint = {}
    with open_trusted_root(store) as pinned:
        for suffix, max_bytes in expected:
            data = read_relative_file(
                pinned, prefix + suffix, max_bytes=max_bytes)
            if not data:
                raise RuntimeError("marcador do checkpoint ausente: " + suffix)
            fingerprint[suffix] = hashlib.sha256(data).hexdigest()
        for suffix in absent:
            try:
                read_relative_file(pinned, prefix + suffix, max_bytes=2048)
            except OSError as exc:
                if getattr(exc, "winerror", None) in (2, 3):
                    continue
                raise
            raise RuntimeError("marcador inesperado depois do crash: " + suffix)
    return fingerprint


def _boot_stamp():
    """Use Windows WMI's actual boot time; fail when it cannot be read."""
    # Formatting a DateTime in PowerShell is locale-dependent (pt-BR,
    # en-US etc.). Convert back to the invariant WMI DMTF representation.
    # Windows 7 PowerShell 2.0 supports both Get-WmiObject and this .NET type.
    statement = (
        "$ErrorActionPreference='Stop';"
        "$os=Get-WmiObject -Class Win32_OperatingSystem;"
        "if ($null -eq $os -or $null -eq $os.LastBootUpTime) "
        "{ throw 'WMI boot time missing' };"
        "[System.Management.ManagementDateTimeConverter]::ToDmtfDateTime("
        "$os.LastBootUpTime)"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         statement],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, timeout=30)
    if result.returncode:
        raise RuntimeError("consulta ao boot WMI falhou: " + result.stderr[:200])
    lines = [v.strip() for v in result.stdout.splitlines() if v.strip()]
    if len(lines) != 1 or re.fullmatch(r"\d{14}\.\d{6}[+-]\d{3}", lines[0]) is None:
        raise RuntimeError("timestamp WMI DMTF de boot ausente ou invalido")
    return lines[0]


def _sha(path):
    with open(path, "rb") as src:
        return hashlib.sha256(src.read()).hexdigest()


def _inspect(root, store):
    import nt_commit_checkpoint_experimental as checkpoint
    # ONLY a scratch probe: no service enrollment or ACL security claim.
    with mock.patch.object(checkpoint, "_assert_protected_acl"):
        return checkpoint.inspect_nt_commit_checkpoint(root, store)


def _check_report(report, root):
    return (report["state"] == "uncertain"
            and report["uncertain_index"] == 0
            and report["completed"] == 0
            and report["total"] == 2
            and os.path.isfile(os.path.join(root, "first.txt"))
            and _sha(os.path.join(root, "first.txt")) ==
            hashlib.sha256(b"FIRST").hexdigest()
            and not os.path.lexists(os.path.join(root, "second.txt")))


def _prepare(base, evidence):
    from test_nt_checkpoint_process_kill import WindowsTerminatedWorkerTests
    if os.path.lexists(base) or os.path.lexists(evidence):
        raise RuntimeError("base/evidencia preexistente; recusa sobrescrita")
    os.mkdir(base)  # parent must already exist; never create unknown ancestors
    root = os.path.join(base, "target")
    overlay = os.path.join(base, "overlay")
    store = os.path.join(base, "store")
    for item in (root, overlay, store):
        os.mkdir(item)
    version = _win7_sp1_version()
    boot = _boot_stamp()
    child = subprocess.Popen(
        [sys.executable, "-u", "-c",
         WindowsTerminatedWorkerTests.WORKER, root, overlay, store],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, cwd=ROOT_DIR)
    try:
        try:
            out, err = child.communicate(timeout=15)
            raise RuntimeError(
                "processo saiu antes do kill: %s %s %s" %
                (child.returncode, out, err[:1000]))
        except subprocess.TimeoutExpired:
            child.kill()
            out, err = child.communicate(timeout=20)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=20)
    if "AFTER_NATIVE_WRITE" not in out or child.returncode == 0:
        raise RuntimeError("kill nao confirmado apos mutacao: " + err[:1000])
    report = _inspect(root, store)
    if not _check_report(report, root):
        raise RuntimeError("nao foi registrado STARTED sem DONE")
    marker_hashes = _marker_fingerprints(root, store)
    artifact = {
        "schema": 2, "boot_before": boot, "base": base,
        "windows_version": version, "marker_sha256": marker_hashes,
        "checkpoint": report, "child_exit_code": child.returncode,
        "first_sha256": _sha(os.path.join(root, "first.txt")),
        "second_absent": True,
        "scope": "VM scratch only; native ACL/enrollment mocked",
    }
    with open(evidence, "x", encoding="utf-8") as dst:
        json.dump(artifact, dst, sort_keys=True, indent=2)
        dst.flush()
        os.fsync(dst.fileno())
    return artifact


def _verify(base, evidence):
    with open(evidence, "r", encoding="utf-8") as src:
        before = json.load(src)
    if before.get("schema") != 2 or before.get("base") != base:
        raise RuntimeError("base nao corresponde a evidencia anterior")
    current_version = _win7_sp1_version()
    if before.get("windows_version") != current_version:
        raise RuntimeError("build/arquitetura Windows mudaram entre as fases")
    now = _boot_stamp()
    if before["boot_before"] == now:
        raise RuntimeError("SEM REBOOT: boot WMI nao mudou, jamais afirmar PASS")
    root = os.path.join(base, "target")
    store = os.path.join(base, "store")
    report = _inspect(root, store)
    if not _check_report(report, root):
        raise RuntimeError("checkpoint ou sentinelas divergiram apos reboot")
    if report["intent_sha256"] != before["checkpoint"]["intent_sha256"]:
        raise RuntimeError("identidade da intencao mudou no reboot")
    if report != before["checkpoint"]:
        raise RuntimeError("estado completo dos marcadores mudou no reboot")
    if _marker_fingerprints(root, store) != before.get("marker_sha256"):
        raise RuntimeError("bytes dos marcadores NT mudaram depois do reboot")
    return {
        "result": "PASS_SCRATCH_CHECKPOINT_POST_REBOOT",
        "boot_before": before["boot_before"],
        "boot_after": now,
        "checkpoint": report,
        "marker_sha256": before["marker_sha256"],
        "windows_version": current_version,
        "scope": "VM scratch only; no production ACL/enrollment/recovery proof",
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--verify-after-reboot", action="store_true")
    parser.add_argument("--base", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--confirm-disposable-vm", action="store_true")
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("somente Windows")
    if not args.confirm_disposable_vm:
        parser.error("exige --confirm-disposable-vm")
    from nt_enrollment_experimental import _canonical_root
    # Reject modern runners before touching the VM scratch directories.
    _win7_sp1_version()
    base = os.path.normpath(args.base)
    evidence = os.path.normpath(args.evidence)
    if base != args.base or evidence != args.evidence:
        parser.error("caminhos canonicos obrigatorios")
    _canonical_root(base)
    if not os.path.isabs(evidence) or ntpath.splitdrive(base)[0].lower() == ntpath.splitdrive(evidence)[0].lower():
        parser.error("evidencia deve ser gravada em outro volume persistente")
    if not evidence.lower().endswith(".json"):
        parser.error("arquivo de evidencia JSON obrigatorio")
    try:
        result = (_prepare(base, evidence) if args.prepare
                  else _verify(base, evidence))
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}),
              file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

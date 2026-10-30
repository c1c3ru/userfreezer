#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two-phase Linux VM reboot evidence for directory-scoped OverlayFS (#49).

NO reboot, mount, unmount, enable, disable, install or disk operation.
This probe only writes a disposable marker through the *OS filesystem*,
never through the UserFreezer API, and one immutable evidence JSON.
It requires a separate mounted persistent evidence volume. A successful
observation never proves rootfs protection or pre-service boot ordering.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid

TEST_ROOT = "/srv/deepfreezer-vm-test"
BASELINE = "baseline.txt"
EVIDENCE_SCHEMA = 1
MAX_EVIDENCE = 16384
_UUID = re.compile(r"[0-9a-f]{32}\Z")


def _boot_id():
    with open("/proc/sys/kernel/random/boot_id", "r", encoding="ascii") as file:
        value = file.read(100).strip()
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise RuntimeError("boot_id Linux invalido ou indisponivel") from exc


def _findmnt(target, option):
    result = subprocess.run(
        ["findmnt", "--kernel", "--noheadings", "--raw",
         "--output", option,
         "--mountpoint" if target == TEST_ROOT else "--target", target],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError("findmnt falhou para %s: %s" %
                           (target, result.stderr[:200]))
    lines = result.stdout.strip().splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise RuntimeError("saida findmnt invalida")
    return lines[0].strip()


def _require_root_owned_directory(path):
    # Inspect each ancestor by lstat; never follow symlinks intentionally.
    path = os.path.normpath(path)
    current = "/"
    for part in path.strip("/").split("/"):
        current = os.path.join(current, part)
        info = os.lstat(current)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or
                info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise PermissionError("ancestral da VM nao e diretorio root protegido")
    return path


def _check_environment(target, evidence):
    if os.name != "posix" or not sys.platform.startswith("linux"):
        raise RuntimeError("ensaio requer Linux")
    if os.geteuid() != 0:
        raise PermissionError("ensaio requer root na VM descartavel")
    if target != TEST_ROOT:
        raise ValueError("probe nao aceita alvo fora de %s" % TEST_ROOT)
    _require_root_owned_directory(target)
    if not isinstance(evidence, str) or not os.path.isabs(evidence):
        raise ValueError("evidencia precisa de caminho absoluto")
    evidence = os.path.normpath(evidence)
    if not evidence.endswith(".json") or os.path.islink(evidence):
        raise ValueError("arquivo JSON/symlink de evidencia invalido")
    parent = os.path.dirname(evidence)
    _require_root_owned_directory(parent)
    if (os.path.commonpath([target, evidence]) == target or
            os.path.commonpath([evidence, target]) == evidence):
        raise ValueError("evidencia nao pode ficar no alvo")
    if _findmnt(target, "FSTYPE") != "overlay":
        raise RuntimeError("alvo nao esta sob mount OverlayFS real")
    evidence_mount = _findmnt(parent, "TARGET")
    if evidence_mount in ("/", target):
        raise RuntimeError("evidencia deve estar em volume persistente separado")
    if _findmnt(parent, "FSTYPE") in (
            "overlay", "tmpfs", "ramfs", "proc", "sysfs"):
        raise RuntimeError("filesystem das evidencias nao e persistente")
    return evidence


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _json_file(path):
    with open(path, "rb") as stream:
        raw = stream.read(MAX_EVIDENCE + 1)
    if not raw or len(raw) > MAX_EVIDENCE:
        raise ValueError("evidencia ausente ou extensa")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("chave duplicada no registro")
            result[key] = value
        return result
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("JSON de evidencias invalido") from exc
    if not isinstance(obj, dict):
        raise ValueError("registro de evidencias invalido")
    return obj


def prepare(target, evidence):
    evidence = _check_environment(target, evidence)
    if os.path.lexists(evidence):
        raise RuntimeError("evidencia preexistente; nao sobrescrever")
    baseline = os.path.join(target, BASELINE)
    if not os.path.isfile(baseline) or os.path.islink(baseline):
        raise RuntimeError("baseline.txt deve existir na base antes do filtro")
    baseline_hash = _hash_file(baseline)
    boot = _boot_id()
    marker = "df-external-%s.txt" % uuid.uuid4().hex
    marker_path = os.path.join(target, marker)
    # A write via the ordinary filesystem is external to UserFreezer API.
    with open(marker_path, "xb") as output:
        output.write(b"USERFREEZER-EXTERNAL-VM-WRITE\n")
        output.flush()
        os.fsync(output.fileno())
    item = {
        "schema": EVIDENCE_SCHEMA, "target": target,
        "baseline_sha256": baseline_hash, "boot_before": boot,
        "marker": marker, "marker_sha256": _hash_file(marker_path),
        "test_scope": "directory-only-overlayfs-VM",
        "observation": "overlay-mounted-before-reboot",
    }
    with open(evidence, "x", encoding="utf-8") as out:
        json.dump(item, out, sort_keys=True, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    return item


def verify_after_reboot(target, evidence):
    evidence = _check_environment(target, evidence)
    report = _json_file(evidence)
    required = {"schema", "target", "baseline_sha256", "boot_before",
                "marker", "marker_sha256", "test_scope", "observation"}
    if set(report) != required or type(report["schema"]) is not int or report["schema"] != EVIDENCE_SCHEMA:
        raise ValueError("schema do registro VM divergente")
    if report["target"] != target or report["test_scope"] != "directory-only-overlayfs-VM":
        raise ValueError("registro aponta para outro alvo de teste")
    if report["observation"] != "overlay-mounted-before-reboot":
        raise ValueError("observacao da preparacao invalida")
    marker = report["marker"]
    if (not isinstance(marker, str) or not marker.startswith("df-external-") or
            not marker.endswith(".txt") or
            _UUID.fullmatch(marker[len("df-external-"):-len(".txt")]) is None):
        raise ValueError("nome da sentinela invalido")
    for key in ("marker_sha256", "baseline_sha256"):
        value = report[key]
        if (not isinstance(value, str) or
                re.fullmatch(r"[0-9a-f]{64}", value) is None):
            raise ValueError("SHA-256 invalido")
    if report["marker_sha256"] != hashlib.sha256(
            b"USERFREEZER-EXTERNAL-VM-WRITE\n").hexdigest():
        raise ValueError("sentinela original nao pertence ao probe")
    before = report["boot_before"]
    now = _boot_id()
    if not isinstance(before, str) or str(uuid.UUID(before)) != before:
        raise ValueError("boot anterior invalido")
    if now == before:
        raise RuntimeError("SEM REBOOT: boot_id nao mudou")
    baseline = os.path.join(target, BASELINE)
    if not os.path.isfile(baseline) or os.path.islink(baseline):
        raise RuntimeError("baseline nao existe no novo boot")
    if _hash_file(baseline) != report["baseline_sha256"]:
        raise RuntimeError("baseline difere apos reboot")
    if os.path.lexists(os.path.join(target, marker)):
        raise RuntimeError("escrita externa NAO foi descartada no reboot")
    return {
        "result": "OBSERVED_LINUX_DIRECTORY_ROLLBACK_AFTER_REBOOT",
        "boot_before": before, "boot_after": now,
        "target": target, "baseline_sha256": report["baseline_sha256"],
        "record_sha256": _hash_file(evidence),
        "independent_vm_attestation": False,
        "rootfs_protection_verified": False,
        "boot_ordering_verified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--verify-after-reboot", action="store_true")
    parser.add_argument("--target", default=TEST_ROOT)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--confirm-disposable-vm", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_disposable_vm:
        parser.error("exige --confirm-disposable-vm")
    try:
        result = (prepare(args.target, args.evidence)
                  if args.prepare else verify_after_reboot(
                      args.target, args.evidence))
    except (OSError, ValueError, RuntimeError, PermissionError) as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

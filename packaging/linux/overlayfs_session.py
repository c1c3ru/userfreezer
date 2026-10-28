#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OS-level opcional por diretório no Linux: mount OverlayFS + upper tmpfs.

Intercepta escritas de QUALQUER processo no diretório montado; o lower
permanece sem mudança e upper fica em RAM e some no reboot.
Nao congela a raiz / nem torna particoes de boot imutaveis.
ATIVAR SOMENTE em VM e com confirmacao explicita.
Python 3.8+, stdlib, subprocess sem shell.
"""
import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys

VOLATILE_ROOT = "/run/deepfreezer-overlayfs"
ALLOWED_ROOTS = ("/srv", "/opt", "/mnt", "/media", "/tmp")
BLOCKED_PREFIXES = ("/opt/deepfreezer", "/opt/deepfreezer-overlayfs")


class OSLevelError(RuntimeError):
    pass


def _safe_absolute(path):
    if not isinstance(path, str) or not path or not os.path.isabs(path):
        raise OSLevelError("path absoluto obrigatorio")
    if any(c in path for c in ",:\r\n\x00"):
        raise OSLevelError("path contem separador perigoso de mount options")
    clean = os.path.normpath(path)
    if path != clean:
        raise OSLevelError("use path canonico sem . ou ..")
    prefix_ok = any(clean.startswith(p + "/") for p in ALLOWED_ROOTS)
    if not prefix_ok or any(
            clean == p or clean.startswith(p + "/") for p in BLOCKED_PREFIXES):
        raise OSLevelError("diretorio fora das areas de teste permitidas")
    current = "/"
    for part in clean.strip("/").split("/"):
        current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            raise OSLevelError("diretorio inexistente: %s" % current)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise OSLevelError("caminho nao e diretorio real: %s" % current)
    if os.path.ismount(clean):
        raise OSLevelError("alvo ja e ponto de montagem; verificar estado antes")
    return clean


def _volatile_path(target):
    token = hashlib.sha256(target.encode("utf-8")).hexdigest()[:20]
    return os.path.join(VOLATILE_ROOT, token)


def protection_status(target):
    # findmnt informa o tipo de filesystem real; nao inferir de manifest.
    proc = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "--mountpoint", target],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, check=False)
    fstype = proc.stdout.strip() if proc.returncode == 0 else None
    if fstype == "overlay":
        return "active"
    if fstype:
        return "unsupported"
    # A mera existencia de um diretorio NAO prova configuracao nem
    # montagem do OverlayFS. Nao mostrar "configured" para um alvo
    # comum, pois isso criaria uma falsa evidencia de protecao.
    return "inactive" if os.path.isdir(target) else "error"


def _mount(command):
    subprocess.run(command, check=True, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, universal_newlines=True)


def activate(target, size_mb=256, dry_run=False, accepted=False):
    target = _safe_absolute(target)
    if not isinstance(size_mb, int) or size_mb < 16 or size_mb > 4096:
        raise OSLevelError("limite tmpfs permitido: 16..4096 MiB")
    if not dry_run:
        if not accepted:
            raise OSLevelError("exige --i-accept-volatile-protection")
        if os.geteuid() != 0:
            raise OSLevelError("montagem do kernel exige root")
    staging = _volatile_path(target)
    upper, work = os.path.join(staging, "upper"), os.path.join(staging, "work")
    tmpfs = ["mount", "-t", "tmpfs", "-o", "size=%dm,mode=0700" % size_mb,
             "tmpfs", staging]
    overlay = ["mount", "-t", "overlay", "-o",
               "lowerdir=%s,upperdir=%s,workdir=%s" % (target, upper, work),
               "overlay", target]
    if dry_run:
        return {"target": target, "volatile_root": staging, "scope": "os-level-directory",
                "commands": [tmpfs, overlay], "state": "pending-activation"}
    os.makedirs(VOLATILE_ROOT, mode=0o700, exist_ok=True)
    os.chmod(VOLATILE_ROOT, 0o700)
    if os.path.lexists(staging):
        raise OSLevelError("diretorio volatile ja existe; nao reutilizar: %s" % staging)
    os.mkdir(staging, 0o700)
    mounted_tmpfs = False
    try:
        _mount(tmpfs)
        mounted_tmpfs = True
        os.mkdir(upper, 0o700)
        os.mkdir(work, 0o700)
        _mount(overlay)
    except (OSError, subprocess.CalledProcessError) as exc:
        if mounted_tmpfs:
            # Falhar fechado: diagnostico de cleanup tambem deve aparecer.
            try:
                _mount(["umount", staging])
            except (OSError, subprocess.CalledProcessError) as cleanup:
                raise OSLevelError("overlay falhou: %s; cleanup tambem falhou: %s" %
                                   (exc, cleanup)) from exc
        os.rmdir(staging)
        raise OSLevelError("nao foi possivel montar overlay: %s" % exc) from exc
    if protection_status(target) != "active":
        raise OSLevelError("mount retornou sucesso mas OverlayFS nao esta ativo")
    return {"target": target, "volatile_root": staging,
            "scope": "os-level-directory", "state": "active"}


def reject_api_target_overlap(target, config_path):
    """Falha fechada para alvos application-level iguais/aninhados."""
    if not config_path:
        return
    if not os.path.isabs(config_path):
        raise OSLevelError("guard-config deve ser absoluto")
    try:
        with open(config_path, "r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        raise OSLevelError("config API nao validavel: %s" % exc)
    if not isinstance(config, dict) or not isinstance(config.get("targets"), list):
        raise OSLevelError("config API invalida")
    for entry in config["targets"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("target"), str):
            raise OSLevelError("config API tem alvo invalido")
        configured = os.path.normpath(entry["target"])
        if not os.path.isabs(configured):
            raise OSLevelError("config API contem caminho relativo")
        try:
            common = os.path.commonpath((target, configured))
        except ValueError:
            continue
        if common in (target, configured):
            raise OSLevelError("OS-level conflita com API: %s" % configured)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="OverlayFS OS-level POR DIRETORIO (somente Linux, VM primeiro)")
    p.add_argument("--target", required=True)
    p.add_argument("--status", action="store_true")
    p.add_argument("--enable", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--size-mb", type=int, default=256)
    p.add_argument("--guard-config", help="recusa sobreposicao com config API")
    p.add_argument("--i-accept-volatile-protection", action="store_true")
    args = p.parse_args(argv)
    try:
        if not args.status and not args.enable:
            p.error("escolha --status ou --enable")
        if args.status:
            result = {"target": args.target, "state": protection_status(args.target),
                      "scope": "os-level-directory"}
        else:
            if args.guard_config:
                safe_target = _safe_absolute(args.target)
                reject_api_target_overlap(safe_target, args.guard_config)
            result = activate(args.target, args.size_mb, args.dry_run,
                              args.i_accept_volatile_protection)
        print(json.dumps(result, indent=2))
        return 0
    except OSLevelError as exc:
        sys.stderr.write("Falha de protecao OS-level: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

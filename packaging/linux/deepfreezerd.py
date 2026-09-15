#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deepfreezerd — enforcement de boot do DeepFreezer (Linux/systemd).

Roda como servico systemd (User=root), uma vez por boot. Para cada
alvo do config: descarta o overlay da sessao anterior (thaw sem
commit) e recongela a arvore, iniciando um novo ciclo "Deep Freeze";
em seguida restringe as permissoes do overlay a root.

Uso: deepfreezerd.py [--config /etc/deepfreezer/config.json] [-v]

Config (JSON), ver packaging/config.example.json:
{"targets": [{"target": "/opt/lab-app", "overlay": null, "verify": false}]}
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deepfreezer import DeepFreezer, DeepFreezeError  # noqa: E402


def _harden_overlay(path, log):
    """chmod 700 (arquivos: 600) + chown root:root recursivo no overlay."""
    if os.geteuid() != 0:
        log.warning("nao sou root; pulando hardening de permissoes em %s", path)
        return
    try:
        os.chown(path, 0, 0)
        os.chmod(path, 0o700)
        for dirpath, dirnames, filenames in os.walk(path):
            for d in dirnames:
                p = os.path.join(dirpath, d)
                os.chown(p, 0, 0)
                os.chmod(p, 0o700)
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                os.chown(p, 0, 0)
                os.chmod(p, 0o600)
    except OSError as e:
        log.warning("hardening parcial em %s: %s", path, e)


def enforce_all(config_path, log):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        log.error("erro lendo config %s: %s", config_path, e)
        return False
    targets = cfg.get("targets", [])
    if not targets:
        log.error("config sem 'targets': %s", config_path)
        return False

    ok = True
    for entry in targets:
        target = entry.get("target")
        try:
            df = DeepFreezer(target, overlay=entry.get("overlay"),
                              verify=bool(entry.get("verify", False)))
        except DeepFreezeError as e:
            log.error("%s: %s", target, e)
            ok = False
            continue
        try:
            if df.frozen:
                log.info("%s: overlay de sessao anterior encontrado, descartando", target)
                df.thaw(commit=False)
            r = df.freeze()
            log.info("%s: congelado (%d caminhos, %.3fs, overlay=%s)",
                      target, r["paths"], r["seconds"], df.overlay)
            _harden_overlay(df.overlay, log)
        except DeepFreezeError as e:
            log.error("%s: %s", target, e)
            ok = False
        finally:
            df.close()
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(prog="deepfreezerd")
    ap.add_argument("--config", default="/etc/deepfreezer/config.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="deepfreezerd[%(process)d] %(levelname)s: %(message)s")
    log = logging.getLogger("deepfreezerd")

    ok = enforce_all(a.config, log)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

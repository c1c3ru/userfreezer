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
from enforcement_health import publish_health  # noqa: E402


def _harden_overlay(path, log):
    """chmod 700 (arquivos: 600) + chown root:root recursivo no overlay."""
    if os.geteuid() != 0:
        log.error("hardening exige root em %s", path)
        return False
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
        log.error("hardening falhou em %s: %s", path, e)
        return False
    return True


DEFAULT_STATUS_PATH = "/var/lib/deepfreezer/status.json"


def _record_health(results, log, config_error=None):
    path = os.environ.get("DEEPFREEZER_STATUS", DEFAULT_STATUS_PATH)
    try:
        report = publish_health(path, results, config_error)
        log.info("enforcement=%s (%d/%d); somente application-level",
                 report["state"], report["successful_targets"],
                 report["total_targets"])
        return report["state"] == "healthy"
    except (OSError, ValueError) as exc:
        log.error("nao foi possivel publicar status seguro %s: %s", path, exc)
        return False


def enforce_all(config_path, log):
    results = []
    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict) or not isinstance(cfg.get("targets"), list):
            raise ValueError("config deve conter lista targets")
        if not cfg["targets"]:
            raise ValueError("config sem targets")
    except (OSError, ValueError, TypeError) as exc:
        msg = "erro lendo config %s: %s" % (config_path, exc)
        log.error(msg)
        _record_health([], log, config_error=msg)
        return False
    for entry in cfg["targets"]:
        if not isinstance(entry, dict):
            results.append({"target": "<invalido>", "state": "error",
                            "error": "entrada nao e objeto JSON"})
            continue
        target = entry.get("target")
        if not isinstance(target, str) or not target:
            results.append({"target": "<invalido>", "state": "error",
                            "error": "target invalido"})
            continue
        df = None
        try:
            df = DeepFreezer(target, overlay=entry.get("overlay"),
                             verify=bool(entry.get("verify", False)))
            if df.frozen:
                log.info("%s: descartando overlay anterior", target)
                df.thaw(commit=False)
            r = df.freeze()
            if not _harden_overlay(df.overlay, log):
                raise DeepFreezeError("hardening do overlay falhou")
            results.append({"target": target, "state": "healthy",
                            "overlay": df.overlay, "baseline_paths": r["paths"],
                            "protection_scope": "application-level"})
            log.info("%s: congelado (%d caminhos, %.3fs)",
                     target, r["paths"], r["seconds"])
        except Exception as exc:
            log.error("%s: enforcement falhou: %s", target, exc)
            results.append({"target": target, "state": "error",
                            "error": str(exc),
                            "protection_scope": "application-level"})
        finally:
            if df is not None:
                df.close()
    return _record_health(results, log)


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

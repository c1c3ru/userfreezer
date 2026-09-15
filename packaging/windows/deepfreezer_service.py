#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servico Windows do DeepFreezer -- dois modos de uso:

1) Servico nativo via pywin32 (requer 'pip install pywin32'):
     python deepfreezer_service.py install
     python deepfreezer_service.py start
   (ver install_service_pywin32.ps1)

2) Processo simples envolvido pelo NSSM -- nao depende de pywin32,
   funciona tambem a partir do .exe gerado por PyInstaller:
     nssm install DeepFreezer python.exe "deepfreezer_service.py --foreground"
   (ver install_service_nssm.ps1)

Em ambos os modos, no start: para cada alvo do config descarta o
overlay da sessao anterior (thaw sem commit) e recongela; em seguida
restringe a ACL do overlay a Administradores/SYSTEM via icacls.

Config: mesmo formato JSON do Linux (ver packaging/config.example.json),
por padrao em C:\\ProgramData\\DeepFreezer\\config.json (sobreponivel
pela variavel de ambiente DEEPFREEZER_CONFIG).
"""
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deepfreezer import DeepFreezer, DeepFreezeError  # noqa: E402

try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
    _HAVE_PYWIN32 = True
except ImportError:
    _HAVE_PYWIN32 = False

CONFIG_PATH = os.environ.get(
    "DEEPFREEZER_CONFIG", r"C:\ProgramData\DeepFreezer\config.json")
LOG_DIR = r"C:\ProgramData\DeepFreezer"


def _setup_logging():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        pass
    log = logging.getLogger("deepfreezerd")
    log.setLevel(logging.INFO)
    if not log.handlers:
        try:
            handler = logging.handlers.RotatingFileHandler(
                os.path.join(LOG_DIR, "deepfreezer.log"),
                maxBytes=1 << 20, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s deepfreezerd %(levelname)s: %(message)s"))
            log.addHandler(handler)
        except OSError:
            log.addHandler(logging.StreamHandler())
    return log


def _harden_overlay(path, log):
    """Restringe a ACL do overlay a Administradores (S-1-5-32-544) e
    SYSTEM (S-1-5-18), removendo a heranca (inclui o acesso padrao do
    grupo Usuarios)."""
    try:
        subprocess.run(
            ["icacls", path, "/inheritance:r",
             "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
             "/grant:r", "*S-1-5-18:(OI)(CI)F"],
            check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        log.warning("hardening de ACL parcial em %s: %s", path, e)


def enforce_all(log):
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        log.error("erro lendo config %s: %s", CONFIG_PATH, e)
        return False
    targets = cfg.get("targets", [])
    if not targets:
        log.error("config sem 'targets': %s", CONFIG_PATH)
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


def run_foreground():
    """Modo NSSM: roda o enforcement uma vez e fica residente ate o
    NSSM encerrar o processo (nssm stop / servico parado)."""
    log = _setup_logging()
    enforce_all(log)
    while True:
        time.sleep(3600)


if _HAVE_PYWIN32:
    class DeepFreezerService(win32serviceutil.ServiceFramework):
        _svc_name_ = "DeepFreezer"
        _svc_display_name_ = "DeepFreezer"
        _svc_description_ = ("Retem o estado congelado das arvores de "
                              "diretorio configuradas; mudancas caem em "
                              "overlay e sao descartadas no proximo boot.")

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.log = _setup_logging()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""))
            enforce_all(self.log)
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)


def main():
    if not _HAVE_PYWIN32:
        if "--foreground" not in sys.argv:
            sys.stderr.write(
                "aviso: pywin32 nao encontrado; rodando em modo --foreground (NSSM)\n")
        return run_foreground()
    if "--foreground" in sys.argv:
        return run_foreground()
    win32serviceutil.HandleCommandLine(DeepFreezerService)


if __name__ == "__main__":
    sys.exit(main())

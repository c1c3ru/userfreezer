#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Elevação por política do SO, SEM senha na UI e sem script editável elevado.

Linux: pkexec chama somente /opt/deepfreezer/admin_client.py, root-owned.
Windows: ShellExecuteEx('runas') chama EXE instalado em Program Files.
O SERVIÇO revalida token + alvo + nonce: a UI nunca é autoridade.
"""
import os
import shutil
import stat
import subprocess
import sys

LINUX_CLIENT = "/opt/deepfreezer/admin_client.py"
WINDOWS_EXE = r"C:\Program Files\DeepFreezer\deepfreezer_service.exe"
OPS = ("freeze", "discard", "commit")


def trusted_linux_client(path=LINUX_CLIENT):
    if os.path.abspath(path) != LINUX_CLIENT:
        return False
    for part in ("/opt", "/opt/deepfreezer", LINUX_CLIENT):
        try:
            st = os.lstat(part)
        except OSError:
            return False
        if st.st_uid != 0 or st.st_mode & 0o022 or stat.S_ISLNK(st.st_mode):
            return False
    return stat.S_ISREG(os.lstat(LINUX_CLIENT).st_mode)


def _client_args(operation, target):
    if operation not in OPS:
        raise ValueError("operacao nao autorizada para elevacao")
    if not isinstance(target, str) or not os.path.isabs(target):
        raise ValueError("alvo absoluto obrigatorio")
    action = ("approve-" + operation) if operation in ("commit", "discard") else "freeze"
    return [action, "--target", target]


def run_admin_action(operation, target, socket_path=None):
    """Retorna sucesso; falhas sao propagadas sem declarar rollback."""
    args = _client_args(operation, target)
    if os.name == "nt":
        return _runas_win(args)
    if not trusted_linux_client():
        raise PermissionError("Cliente privilegiado nao instalado em /opt/deepfreezer "
                              "ou permissoes root inseguras")
    if socket_path:
        args += ["--socket", socket_path]
    if os.geteuid() == 0:
        command = ["/usr/bin/python3", LINUX_CLIENT] + args
    else:
        pkexec = shutil.which("pkexec")
        if not pkexec:
            raise PermissionError("pkexec/polkit indisponivel para elevar privilegios")
        command = [pkexec, "/usr/bin/python3", LINUX_CLIENT] + args
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=180, universal_newlines=True)
    if proc.returncode:
        raise PermissionError("Servico recusou a operacao administrativa "
                              "(codigo %d). %s" %
                              (proc.returncode, (proc.stderr or proc.stdout)[-500:]))
    return True


def _runas_win(args):
    if not os.path.isfile(WINDOWS_EXE):
        raise PermissionError("Instale antes o EXE do servico em Program Files")
    # Dependencias do cliente Tk/pywin32 nao sao parte do core.
    import win32api
    import win32con
    import win32event
    import win32process
    from win32com.shell import shell, shellcon

    params = subprocess.list2cmdline(["--admin-cli"] + args)
    result = shell.ShellExecuteEx(
        fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
        lpVerb="runas",
        lpFile=WINDOWS_EXE,
        lpParameters=params,
        lpDirectory=os.path.dirname(WINDOWS_EXE),
        nShow=win32con.SW_SHOWNORMAL)
    process = result["hProcess"]
    try:
        wait = win32event.WaitForSingleObject(process, 180000)
        if wait != win32event.WAIT_OBJECT_0:
            raise RuntimeError("Timeout na elevacao: resultado indeterminado; "
                               "consulte o status e os logs do servico")
        code = win32process.GetExitCodeProcess(process)
        if code:
            raise PermissionError("Servico recusou a operacao administrativa "
                                  "(codigo %d); consulte o log de enforcement" % code)
        return True
    finally:
        win32api.CloseHandle(process)

def run_admin_uwf_stage(persistent_volume):
    """UAC to installed trusted EXE; broker still validates SID+nonce+OS."""
    from uwf_ipc_lab import _validate_volumes
    _validate_volumes("C:", persistent_volume)
    if os.name != "nt":
        raise PermissionError("UWF disponivel somente em Windows")
    return _runas_win([
        "approve-uwf-stage", "--target", "C:",
        "--persistent-volume", persistent_volume,
        "--acknowledge-vm-snapshot",
        "--acknowledge-discard-writes",
    ])

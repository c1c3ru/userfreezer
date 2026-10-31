#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local Windows UWF inspection and VM-LAB-only staging behind service IPC.

No client can select executables, invoke shell, pass code or set a target
other than C:. UWF is never configured by import, by installation, by
opening the GUI or by read-only calls. The service default is disabled.
Use only on a disposable, snapshotted Windows 10/11 UWF-capable VM.
"""
import ctypes
import os
import subprocess

ALLOWED_PERSISTENT = frozenset("%s:" % chr(c) for c in range(68, 91))
SUPPORTED_EDITION = frozenset((
    "Enterprise", "EnterpriseN", "EnterpriseS", "EnterpriseSN",
    "Education", "EducationN", "IoTEnterprise", "IoTEnterpriseS",
    "IoTEnterpriseK", "IoTEnterpriseSK",
))


def _validate_volumes(target, persistent):
    if target != "C:" or persistent not in ALLOWED_PERSISTENT:
        raise ValueError("UWF em laboratorio aceita C: e D:..Z: distintos")
    return target, persistent


def _preconditions(target, persistent):
    _validate_volumes(target, persistent)
    if os.name != "nt":
        raise RuntimeError("UWF exige Windows real")
    from packaging.windows import os_detect
    info = os_detect.get_os_info()
    if (info["build"] < 10240 or info["edition"] not in SUPPORTED_EDITION or
            os_detect.classify(info["build"], info["edition"])["strategy"] != "uwf"):
        raise RuntimeError("Windows/edicao nao oferece UWF nativo validavel")
    if os.environ.get("SystemDrive", "").upper() != "C:":
        raise RuntimeError("Windows nao inicializado de C:")
    drive_type = ctypes.windll.kernel32.GetDriveTypeW(persistent + "\\")
    if drive_type != 3:  # DRIVE_FIXED, not mapped/removable/network.
        raise RuntimeError("volume persistente precisa ser disco local fixo")
    return info


def _provider_snapshot(target, persistent):
    """Read current/next sessions from the real WMI provider.

    This is an observation, NEVER proof of rollback after reboot. Service
    thread initializes COM independently and always releases it.
    """
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        provider = win32com.client.GetObject(
            r"winmgmts:\\.\root\standardcimv2\embedded")
        filters = list(provider.ExecQuery("SELECT * FROM UWF_Filter"))
        volumes = list(provider.ExecQuery("SELECT * FROM UWF_Volume"))
        if len(filters) != 1:
            raise RuntimeError("provedor UWF_Filter ausente ou ambiguo")
        f = filters[0]
        def rows(drive, current):
            return [v for v in volumes
                    if str(v.DriveLetter or "").upper() == drive and
                    bool(v.CurrentSession) is current]
        c_now, c_next = rows(target, True), rows(target, False)
        d_rows = [v for v in volumes
                  if str(v.DriveLetter or "").upper() == persistent]
        if len(c_now) > 1 or len(c_next) > 1 or len(d_rows) > 2:
            raise RuntimeError("entradas UWF duplicadas")
        if any(bool(v.Protected) for v in d_rows):
            raise RuntimeError("volume persistente ja protegido pelo UWF")
        return {
            "current_filter_enabled": bool(f.CurrentEnabled),
            "next_filter_enabled": bool(f.NextEnabled),
            "current_c_protected": bool(c_now and c_now[0].Protected),
            "next_c_protected": bool(c_next and c_next[0].Protected),
            "persistent_volume_unprotected": True,
        }
    finally:
        pythoncom.CoUninitialize()


def inspect_uwf(target="C:", persistent="D:"):
    _preconditions(target, persistent)
    state = _provider_snapshot(target, persistent)
    current = state["current_filter_enabled"] and state["current_c_protected"]
    next_state = state["next_filter_enabled"] and state["next_c_protected"]
    if current:
        status = "native_filter_currently_enabled"
    elif next_state:
        status = "configured_for_next_boot_not_yet_verified"
    else:
        status = "not_protected"
    return dict(state, status=status, scope="os-level-volume",
                system_volume="C:", persistent_volume=persistent,
                external_write_rollback_verified=False,
                vm_reboot_verified=False)


def _uwfmgr_path():
    if os.name != "nt":
        raise RuntimeError("executavel UWF nativo requer Windows")
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if length <= 0 or length >= len(buffer):
        raise RuntimeError("diretorio System32 nao identificado")
    path = os.path.join(buffer.value, "uwfmgr.exe")
    if not os.path.isfile(path):
        raise RuntimeError("componente uwfmgr.exe nao instalado")
    return path


def _native_call(executable, verb, option, volume=None):
    cmd = [executable, verb, option]
    if volume is not None:
        _validate_volumes(volume, "D:")
        cmd.append(volume)
    done = subprocess.run(cmd, shell=False, timeout=45,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode:
        raise RuntimeError("uwfmgr %s %s falhou com codigo %d; "
                           "estado potencialmente parcial" %
                           (verb, option, done.returncode))


def stage_uwf_lab(target, persistent, *, enabled=False):
    """Elevated broker-only: stage next boot, never reboot or report PASS.

    A failed native command may leave persistent next-session settings.
    We intentionally DO NOT issue a blind 'disable/unprotect' rollback.
    """
    _validate_volumes(target, persistent)
    if enabled is not True:
        raise PermissionError("provisionamento de laboratorio desabilitado")
    before = inspect_uwf(target, persistent)
    if (before["current_filter_enabled"] or before["next_filter_enabled"] or
            before["current_c_protected"] or before["next_c_protected"]):
        raise RuntimeError("UWF existente; operacao recusada para evitar alteracao")
    binary = _uwfmgr_path()
    _native_call(binary, "volume", "protect", target)
    _native_call(binary, "filter", "enable")
    after = inspect_uwf(target, persistent)
    if not (after["next_filter_enabled"] and after["next_c_protected"]):
        raise RuntimeError("UWF pendente nao confirmado pelo WMI; "
                           "nao reiniciar ate inspecao administrativa")
    return {
        "status": "configured_for_next_boot_not_yet_verified",
        "system_volume": target, "persistent_volume": persistent,
        "reboot_required": True, "reboot_performed": False,
        "external_write_rollback_verified": False,
    }

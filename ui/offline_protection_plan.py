#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline protection configuration *proposal*, never active OS protection.

Uses volume C: as the suggested Windows scope; requires an explicit external
persistent volume such as D: and informed administrative approval. The plan
is intentionally NOT read by the privileged service: it cannot enable a
kernel filter, rewrite boot state or authorize a write operation.
Python 3.8+, standard library only (including Windows 7).
"""
import json
import ntpath
import os
import re

_MODE = frozenset(("windows", "profile", "folder"))
_VOLUMEDRIVE = re.compile(r"^[A-Za-z]:$")
_MAX_JSON = 4096


def _volume(value):
    if not isinstance(value, str) or not _VOLUMEDRIVE.fullmatch(value):
        raise ValueError("volume deve ser somente uma letra, por exemplo D:")
    return value.upper()


def make_protection_plan(mode, *, system_drive="C:", persistent_drive=None,
                         folder=None, admin_consent=False, backup_confirmed=False,
                         capability=None):
    """Validate and return a data-only, *inactive* scope proposal.

    Never accepts a folder on protected C: as a 'permanent data area'.
    Protecting an entire volume is NOT the same as user-profile selection.
    """
    if mode not in _MODE:
        raise ValueError("modo de protecao desconhecido")
    if type(admin_consent) is not bool or type(backup_confirmed) is not bool:
        raise ValueError("confirmacoes precisam ser booleanas")
    if not admin_consent or not backup_confirmed:
        raise PermissionError(
            "autorizacao explicita e copia de seguranca obrigatorias")
    system_drive = _volume(system_drive)
    if system_drive != "C:":
        raise ValueError("instalador v0.2 protege C: somente; outro sistema requer revisao")
    if not isinstance(capability, dict):
        raise ValueError("deteccao do Windows nao confirmada")
    strategy = capability.get("strategy")
    if strategy not in ("uwf", "ewf_fbwf", "vhdx_diff", "unsupported"):
        raise ValueError("estrategia de SO nao reconhecida")
    proposal = {
        "schema": "userfreezer-protection-proposal-v1",
        "mode": mode,
        "proposed_system_volume": system_drive,
        "detected_backend": strategy,
        "offline": True,
        "admin_consent_for_proposal": True,
        "backup_acknowledged": True,
        "activation_state": "NOT_STARTED",
        "reboot_verified": False,
        "external_write_rollback_verified": False,
        "service_configuration_applied": False,
        "persistent_drive": None,
        "selected_folder": None,
    }
    if mode == "windows":
        persistent_drive = _volume(persistent_drive)
        if persistent_drive == system_drive:
            raise ValueError("dados persistentes exigem OUTRO volume nao protegido")
        proposal["persistent_drive"] = persistent_drive
    elif persistent_drive:
        raise ValueError("volume persistente apenas para modo Windows")
    if mode == "folder":
        if not isinstance(folder, str) or not folder:
            raise ValueError("selecione uma pasta explicita")
        path = ntpath.normpath(folder)
        drive, tail = ntpath.splitdrive(path)
        if (not drive or not tail.startswith("\\") or
                path.startswith("\\\\") or
                any(chunk in (".", "..") for chunk in folder.split("\\"))):
            raise ValueError("pasta deve ser caminho Windows absoluto local")
        proposal["selected_folder"] = path
    elif folder:
        raise ValueError("pasta configuravel apenas no modo pasta")
    return proposal


def save_proposal_create_only(proposal, pathname):
    """Write untrusted proposal to a new user-chosen file, never to service config.

    Export is only a record of intent. No UAC token, persistence guarantee,
    privileged service/registry modifications, or OS filter activation.
    """
    if not isinstance(pathname, str) or not pathname.lower().endswith(".json"):
        raise ValueError("arquivo de proposta precisa ser .json")
    if not isinstance(proposal, dict) or proposal.get("activation_state") != "NOT_STARTED":
        raise ValueError("somente proposta inativa pode ser exportada")
    raw = (json.dumps(proposal, ensure_ascii=False, sort_keys=True, indent=2)
           + "\n").encode("utf-8")
    if len(raw) > _MAX_JSON:
        raise ValueError("proposta excede tamanho permitido")
    with open(pathname, "xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return len(raw)

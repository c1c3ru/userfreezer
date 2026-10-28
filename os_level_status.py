#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Leitura SOMENTE de estado OS-level observado pelo kernel.

Nenhum comando de ativacao, alteracao de boot, volume ou particao.
Separar 'application-level healthy' de OS-level ativo e fundamental.
Em Windows, filtros UWF/EWF nao sao verificados por esta implementacao:
retornar UNVERIFIED, nunca promover por inferencia.
"""
import os
import subprocess


def probe_target(target, system=None, runner=None):
    """Retorna estado runtime com escopo e evidencia, sem afirmar reboot.

    active = montagem overlay real neste ponto Linux (NAO sistema inteiro).
    inactive = ponto Linux comum sem montagem overlay.
    unverified = Windows ou kernel sem evidencia confiavel.
    error = consulta falhou/target invalido.
    """
    platform = os.name if system is None else system
    item = {
        "state": "unverified",
        "strategy": "unknown",
        "scope": "unknown",
        "source": "not-checked",
        "reboot_verified": False,
        "error": "",
    }
    if platform != "posix":
        item["error"] = "filtro Windows nao consultado; exige validacao UWF/EWF em VM"
        return item
    if not isinstance(target, str) or not os.path.isabs(target):
        item.update(state="error", error="alvo OS-level deve ser absoluto")
        return item
    # O alvo deve ser um diretório real, e nao um symlink ao qual se
    # atribuiria o status de outra montagem.
    if not os.path.isdir(target) or os.path.islink(target):
        item.update(state="error", error="alvo ausente ou simbolico")
        return item
    run = runner or subprocess.run
    try:
        observed = run(
            ["findmnt", "-n", "-o", "FSTYPE", "--mountpoint", target],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        item.update(state="error", source="findmnt",
                    error="consulta mount indisponivel: %s" % exc)
        return item
    item["source"] = "kernel-findmnt"
    if observed.returncode == 1:
        item.update(state="inactive", strategy="none",
                    scope="os-level-directory")
    elif observed.returncode != 0:
        item.update(state="error", error="findmnt retornou erro %s" %
                    observed.returncode)
    elif observed.stdout.strip() == "overlay":
        item.update(state="active", strategy="overlayfs",
                    scope="os-level-directory")
    else:
        item.update(state="inactive", strategy="none",
                    scope="os-level-directory")
    return item

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows protection-scope selection preview (no privileged mutation).

A user may choose a folder or their profile for the application API, but
neither choice intercepts Explorer writes. True rollback requires an
independently activated, OS-supported filesystem write filter or a
separately certified disk/boot architecture. This module NEVER activates
a filter, rewrites BCD, registers a service or writes service configuration.
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WINDOWS_TOOLS = os.path.join(_ROOT, "packaging", "windows")
if _WINDOWS_TOOLS not in sys.path:
    sys.path.insert(0, _WINDOWS_TOOLS)

import os_detect  # noqa: E402


def capability_info(build, edition):
    """Pure platform matrix. No filter is considered active by detection."""
    strategy = os_detect.classify(build, edition)
    value = strategy["strategy"]
    if value == "uwf":
        detail = ("UWF pode estar disponivel nesta edicao. A deteccao NAO "
                  "prova que o filtro esteja instalado, ativo ou proteja C:. "
                  "Exige configuracao administrativa autorizada e reboot.")
    elif value == "ewf_fbwf":
        detail = ("Windows Embedded pode oferecer EWF/FBWF. Verifique "
                  "componentes nativos, volume e reboot em VM; nada sera ativado.")
    elif value == "vhdx_diff":
        detail = ("Edicao sem UWF nativo detectado. VHDX/boot diferencial e "
                  "experimental e NAO e provisionado por esta interface.")
    else:
        detail = ("Sem protecao completa suportada automaticamente nesta "
                  "edicao; Windows 7 comum nao oferece UWF/EWF/FBWF nativos.")
    return {
        "version": strategy["windows_version"],
        "edition": edition,
        "strategy": value,
        "os_filter_verified": False,
        "reboot_verified": False,
        "external_write_rollback_available": False,
        "description": detail,
    }


def local_capability():
    if os.name != "nt":
        return {
            "version": "n/a", "edition": "n/a", "strategy": "unsupported",
            "os_filter_verified": False, "reboot_verified": False,
            "external_write_rollback_available": False,
            "description": "Configuracao do filtro Windows exige Windows.",
        }
    try:
        info = os_detect.get_os_info()
        return capability_info(info["build"], info["edition"])
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "version": "unknown", "edition": "unknown",
            "strategy": "unsupported", "os_filter_verified": False,
            "reboot_verified": False, "external_write_rollback_available": False,
            "description": "Edicao do Windows nao verificavel: %s" % exc,
        }


class ProtectionScopeDialog(object):
    """Interactive selection PREVIEW only: never signals protection enabled."""

    def __init__(self, parent):
        self.parent = parent
        self.top = tk.Toplevel(parent)
        self.top.title("UserFreezer - Escolher modo de protecao")
        self.top.geometry("750x420")
        self.top.transient(parent)
        self.mode = tk.StringVar(master=self.top, value="windows")
        self.selected_folder = tk.StringVar(
            master=self.top, value=os.path.expanduser("~"))
        self.capability = local_capability()

        body = ttk.Frame(self.top, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body, text="Qual protecao voce deseja?",
            font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        ttk.Label(
            body, text=("IMPORTANTE: o UserFreezer ainda NAO protege arquivos "
                        "criados pelo Explorer na Area de Trabalho."),
            wraplength=700).pack(anchor="w", pady=8)

        for value, label in (
            ("windows", "Sistema/volume Windows - descartar alteracoes no reboot (OS-level)"),
            ("profile", "Meu perfil de usuario - somente operacoes pela API"),
            ("folder", "Pasta especifica - somente operacoes pela API"),
        ):
            ttk.Radiobutton(
                body, text=label, variable=self.mode, value=value,
                command=self.refresh_choice).pack(anchor="w", pady=4)

        choose = ttk.Frame(body)
        choose.pack(fill="x", pady=5)
        ttk.Button(choose, text="Escolher pasta...", command=self.choose_folder).pack(
            side="left")
        ttk.Label(choose, textvariable=self.selected_folder,
                  wraplength=530).pack(side="left", padx=8)

        self.detail = ttk.Label(body, text="", wraplength=700)
        self.detail.pack(anchor="w", pady=8)
        self.status = ttk.Label(
            body, text="ATIVACAO: nenhuma configuracao foi alterada.",
            wraplength=700)
        self.status.pack(anchor="w", pady=6)
        ttk.Button(body, text="Fechar", command=self.top.destroy).pack(
            side="right", pady=5)
        self.refresh_choice()

    def choose_folder(self):
        chosen = filedialog.askdirectory(
            parent=self.top, title="Pasta para operacoes pela API")
        if chosen:
            self.selected_folder.set(chosen)
            self.mode.set("folder")
            self.refresh_choice()

    def refresh_choice(self):
        selection = self.mode.get()
        if selection == "windows":
            result = ("Edicao: %s / Windows %s. %s\n"
                      "Modo completo: NAO ATIVADO. Para validar, instalar "
                      "e testar o filtro do SO em VM com snapshot."
                      % (self.capability["edition"],
                         self.capability["version"],
                         self.capability["description"]))
        else:
            location = (os.path.expanduser("~") if selection == "profile"
                        else self.selected_folder.get())
            result = (
                "Pasta escolhida para operacoes via API: %s\n"
                "ATENCAO: essa selecao e somente uma previa. Nao foi "
                "registrada no servico e nao protege escritas do Explorer. "
                "Configurar todo o perfil nao transforma a API em filtro "
                "do Windows." % location)
        self.detail.config(text=result)


def show_protection_scope(parent):
    return ProtectionScopeDialog(parent)

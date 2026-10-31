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
from ui.offline_protection_plan import make_protection_plan, save_proposal_create_only  # noqa: E402
from ui.admin_elevation import run_admin_uwf_stage  # noqa: E402
from admin_client import request  # noqa: E402


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
        self.top.geometry("850x610")
        self.top.transient(parent)
        self.mode = tk.StringVar(master=self.top, value="windows")
        self.selected_folder = tk.StringVar(
            master=self.top, value=os.path.expanduser("~"))
        self.capability = local_capability()
        self.persistent_drive = tk.StringVar(master=self.top, value="D:")
        self.consent = tk.BooleanVar(master=self.top, value=False)
        self.backup = tk.BooleanVar(master=self.top, value=False)

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

        volume = ttk.Frame(body)
        volume.pack(fill="x", pady=7)
        ttk.Label(volume, text="Volume do Windows: C: (padrao)").pack(side="left")
        ttk.Label(volume, text="Dados persistentes em outro volume:").pack(
            side="left", padx=(15, 4))
        ttk.Entry(volume, textvariable=self.persistent_drive,
                  width=6).pack(side="left")
        ttk.Label(
            body, text=("Ex.: D: em disco local separado com backup. "
                        "Selecionar pasta nao intercepta o Explorer."),
            wraplength=790).pack(anchor="w")
        ttk.Checkbutton(
            body, text="Tenho backup/snapshot e entendo que a protecao real "
                       "descartara mudancas em C: apos reboot.",
            variable=self.backup).pack(anchor="w", pady=5)
        ttk.Checkbutton(
            body, text="Autorizo registrar uma PROPOSTA inativa. "
                       "Isto NAO equivale a UAC nem ativa protecao.",
            variable=self.consent).pack(anchor="w", pady=4)

        self.detail = ttk.Label(body, text="", wraplength=700)
        self.detail.pack(anchor="w", pady=8)
        self.status = ttk.Label(
            body, text="ATIVACAO: nenhuma configuracao foi alterada.",
            wraplength=700)
        self.status.pack(anchor="w", pady=6)
        actions = ttk.Frame(body)
        actions.pack(fill="x")
        ttk.Button(
            actions, text="Exportar proposta offline...",
            command=self.export_proposal).pack(side="left", pady=6)
        ttk.Button(
            actions, text="Consultar UWF",
            command=self.inspect_native_uwf).pack(side="left", padx=7)
        ttk.Button(
            actions, text="Agendar UWF na VM (UAC)",
            command=self.stage_native_uwf).pack(side="left", padx=7)
        ttk.Button(actions, text="Fechar", command=self.top.destroy).pack(
            side="right", pady=6)
        self.refresh_choice()

    def inspect_native_uwf(self):
        if self.capability.get("strategy") != "uwf":
            messagebox.showwarning(
                "UWF indisponivel",
                "Este Windows nao oferece UWF nativo confirmado pela edicao.",
                parent=self.top)
            return
        try:
            result = request(
                "uwf-status", "C:", operation=self.persistent_drive.get())
            if not result.get("ok"):
                raise RuntimeError((result.get("error") or {}).get(
                    "message", "UWF indisponivel"))
            data = result["result"]
            self.status.config(
                text=("UWF (WMI): %s | staging em laboratorio: %s | "
                      "rollback externo NAO CERTIFICADO" %
                      (data["status"], data["lab_staging_enabled"])))
        except (RuntimeError, OSError, ValueError, PermissionError) as exc:
            messagebox.showerror("Inspecao UWF recusada", str(exc), parent=self.top)

    def stage_native_uwf(self):
        if self.mode.get() != "windows" or self.capability.get("strategy") != "uwf":
            messagebox.showerror(
                "Nao suportado",
                "Ativacao UWF somente em Windows 10/11 com UWF nativo.",
                parent=self.top)
            return
        try:
            make_protection_plan(
                "windows", system_drive="C:",
                persistent_drive=self.persistent_drive.get(),
                admin_consent=self.consent.get(),
                backup_confirmed=self.backup.get(),
                capability=self.capability)
        except (ValueError, PermissionError) as exc:
            messagebox.showerror("Consentimento obrigatorio", str(exc),
                                 parent=self.top)
            return
        if not messagebox.askyesno(
                "ALTERACAO DO BOOT EM VM DESCARTAVEL",
                "O filtro UWF real pode alterar paginacao e recuperacao "
                "do Windows, e descartar novas gravacoes em C: apos reboot. "
                "Voce ja salvou o snapshot da VM e confirmou que D: "
                "sera persistente? Deseja solicitar UAC e agendar?",
                parent=self.top):
            return
        try:
            run_admin_uwf_stage(self.persistent_drive.get())
        except (OSError, RuntimeError, PermissionError, ValueError) as exc:
            self.status.config(text="UWF: resultado recusado/indeterminado")
            messagebox.showerror(
                "UWF nao confirmado",
                "Nao reinicie sem inspecionar a configuracao UWF. %s" % exc,
                parent=self.top)
            return
        self.status.config(
            text="UWF AGENDADO PARA PROXIMO BOOT; NAO ATIVO NESTA SESSAO.")
        messagebox.showinfo(
            "Reboot manual necessario",
            "O servico confirmou o agendamento no WMI. Reinicie a VM "
            "MANUALMENTE e depois teste Explorer/rollback. "
            "Nenhuma equivalencia ao Deep Freeze foi certificada.",
            parent=self.top)

    def export_proposal(self):
        # Data-only; no IPC, UAC or filter changes.
        mode = self.mode.get()
        try:
            proposal = make_protection_plan(
                mode, system_drive="C:",
                persistent_drive=(self.persistent_drive.get()
                                  if mode == "windows" else None),
                folder=self.selected_folder.get() if mode == "folder" else None,
                admin_consent=self.consent.get(),
                backup_confirmed=self.backup.get(),
                capability=self.capability)
        except (ValueError, PermissionError) as exc:
            messagebox.showerror("Proposta recusada", str(exc), parent=self.top)
            return
        if not messagebox.askyesno(
                "Confirmar proposta nao aplicada",
                "Exportar a proposta offline? Nenhum filtro nem servico "
                "sera ativado e o plano nao garante rollback do Explorer.",
                parent=self.top):
            return
        destination = filedialog.asksaveasfilename(
            parent=self.top,
            title="Salvar proposta de configuracao (sem ativar)",
            defaultextension=".json", initialfile="userfreezer-plan.json",
            filetypes=[("JSON", "*.json")])
        if not destination:
            return
        try:
            save_proposal_create_only(proposal, destination)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Falha no arquivo", str(exc), parent=self.top)
            return
        self.status.config(text="PROPOSTA SALVA; PROTECAO OS-LEVEL NAO ATIVADA.")
        messagebox.showinfo(
            "Plano offline salvo",
            "Proposta gravada. Para ensaio UWF em VM Windows 10/11 "
            "compativel, consultar packaging/windows/os_level/"
            "uwf_lab_stage.ps1. Nunca executar em producao.",
            parent=self.top)

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
                      "Modo completo: NAO ATIVADO. Dados persistentes em outro volume. Para validar, instalar "
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

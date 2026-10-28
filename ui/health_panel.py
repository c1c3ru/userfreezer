#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Painel administrativo multialvos via IPC (Windows 7/Python 3.8).

Sem leitura de config e SEM importar DeepFreezer: o serviço autentica e
autoriza cada pedido, usando o token do SO. Uma sessao comum pode VER
status; operacoes falham sem token elevado/root.
"""
import argparse
import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

UI_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(UI_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from admin_client import request  # noqa: E402
from ui.admin_elevation import run_admin_action  # noqa: E402


class AdminPanel(object):
    def __init__(self, root, socket_path=None, preselect=None):
        self.root = root
        self.socket_path = socket_path
        self.preselect = preselect
        self.root.title("DeepFreezer - Gerenciamento local autenticado")
        self.root.geometry("1200x580")
        self.entries = {}
        self.last_snapshot = None

        header = ttk.Frame(root, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text="Alvos do DeepFreezer",
                  font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        self.status = ttk.Label(header, text="Conectando ao servico...")
        self.status.pack(anchor="w", pady=4)
        ttk.Label(header, text="API healthy != OS protegido. Estado do kernel consultado separadamente; ativo por diretorio nao comprova reboot.",
                  wraplength=1120).pack(anchor="w")

        body = ttk.Frame(root, padding=(12, 0, 12, 10))
        body.pack(fill="both", expand=True)
        columns = ("target", "state", "os_level", "paths", "overlay", "error")
        self.table = ttk.Treeview(body, columns=columns, show="headings",
                                  selectmode="browse")
        labels = {"target": "Alvo", "state": "API / agora", "os_level": "Kernel / escopo",
                  "paths": "Base / pendentes", "overlay": "Overlay / tamanho",
                  "error": "Falha"}
        widths = {"target": 215, "state": 142, "os_level": 155, "paths": 110,
                  "overlay": 245, "error": 235}
        for key in columns:
            self.table.heading(key, text=labels[key])
            self.table.column(key, width=widths[key], minwidth=75)
        scrollbar = ttk.Scrollbar(body, orient="vertical",
                                  command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(root, padding=12)
        footer.pack(fill="x")
        ttk.Button(footer, text="Atualizar", command=self.refresh).pack(side="left", padx=2)
        ttk.Button(footer, text="Exportar diagnostico", command=self.export).pack(side="left", padx=2)
        ttk.Button(footer, text="Congelar", command=lambda: self.action("freeze")).pack(side="left", padx=2)
        ttk.Button(footer, text="Descartar", command=lambda: self.action("discard")).pack(side="left", padx=2)
        ttk.Button(footer, text="Aplicar (commit)", command=lambda: self.action("commit")).pack(side="left", padx=2)
        ttk.Button(footer, text="Fechar", command=root.destroy).pack(side="right")
        self.refresh()

    def _request(self, action="status", target=None, confirm=None, operation=None):
        response = request(action, target, confirm, operation,
                           socket_path=self.socket_path)
        if not response.get("ok"):
            err = response.get("error") or {}
            raise PermissionError(err.get("message", "Operacao recusada pelo servico"))
        return response["result"]

    def refresh(self):
        selected = self.selected_target() or self.preselect
        try:
            snapshot = self._request("status")
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            self.status.config(text="Servico IPC nao disponivel: %s" % exc)
            return
        for item in self.table.get_children():
            self.table.delete(item)
        self.entries.clear()
        self.last_snapshot = snapshot
        self.status.config(text="Ultimo enforcement: %s | Estado: %s | Alvos: %d" %
                           (snapshot.get("timestamp"), snapshot.get("state"),
                            len(snapshot.get("targets", []))))
        for index, entry in enumerate(snapshot.get("targets", [])):
            target = entry["target"]
            iid = str(index)
            self.entries[iid] = entry
            runtime = entry.get("frozen")
            now_state = ("indisponivel" if runtime is None else
                         "congelado" if runtime else "descongelado")
            ops = entry.get("pending_ops") or {}
            pending = sum(int(x) for x in ops.values())
            os_level = entry.get("os_level") or {}
            os_state = os_level.get("state", "unverified")
            os_scope = os_level.get("scope", "unknown")
            os_strategy = os_level.get("strategy", "unknown")
            error = (entry.get("runtime_error") or entry.get("error", "") or
                     os_level.get("error", ""))
            self.table.insert("", "end", iid=iid, values=(
                target, "%s / %s" % (entry.get("state", "error"), now_state),
                "%s (%s, %s)" % (os_state, os_strategy, os_scope),
                "%s / %s" % (entry.get("baseline_paths", 0), pending),
                "%s (%s bytes%s)" % (
                    entry.get("overlay", ""),
                    entry.get("overlay_bytes", "?"),
                    "+" if entry.get("overlay_size_partial") else ""), error))
            if target == selected:
                self.table.selection_set(iid)
                self.table.focus(iid)
        self.preselect = None

    def export(self):
        if self.last_snapshot is None:
            messagebox.showwarning("DeepFreezer", "Nenhum diagnostico disponivel.",
                                   parent=self.root)
            return
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Exportar diagnostico",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")])
        if not destination:
            return
        try:
            # O snapshot IPC nao inclui credenciais/hash/senha, somente
            # estados, nomes de alvos e mensagens tecnicas.
            with open(destination, "w", encoding="utf-8") as f:
                json.dump(self.last_snapshot, f, indent=2, ensure_ascii=False)
                f.write("\\n")
        except OSError as exc:
            messagebox.showerror("Falha na exportacao", str(exc), parent=self.root)
            return
        messagebox.showinfo("DeepFreezer",
                            "Diagnostico exportado (sem credenciais).",
                            parent=self.root)

    def selected_target(self):
        current = self.table.selection()
        if not current:
            return None
        entry = self.entries.get(current[0])
        return entry["target"] if entry else None

    def action(self, operation):
        if operation == "commit" and os.name == "nt":
            messagebox.showerror(
                "Commit indisponivel no Windows",
                "Operacao bloqueada pelo core por seguranca (#63). "
                "Um teste mostrou troca concorrente de diretorios mesmo "
                "com handles Win32 abertos. Descarte alteracoes ou "
                "aguarde o backend com commit seguro.",
                parent=self.root)
            return
        target = self.selected_target()
        if not target:
            messagebox.showwarning("DeepFreezer", "Selecione um alvo primeiro.",
                                   parent=self.root)
            return
        if operation == "freeze":
            if not messagebox.askyesno(
                    "Confirmacao", "Congelar este alvo via servico?\n%s" % target,
                    parent=self.root):
                return
        else:
            label = "COMMIT" if operation == "commit" else "DESCARTAR"
            verb = ("APLICAR permanentemente as alteracoes" if operation == "commit"
                    else "DESCARTAR todas as alteracoes da sessao")
            response = simpledialog.askstring(
                "Confirmacao destrutiva",
                "Voce solicitou %s em:\n%s\n\nDigite %s para confirmar:" %
                (verb, target, label), parent=self.root)
            if response != label:
                return
        try:
            # UI continua sem privilegios; OS promove um helper imutavel
            # root/Program Files. Broker valida token, alvo e nonce.
            run_admin_action(operation, target, self.socket_path)
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            messagebox.showerror("Falha na autorizacao",
                                 "%s\nNenhuma operacao local de fallback foi executada." %
                                 exc, parent=self.root)
            self.refresh()
            return
        messagebox.showinfo(
            "DeepFreezer", "Comando concluido pelo servico autorizado.",
            parent=self.root)
        self.refresh()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", help="socket Unix local; no Windows usa named pipe")
    parser.add_argument("--target", help="alvo a selecionar inicialmente")
    args = parser.parse_args(argv)
    root = tk.Tk()
    AdminPanel(root, args.socket, args.target)
    root.mainloop()


if __name__ == "__main__":
    main()

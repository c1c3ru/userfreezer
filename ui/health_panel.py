#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Painel administrativo multialvos via IPC (Windows 7/Python 3.8).

Sem leitura de config e SEM importar DeepFreezer: o serviço autentica e
autoriza cada pedido, usando o token do SO. Uma sessao comum pode VER
status; operacoes falham sem token elevado/root.
"""
import argparse
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

UI_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(UI_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from admin_client import request  # noqa: E402


class AdminPanel(object):
    def __init__(self, root, socket_path=None, preselect=None):
        self.root = root
        self.socket_path = socket_path
        self.preselect = preselect
        self.root.title("DeepFreezer - Gerenciamento local autenticado")
        self.root.geometry("1060x560")
        self.entries = {}

        header = ttk.Frame(root, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text="Alvos do DeepFreezer",
                  font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        self.status = ttk.Label(header, text="Conectando ao servico...")
        self.status.pack(anchor="w", pady=4)
        ttk.Label(header, text="Somente application-level: 'healthy' nao significa protecao do disco inteiro.",
                  wraplength=990).pack(anchor="w")

        body = ttk.Frame(root, padding=(12, 0, 12, 10))
        body.pack(fill="both", expand=True)
        columns = ("target", "state", "paths", "overlay", "error")
        self.table = ttk.Treeview(body, columns=columns, show="headings",
                                  selectmode="browse")
        labels = {"target": "Alvo", "state": "Ultimo ciclo", "paths": "Arquivos",
                  "overlay": "Overlay", "error": "Falha"}
        widths = {"target": 235, "state": 110, "paths": 85,
                  "overlay": 300, "error": 265}
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
        self.status.config(text="Ultimo enforcement: %s | Estado: %s | Alvos: %d" %
                           (snapshot.get("timestamp"), snapshot.get("state"),
                            len(snapshot.get("targets", []))))
        for index, entry in enumerate(snapshot.get("targets", [])):
            target = entry["target"]
            iid = str(index)
            self.entries[iid] = entry
            self.table.insert("", "end", iid=iid, values=(
                target, entry.get("state", "error"),
                entry.get("baseline_paths", 0),
                entry.get("overlay", ""), entry.get("error", "")))
            if target == selected:
                self.table.selection_set(iid)
                self.table.focus(iid)
        self.preselect = None

    def selected_target(self):
        current = self.table.selection()
        if not current:
            return None
        entry = self.entries.get(current[0])
        return entry["target"] if entry else None

    def action(self, operation):
        target = self.selected_target()
        if not target:
            messagebox.showwarning("DeepFreezer", "Selecione um alvo primeiro.",
                                   parent=self.root)
            return
        if operation == "freeze":
            if not messagebox.askyesno("Confirmacao",
                                       "Congelar este alvo via servico?\n%s" % target,
                                       parent=self.root):
                return
            confirmation = None
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
                challenge = self._request("prepare", target, operation=operation)
                confirmation = challenge["token"]
            except (OSError, ValueError, RuntimeError, PermissionError) as exc:
                messagebox.showerror("Autorizacao negada", str(exc), parent=self.root)
                return
        try:
            result = self._request(operation, target, confirm=confirmation)
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            messagebox.showerror("Falha na operacao",
                                 "O servico recusou o comando: %s\n"
                                 "A autorizacao pertence ao sistema operacional "
                                 "(UID root / Windows Administrators elevado)." % exc,
                                 parent=self.root)
            return
        messagebox.showinfo("DeepFreezer",
                            "Acao executada no alvo: %s\nCongelado: %s" %
                            (result["target"], result["frozen"]),
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

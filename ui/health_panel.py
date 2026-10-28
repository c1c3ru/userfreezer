#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Painel Tk/ttk somente leitura para todos os alvos (Python 3.8/Win7).

A interface nao possui IPC administrativo nesta etapa. O arquivo status.json
e protegido; executar a consulta com credenciais administrativas, SEM
relaxar permissões. Para UI nao privilegiada, implementar #53 primeiro.
"""
import argparse
import os
import tkinter as tk
from tkinter import ttk, messagebox

from health_model import load_health_report


def default_path():
    if os.name == "nt":
        return os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                            "DeepFreezer", "status.json")
    return "/var/lib/deepfreezer/status.json"


class HealthPanel(object):
    def __init__(self, root, path):
        self.root = root
        self.path = path
        self.root.title("DeepFreezer - Saude do servico (somente leitura)")
        self.root.geometry("940x510")
        header = ttk.Frame(root, padding=12)
        header.pack(fill="x")
        self.title = ttk.Label(
            header, text="Monitoramento de alvos", font=("TkDefaultFont", 15, "bold"))
        self.title.pack(anchor="w")
        self.status = ttk.Label(
            header, text="Nenhum relatorio carregado.")
        self.status.pack(anchor="w", pady=4)
        self.warning = ttk.Label(
            header, text="Apenas application-level: isto nao protege o SO inteiro.")
        self.warning.pack(anchor="w")
        body = ttk.Frame(root, padding=(12, 0, 12, 10))
        body.pack(fill="both", expand=True)
        cols = ("target", "state", "paths", "overlay", "error")
        self.table = ttk.Treeview(body, columns=cols, show="headings")
        labels = {"target": "Alvo", "state": "Saude", "paths": "Caminhos",
                  "overlay": "Overlay", "error": "Diagnostico"}
        widths = {"target": 245, "state": 85, "paths": 75,
                  "overlay": 230, "error": 250}
        for col in cols:
            self.table.heading(col, text=labels[col])
            self.table.column(col, width=widths[col], minwidth=70, stretch=True)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        footer = ttk.Frame(root, padding=12)
        footer.pack(fill="x")
        ttk.Button(footer, text="Atualizar", command=self.refresh).pack(side="left")
        ttk.Button(footer, text="Fechar", command=root.destroy).pack(side="right")
        self.refresh()

    def refresh(self):
        for item in self.table.get_children():
            self.table.delete(item)
        try:
            report = load_health_report(self.path)
        except (OSError, ValueError) as exc:
            self.status.config(text="Sem leitura de status: %s" % exc)
            return
        self.status.config(text="Ultimo ciclo: %s  |  Estado: %s  |  Alvos: %d" %
                           (report["timestamp"], report["state"],
                            len(report["targets"])))
        for item in report["targets"]:
            self.table.insert("", "end", values=(
                item["target"], item["state"], item["baseline_paths"],
                item["overlay"], item["message"]))
        if report["config_error"]:
            messagebox.showwarning("Falha no enforcement",
                                   report["config_error"], parent=self.root)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", default=default_path(),
                        help="status.json seguro gerado pelo servico")
    args = parser.parse_args(argv)
    root = tk.Tk()
    HealthPanel(root, args.status)
    root.mainloop()


if __name__ == "__main__":
    main()

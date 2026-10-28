#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bandeja sem privilegios: observa o broker e abre o painel IPC.

Nao le config.json, nao valida senha local, nao importa DeepFreezer.
Todas as mutacoes passam pelo servico, que verifica o token do SO.
"""
import argparse
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

UI_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(UI_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from admin_client import request  # noqa: E402
from icons import icon_for  # noqa: E402
import pystray  # noqa: E402


class TrayApp(object):
    def __init__(self, socket_path=None, target=None):
        self.socket_path = socket_path
        self.target = target
        state = self._safe_status()
        self.icon = pystray.Icon("deepfreezer", icon_for(
            state == "healthy"), "DeepFreezer (ultimo ciclo: %s)" % state,
            menu=pystray.Menu(
                pystray.MenuItem("Abrir painel de alvos...", self._open_panel),
                pystray.MenuItem("Atualizar estado...", self._refresh),
                pystray.MenuItem("Sair", self._quit)))

    def _safe_status(self):
        try:
            reply = request(socket_path=self.socket_path)
            if reply.get("ok"):
                return reply["result"].get("state", "unknown")
            return "error"
        except (OSError, RuntimeError, ValueError):
            return "unavailable"

    def _refresh(self, _icon=None, _item=None):
        state = self._safe_status()
        self.icon.icon = icon_for(state == "healthy")
        self.icon.title = "DeepFreezer (ultimo ciclo: %s; so application-level)" % state

    def _open_panel(self, _icon=None, _item=None):
        args = [sys.executable, os.path.join(UI_DIR, "health_panel.py")]
        if self.socket_path:
            args.extend(["--socket", self.socket_path])
        if self.target:
            args.extend(["--target", self.target])
        try:
            subprocess.Popen(args, cwd=ROOT_DIR)
        except OSError as exc:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("DeepFreezer", "Nao foi possivel abrir painel: %s" %
                                 exc, parent=root)
            root.destroy()

    def _quit(self, _icon=None, _item=None):
        self.icon.stop()

    def run(self):
        self.icon.run()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--config", help="obsoleto: painel consulta broker, nao config")
    p.add_argument("--target", help="alvo selecionado inicialmente")
    p.add_argument("--socket", help="socket local Linux")
    a = p.parse_args(argv)
    TrayApp(socket_path=a.socket, target=a.target).run()


if __name__ == "__main__":
    main()

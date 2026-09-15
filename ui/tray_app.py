#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bandeja do sistema do DeepFreezer -- icone azul (congelado) / laranja
(descongelado), painel de status e alternancia de estado atras de
senha de admin.

Unica parte do projeto com dependencias externas (core e daemon sao
so' stdlib): requer 'pystray' + 'Pillow'. Os dialogos usam Tkinter
(stdlib, mas no Linux pode exigir o pacote de SO 'python3-tk').

Uso: python3 tray_app.py --config /etc/deepfreezer/config.json [--target /caminho]

Sem --target, usa o primeiro alvo listado no config (mesmo config.json
do daemon). A senha de admin e' definida por set_admin_password.py.
"""
import argparse
import json
import os
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog

_UI_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_UI_DIR))
from deepfreezer import DeepFreezer, DeepFreezeError  # noqa: E402

sys.path.insert(0, _UI_DIR)
from admin_auth import load_admin_hash, verify_password  # noqa: E402
from icons import icon_for  # noqa: E402

import pystray  # noqa: E402


def _dir_size(path):
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def _human_size(n):
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return "%.1f%s" % (size, unit)
        size /= 1024.0
    return "%.1f PB" % size


class TrayApp(object):
    def __init__(self, config_path, target):
        self.config_path = config_path
        self.target = target
        self._root = None
        self.icon = pystray.Icon(
            "deepfreezer", icon_for(self._is_frozen()), "DeepFreezer",
            menu=self._build_menu())

    # -- estado ---------------------------------------------------------
    def _open_df(self):
        return DeepFreezer(self.target)

    def _is_frozen(self):
        try:
            with self._open_df() as df:
                return df.frozen
        except DeepFreezeError:
            return False

    def _status_text(self):
        try:
            with self._open_df() as df:
                st = df.status()
        except DeepFreezeError as e:
            return "erro: %s" % e
        if not st["frozen"]:
            return "Estado: DESCONGELADO\nAlvo: %s" % st["target"]
        size = _dir_size(st["overlay"]) if os.path.isdir(st["overlay"]) else 0
        return (
            "Estado: CONGELADO\n"
            "Alvo: %s\n"
            "Congelado em: %s\n"
            "Arquivos monitorados: %d\n"
            "Uso de disco do overlay: %s\n"
            "Mudancas pendentes: %d"
        ) % (st["target"], st["frozen_at"], st["baseline_paths"],
             _human_size(size), st["pending_seq"])

    # -- autenticacao -----------------------------------------------------
    def _tk_root(self):
        if self._root is None:
            self._root = tk.Tk()
            self._root.withdraw()
        return self._root

    def _require_password(self):
        digest_hex, salt_hex = load_admin_hash(self.config_path)
        root = self._tk_root()
        if not digest_hex:
            messagebox.showerror(
                "DeepFreezer",
                "Nenhuma senha de admin configurada.\n"
                "Rode set_admin_password.py antes de usar o painel.",
                parent=root)
            return False
        pw = simpledialog.askstring(
            "DeepFreezer", "Senha de administrador:", show="*", parent=root)
        if pw is None:
            return False
        if verify_password(pw, digest_hex, salt_hex):
            return True
        messagebox.showerror("DeepFreezer", "Senha incorreta.", parent=root)
        return False

    # -- acoes ------------------------------------------------------------
    def _show_status(self, _icon=None, _item=None):
        if not self._require_password():
            return
        messagebox.showinfo("DeepFreezer - Status", self._status_text(),
                             parent=self._tk_root())

    def _toggle(self, _icon=None, _item=None):
        if not self._require_password():
            return
        root = self._tk_root()
        try:
            if self._is_frozen():
                commit = messagebox.askyesnocancel(
                    "DeepFreezer",
                    "Descongelar:\n"
                    "SIM = aplicar as mudancas da sessao (commit)\n"
                    "NAO = descartar e restaurar o estado congelado\n"
                    "CANCELAR = nao fazer nada",
                    parent=root)
                if commit is None:
                    return
                with self._open_df() as df:
                    df.thaw(commit=commit)
            else:
                with self._open_df() as df:
                    df.freeze()
        except DeepFreezeError as e:
            messagebox.showerror("DeepFreezer", "Erro: %s" % e, parent=root)
            return
        self.icon.icon = icon_for(self._is_frozen())
        self.icon.menu = self._build_menu()

    def _quit(self, _icon=None, _item=None):
        self.icon.stop()

    def _build_menu(self):
        toggle_label = "Descongelar..." if self._is_frozen() else "Congelar"
        return pystray.Menu(
            pystray.MenuItem("Status...", self._show_status),
            pystray.MenuItem(toggle_label, self._toggle),
            pystray.MenuItem("Sair", self._quit),
        )

    def run(self):
        self.icon.run()


def _load_default_target(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    targets = cfg.get("targets", [])
    if not targets:
        raise SystemExit("config sem 'targets': %s" % config_path)
    return targets[0]["target"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tray_app")
    ap.add_argument("--config", required=True,
                     help="config.json compartilhado com o daemon")
    ap.add_argument("--target", help="sobrepoe o 1o alvo do config")
    a = ap.parse_args(argv)

    target = a.target or _load_default_target(a.config)
    TrayApp(a.config, target).run()


if __name__ == "__main__":
    main()

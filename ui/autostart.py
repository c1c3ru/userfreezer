#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Autostart da BANDEJA no perfil do usuario, sem privilegio/admin.

Linux: XDG ~/.config/autostart. Windows 7+: HKCU Run.
Nunca altera o servico privilegiado nem o config.json root-only.
"""
import argparse
import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "DeepFreezerTray"
DESKTOP_NAME = "deepfreezer-tray.desktop"


def _default_tray():
    return os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        "tray_app.py"))


def _desktop_arg(value):
    # XDG Desktop Entry Exec: quoted arguments, sem interpretacao de shell.
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    for literal in ("$", "`"):
        value = value.replace(literal, "\\" + literal)
    return '"' + value.replace("%", "%%") + '"'


def desktop_entry(executable, tray):
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=DeepFreezer Tray\n"
            "Comment=Status do freezer por IPC; nao requer root\n"
            "Exec=%s %s\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n" %
            (_desktop_arg(executable), _desktop_arg(tray)))


def _validated_command(tray_path, executable):
    tray = os.path.abspath(tray_path or _default_tray())
    binary = os.path.abspath(executable or sys.executable)
    if not os.path.isfile(tray) or not os.path.isfile(binary):
        raise FileNotFoundError("Python/tray nao foram localizados")
    return binary, tray


def _linux_path():
    root = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    if not os.path.isabs(root):
        raise ValueError("XDG_CONFIG_HOME deve ser absoluto")
    return os.path.join(root, "autostart", DESKTOP_NAME)


def install(tray_path=None, executable=None):
    binary, tray = _validated_command(tray_path, executable)
    if os.name == "nt":
        import subprocess
        import winreg
        # Evitar terminal na abertura do desktop quando existir pythonw.
        if binary.lower().endswith("python.exe"):
            gui = os.path.join(os.path.dirname(binary), "pythonw.exe")
            if os.path.isfile(gui):
                binary = gui
        command = subprocess.list2cmdline([binary, tray])
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)
        return "HKCU:" + RUN_KEY + "/" + RUN_VALUE

    path = _linux_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    # escrita atomica 0600, somente perfil do usuario atual.
    temp = path + ".%d.tmp" % os.getpid()
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(desktop_entry(binary, tray))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)
    return path


def remove():
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            return False
        return True
    path = _linux_path()
    if os.path.isfile(path) and not os.path.islink(path):
        os.unlink(path)
        return True
    return False


def main(argv=None):
    p = argparse.ArgumentParser(description="Autostart da bandeja (usuario)")
    actions = p.add_mutually_exclusive_group(required=True)
    actions.add_argument("--install", action="store_true")
    actions.add_argument("--remove", action="store_true")
    args = p.parse_args(argv)
    if args.install:
        print(install())
    else:
        print("removido" if remove() else "nao instalado")
    return 0


if __name__ == "__main__":
    sys.exit(main())

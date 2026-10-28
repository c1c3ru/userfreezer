#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cliente local do broker. Sem acesso direto a DeepFreezer ou config.json.

Para mutacoes Linux: processo cliente deve ser root (ex.: sudo/pkexec).
Para Windows: token elevado Administrators, conferido pelo SERVIDOR.
"""
import argparse
import json
import os
import sys

from admin_ipc import request_unix

DEFAULT_UNIX_SOCKET = "/run/deepfreezer/admin.sock"


def request(action="status", target=None, confirm=None, operation=None,
            socket_path=None):
    if os.name == "nt":
        from admin_ipc_win import request_windows
        return request_windows(action, target, confirm, operation)
    return request_unix(socket_path or DEFAULT_UNIX_SOCKET, action, target,
                        confirm, operation)


def main(argv=None):
    p = argparse.ArgumentParser(description="DeepFreezer - cliente IPC local")
    p.add_argument("action", choices=("status", "freeze", "prepare", "discard", "commit"))
    p.add_argument("--target", help="alvo cadastrado")
    p.add_argument("--operation", choices=("discard", "commit"))
    p.add_argument("--confirm", help="nonce fornecido por prepare")
    p.add_argument("--socket", default=None)
    a = p.parse_args(argv)
    try:
        response = request(a.action, a.target, a.confirm, a.operation, a.socket)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Define ou atualiza a senha de admin da UI do DeepFreezer.

Uso: python3 set_admin_password.py --config /etc/deepfreezer/config.json
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from admin_auth import set_admin_password  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True,
                     help="config.json compartilhado com o daemon")
    a = ap.parse_args(argv)

    pw1 = getpass.getpass("Nova senha de admin: ")
    pw2 = getpass.getpass("Confirme a senha: ")
    if pw1 != pw2:
        print("erro: senhas nao conferem", file=sys.stderr)
        return 1
    if len(pw1) < 8:
        print("erro: use pelo menos 8 caracteres", file=sys.stderr)
        return 1

    set_admin_password(a.config, pw1)
    print("senha de admin atualizada em %s" % a.config)
    return 0


if __name__ == "__main__":
    sys.exit(main())

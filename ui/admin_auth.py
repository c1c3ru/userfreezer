#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autenticacao de admin para a UI do DeepFreezer -- so' stdlib.

A senha nunca e' guardada em texto plano: PBKDF2-HMAC-SHA256 com salt
aleatorio por instalacao. Hash e salt (hex) ficam gravados no mesmo
config.json usado pelo core/daemon, nas chaves "admin_password_hash"
e "admin_password_salt".
"""
import hashlib
import hmac
import json
import os

PBKDF2_ITERATIONS = 200_000
_HASH_KEY = "admin_password_hash"
_SALT_KEY = "admin_password_salt"


def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password, stored_hash_hex, salt_hex):
    if not stored_hash_hex or not salt_hex:
        return False
    salt = bytes.fromhex(salt_hex)
    digest_hex, _ = hash_password(password, salt)
    return hmac.compare_digest(digest_hex, stored_hash_hex)


def load_admin_hash(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return None, None
    return cfg.get(_HASH_KEY), cfg.get(_SALT_KEY)


def has_admin_password(config_path):
    digest_hex, salt_hex = load_admin_hash(config_path)
    return bool(digest_hex and salt_hex)


def set_admin_password(config_path, password):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {"targets": []}
    digest_hex, salt_hex = hash_password(password)
    cfg[_HASH_KEY] = digest_hex
    cfg[_SALT_KEY] = salt_hex
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, config_path)

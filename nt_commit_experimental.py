#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROTOTIPO ISOLADO: plano de alteracoes Windows SOMENTE por handles NT.

Nao usado pelo core DeepFreezer, por IPC ou por CLI. Nao reativa
thaw(commit=True). Os processos nao confiaveis podem trocar a raiz
ANTES da abertura, e a aplicacao de multiplas operacoes NAO e atomica.
Exige validacao de ACL/raiz, concurrency/stress e Win7 SP1 (#63).
"""
import contextlib
import os
import secrets

from win32_relative_directory import (
    _validate_component, open_trusted_root, open_relative_directory,
    create_relative_directory, create_relative_file, rename_relative_file,
    delete_relative_file, remove_relative_tree,
)


class PartialCommitError(RuntimeError):
    """Falha com registro das alteracoes ja executadas sem rollback."""
    def __init__(self, completed, cause):
        self.completed = tuple(completed)
        RuntimeError.__init__(self, "plano NT interrompido apos %d operacoes: %s" %
                              (len(completed), cause))


def _split_relative(rel):
    if not isinstance(rel, str) or not rel or rel.startswith("/"):
        raise ValueError("caminho relativo invalido")
    parts = rel.split("/")
    for component in parts:
        _validate_component(component)
    return parts


def _validate_plan(plan):
    if not isinstance(plan, (tuple, list)) or len(plan) > 10000:
        raise ValueError("plano invalido ou extenso")
    checked = []
    for entry in plan:
        if not isinstance(entry, (tuple, list)) or len(entry) != 3:
            raise ValueError("item deve ser (tipo, caminho, payload)")
        kind, rel, payload = entry
        if kind not in ("W", "M", "F", "D"):
            raise ValueError("operacao NT desconhecida")
        parts = _split_relative(rel)
        if kind == "W":
            if not isinstance(payload, bytes):
                raise ValueError("write exige bytes")
        elif payload is not None:
            raise ValueError("operacao sem write nao aceita payload")
        checked.append((kind, rel, parts, payload))
    return checked


def apply_plan_experimental(root, plan, on_root_pinned=None):
    """Aplica operacoes de teste com uma raiz previamente confiavel.

    W: gravar/replace arquivo; M: mkdir; F: unlink regular; D: rmtree.
    on_root_pinned e injetavel apenas para stress/teste de troca de path.
    Nao permite input de usuario comum nem autorizacao IPC.
    """
    if os.name != "nt":
        raise OSError("plano NT so pode ser executado no Windows")
    checked = _validate_plan(plan)
    completed = []
    with open_trusted_root(root) as trusted:
        if on_root_pinned:
            on_root_pinned()
        for kind, rel, parts, payload in checked:
            try:
                with contextlib.ExitStack() as stack:
                    parent = trusted
                    for component in parts[:-1]:
                        try:
                            child = stack.enter_context(
                                open_relative_directory(parent, component))
                        except OSError:
                            if kind not in ("W", "M"):
                                raise
                            # Se o item existente for reparse, mkdir falha
                            # e nunca seguimos o link no nome.
                            create_relative_directory(parent, component)
                            child = stack.enter_context(
                                open_relative_directory(parent, component))
                        parent = child
                    name = parts[-1]
                    if kind == "W":
                        temp = ".deepfreezer-%s.tmp" % secrets.token_hex(12)
                        try:
                            create_relative_file(parent, temp, payload)
                            rename_relative_file(parent, temp, name,
                                                 replace=True)
                        except BaseException:
                            try:
                                delete_relative_file(parent, temp)
                            except OSError:
                                pass
                            raise
                    elif kind == "M":
                        try:
                            create_relative_directory(parent, name)
                        except OSError:
                            # Idempotente SOMENTE se existe diretorio real.
                            with open_relative_directory(parent, name):
                                pass
                    elif kind == "F":
                        delete_relative_file(parent, name)
                    else:
                        remove_relative_tree(parent, name)
                completed.append(rel)
            except (OSError, ValueError) as exc:
                raise PartialCommitError(completed, exc) from exc
    return completed

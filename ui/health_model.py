#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Leitura e validacao de relatórios do serviço para exibição somente leitura."""
import json
import os

VALID_STATES = ("healthy", "degraded", "error")


def parse_health_report(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Formato de status nao suportado (schema_version != 1)")
    if data.get("protection_scope") != "application-level":
        raise ValueError("Escopo de protecao inesperado ou nao identificado")
    if data.get("state") not in VALID_STATES:
        raise ValueError("Estado geral desconhecido")
    entries = data.get("targets")
    if not isinstance(entries, list) or len(entries) > 1000:
        raise ValueError("Lista de alvos invalida ou grande demais")
    rows = []
    for item in entries:
        if not isinstance(item, dict) or item.get("state") not in VALID_STATES:
            raise ValueError("Estado de alvo invalido")
        rows.append({
            "target": str(item.get("target") or "<desconhecido>"),
            "state": item["state"],
            "overlay": str(item.get("overlay") or ""),
            "message": str(item.get("error") or ""),
            "baseline_paths": item.get("baseline_paths", ""),
        })
    return {
        "state": data["state"],
        "timestamp": str(data.get("last_enforcement_utc") or ""),
        "scope": data["protection_scope"],
        "config_error": str(data.get("config_error") or ""),
        "targets": rows,
    }


def load_health_report(path):
    """Nao executa comandos e NAO tenta elevar privilegios."""
    if os.stat(path).st_size > (1 << 20):
        raise ValueError("Arquivo de saude excede 1 MiB")
    with open(path, "r", encoding="utf-8") as f:
        return parse_health_report(json.load(f))

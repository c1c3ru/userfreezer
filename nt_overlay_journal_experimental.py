#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXPERIMENTAL pinned NT journal reconciliation; NEVER mutates files.

Reads manifest and journal through a trusted, pre-enrolled overlay handle.
Rejects truncated/duplicate/out-of-order journal records, malformed paths,
and any mismatch with the core's in-memory state. No production commit here.
"""
import json
import ntpath

from nt_commit_experimental import _validate_plan
from nt_enrollment_experimental import _canonical_root
from nt_enrollment_store_experimental import (
    _assert_protected_acl, load_identity_from_store,
)
from win32_relative_directory import (
    directory_identity, open_trusted_root, read_relative_file,
)

MAX_JOURNAL_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 10000


def _unique_object(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("chave duplicada no journal NT")
        data[key] = value
    return data


def _parse_pinned_metadata(manifest_raw, journal_raw, expected_root,
                           expected_ops, expected_payload_ids, expected_seq):
    """Validate exact core state against handle-read metadata before I/O."""
    if not isinstance(manifest_raw, bytes) or not isinstance(journal_raw, bytes):
        raise ValueError("metadados do overlay NT invalidos")
    if not isinstance(expected_ops, dict) or not isinstance(expected_payload_ids, dict):
        raise ValueError("estado em memoria invalido")
    if type(expected_seq) is not int or expected_seq < 0:
        raise ValueError("sequencia de journal invalida")
    canonical = _canonical_root(expected_root)
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"),
                              object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("manifest NT invalido") from exc
    if (not isinstance(manifest, dict) or type(manifest.get("v")) is not int
            or manifest["v"] != 1 or not isinstance(manifest.get("root"), str)
            or ntpath.normcase(manifest["root"]) != canonical
            or not isinstance(manifest.get("entries"), dict)):
        raise ValueError("manifest nao pertence a raiz NT informada")
    if journal_raw and not journal_raw.endswith(b"\n"):
        raise ValueError("journal NT truncado")
    records = journal_raw.splitlines()
    if len(records) > MAX_RECORDS:
        raise ValueError("journal NT extenso")
    computed_ops = {}
    computed_ids = {}
    last_seq = 0
    for raw in records:
        try:
            item = json.loads(raw.decode("utf-8"),
                              object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("registro NT invalido") from exc
        if not isinstance(item, dict):
            raise ValueError("registro NT nao e objeto")
        if not {"seq", "op", "p"}.issubset(item):
            raise ValueError("registro NT sem campos obrigatorios")
        if set(item) - {"seq", "op", "p", "d", "src"}:
            raise ValueError("registro NT com campos desconhecidos")
        seq, kind, rel = item["seq"], item["op"], item["p"]
        directory = item.get("d", 0)
        if (type(seq) is not int or seq <= last_seq or
                type(directory) is not int or directory not in (0, 1)):
            raise ValueError("ordem ou flag NT invalido")
        last_seq = seq
        if not isinstance(rel, str):
            raise ValueError("caminho NT invalido")
        payload = b"" if kind == "W" else None
        try:
            _validate_plan([(kind, rel, payload)])
        except (TypeError, ValueError) as exc:
            raise ValueError("caminho/tipo de journal NT invalido") from exc
        if kind == "W":
            src = item.get("src")
            if (directory != 0 or not isinstance(src, str) or
                    not 1 <= len(src) <= 32 or not src.isascii() or
                    not src.isdigit()):
                raise ValueError("payload imutavel do journal NT exigido")
            computed_ids[rel] = src
        else:
            if "src" in item or (kind == "M" and directory != 1):
                raise ValueError("metadados de journal NT incoerentes")
            computed_ids.pop(rel, None)
        computed_ops[rel] = (seq, kind, directory)
    if (last_seq != expected_seq or computed_ops != expected_ops
            or computed_ids != expected_payload_ids):
        raise ValueError("estado do core difere do journal NT protegido")
    return [
        (rel.split("/"), kind, directory,
         ("payloads/" + computed_ids[rel]) if kind == "W" else None)
        for rel, (seq, kind, directory) in sorted(
            computed_ops.items(), key=lambda pair: pair[1][0])
    ]


def prepare_verified_journal_entries_experimental(
        root, overlay_root, store_directory,
        expected_ops, expected_payload_ids, expected_seq):
    """Read and reconcile an overlay journal pinned by enrolled NT identity."""
    _canonical_root(root)
    _canonical_root(overlay_root)
    expected = load_identity_from_store(overlay_root, store_directory)
    with open_trusted_root(overlay_root, read_control=True) as overlay:
        if directory_identity(overlay) != expected:
            raise OSError("identidade do overlay NT divergente")
        _assert_protected_acl(overlay)
        manifest = read_relative_file(
            overlay, "manifest.json", max_bytes=MAX_MANIFEST_BYTES,
            handle_guard=_assert_protected_acl)
        journal = read_relative_file(
            overlay, "journal.log", max_bytes=MAX_JOURNAL_BYTES,
            handle_guard=_assert_protected_acl)
    return _parse_pinned_metadata(
        manifest, journal, root, expected_ops, expected_payload_ids,
        expected_seq)

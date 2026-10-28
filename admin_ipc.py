#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Protocolo de administracao LOCAL do DeepFreezer (stdlib, Python 3.8+).

A camada de transporte DEVE fornecer o resultado de autenticacao do SO.
Nenhuma senha/credencial e enviada pela UI ou aceita neste protocolo.
"""
import json
import os
import socket
import struct
import threading
import uuid

from deepfreezer import DeepFreezer, DeepFreezeError

MAX_BYTES = 16384
ACTIONS = ("status", "freeze", "discard", "commit")
MUTATIONS = ("freeze", "discard", "commit")


class ProtocolError(ValueError):
    pass


def _reject_duplicate_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ProtocolError("chave JSON duplicada")
        obj[key] = value
    return obj


def decode_message(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ProtocolError("mensagem invalida ou maior que 16 KiB")
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeError, ValueError) as exc:
        raise ProtocolError("JSON invalido: %s" % exc)
    if not isinstance(obj, dict) or obj.get("v") != 1:
        raise ProtocolError("versao do protocolo nao suportada")
    allowed = {"v", "id", "action", "target", "confirm"}
    if set(obj) - allowed:
        raise ProtocolError("campos desconhecidos")
    try:
        uid = str(uuid.UUID(obj["id"]))
    except (TypeError, ValueError, KeyError, AttributeError):
        raise ProtocolError("id UUID invalido")
    if uid != obj["id"]:
        raise ProtocolError("id UUID nao canonico")
    if obj.get("action") not in ACTIONS:
        raise ProtocolError("acao nao permitida")
    return obj


def load_targets(config_path):
    with open(config_path, "r", encoding="utf-8-sig") as f:
        config = json.load(f, object_pairs_hook=_reject_duplicate_pairs)
    targets = config.get("targets") if isinstance(config, dict) else None
    if not isinstance(targets, list) or not targets or len(targets) > 256:
        raise ProtocolError("config: lista de alvos invalida")
    result = {}
    for entry in targets:
        if not isinstance(entry, dict) or not isinstance(entry.get("target"), str):
            raise ProtocolError("config: entrada de alvo invalida")
        name = os.path.abspath(os.path.expanduser(entry["target"]))
        if name in result or not name:
            raise ProtocolError("config: alvo repetido ou vazio")
        result[name] = {
            "target": name,
            "overlay": entry.get("overlay"),
            "verify": bool(entry.get("verify", False)),
        }
    return result


class Broker(object):
    """Handler desacoplado do transporte; auth do kernel em todo pedido."""

    def __init__(self, config_path, status_path, audit=None):
        self.config_path = config_path
        self.status_path = status_path
        self.audit = audit
        self._mutex = threading.RLock()

    def _audit(self, ident, obj, ok, message):
        if self.audit:
            self.audit("ipc peer=%s action=%s target=%s ok=%s info=%s" % (
                ident, obj.get("action"), obj.get("target"), ok, message))

    def process(self, raw, is_admin=False, identity="unknown"):
        obj = {"action": None, "target": None, "id": None}
        try:
            obj = decode_message(raw)
            if obj["action"] in MUTATIONS and not is_admin:
                raise PermissionError("permissao administrativa exigida")
            with self._mutex:
                targets = load_targets(self.config_path)
                if obj["action"] == "status":
                    # O resultado e a ultima verificacao, NAO status de OS-level.
                    # Arquivo de status e protegido no disco; o broker serve
                    # somente campos sem segredos para usuarios locais.
                    with open(self.status_path, "r", encoding="utf-8") as f:
                        status = json.load(f)
                    if status.get("protection_scope") != "application-level":
                        raise ProtocolError("escopo de protecao desconhecido")
                    result = {
                        "state": status.get("state", "error"),
                        "timestamp": status.get("last_enforcement_utc"),
                        "scope": "application-level",
                        "targets": [],
                    }
                    reported = {x["target"]: x for x in status.get("targets", [])
                                if isinstance(x, dict) and "target" in x}
                    for key, cfg in targets.items():
                        x = reported.get(key, {})
                        result["targets"].append({
                            "target": key, "overlay": cfg["overlay"] or key + ".dfreezer",
                            "state": x.get("state", "error"),
                            "error": x.get("error", ""),
                            "baseline_paths": x.get("baseline_paths", 0),
                        })
                else:
                    target = obj.get("target")
                    if not isinstance(target, str) or target not in targets:
                        raise PermissionError("alvo nao configurado")
                    if obj["action"] in ("discard", "commit"):
                        expected = "%s %s" % (obj["action"].upper(), target)
                        if obj.get("confirm") != expected:
                            raise ProtocolError("confirmacao explicita obrigatoria")
                    cfg = targets[target]
                    with DeepFreezer(target, overlay=cfg["overlay"],
                                     verify=cfg["verify"]) as df:
                        if obj["action"] == "freeze":
                            if not df.frozen:
                                df.freeze()
                        elif obj["action"] == "discard":
                            if not df.frozen:
                                raise DeepFreezeError("alvo nao congelado")
                            df.thaw(commit=False)
                        elif obj["action"] == "commit":
                            if not df.frozen:
                                raise DeepFreezeError("alvo nao congelado")
                            df.thaw(commit=True)
                        result = {"target": target, "frozen": df.frozen,
                                  "action": obj["action"], "scope": "application-level"}
            self._audit(identity, obj, True, "ok")
            return {"v": 1, "id": obj["id"], "ok": True, "result": result}
        except (ProtocolError, PermissionError, DeepFreezeError, OSError,
                TypeError, ValueError) as exc:
            self._audit(identity, obj, False, str(exc))
            return {"v": 1, "id": obj.get("id"), "ok": False,
                    "error": {"code": type(exc).__name__, "message": str(exc)}}


def wire_send(sock, data):
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ProtocolError("resposta muito grande")
    sock.sendall(struct.pack("!I", len(raw)) + raw)


def wire_receive(sock):
    def exact(size):
        buf = b""
        while len(buf) < size:
            part = sock.recv(size - len(buf))
            if not part:
                raise ConnectionError("conexao encerrada")
            buf += part
        return buf
    size = struct.unpack("!I", exact(4))[0]
    if size < 1 or size > MAX_BYTES:
        raise ProtocolError("tamanho da requisicao invalido")
    return exact(size)


def unix_peer_credentials(sock):
    # Linux: obtidos do kernel, nao fornecidos pelo cliente.
    if not hasattr(socket, "SO_PEERCRED"):
        raise RuntimeError("SO_PEERCRED indisponivel: IPC desabilitado")
    pid, uid, gid = struct.unpack(
        "3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    return pid, uid, gid


def serve_unix(broker, path, stop_event=None):
    """Unix socket local; status leitura comum, mutacoes SOMENTE uid=0."""
    if os.name == "nt":
        raise RuntimeError("usar named pipe no Windows")
    stop_event = stop_event or threading.Event()
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    if os.path.lexists(path):
        raise RuntimeError("socket ja existe; nao remover socket alheio")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(path)
        os.chmod(path, 0o666)  # autenticacao por SO_PEERCRED em cada comando
        server.listen(8)
        server.settimeout(0.5)
        while not stop_event.is_set():
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            with client:
                client.settimeout(5)
                try:
                    pid, uid, _gid = unix_peer_credentials(client)
                    request = wire_receive(client)
                    response = broker.process(request, is_admin=(uid == 0),
                                              identity="uid=%d pid=%d" % (uid, pid))
                    wire_send(client, response)
                except (OSError, ConnectionError, ProtocolError) as exc:
                    # Fail closed: nao reutiliza bytes de requisicao incompleta.
                    try:
                        wire_send(client, {"v": 1, "id": None, "ok": False,
                                          "error": {"code": "ProtocolError",
                                                    "message": str(exc)}})
                    except (OSError, ProtocolError):
                        pass
    finally:
        server.close()
        if os.path.exists(path) and stat_is_socket(path):
            os.unlink(path)


def stat_is_socket(path):
    import stat
    return stat.S_ISSOCK(os.lstat(path).st_mode)


def request_unix(path, action="status", target=None, confirm=None, timeout=5):
    obj = {"v": 1, "id": str(uuid.uuid4()), "action": action}
    if target is not None:
        obj["target"] = target
    if confirm is not None:
        obj["confirm"] = confirm
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(path)
        wire_send(conn, obj)
        raw = wire_receive(conn)
    response = decode_reply(raw)
    if response.get("id") != obj["id"]:
        raise ProtocolError("correlacao de resposta falhou")
    return response


def decode_reply(raw):
    response = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    if not isinstance(response, dict) or response.get("v") != 1:
        raise ProtocolError("resposta invalida")
    return response

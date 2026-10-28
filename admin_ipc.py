#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Protocolo de administracao LOCAL do DeepFreezer (stdlib, Python 3.8+).

A camada de transporte DEVE fornecer o resultado de autenticacao do SO.
Nenhuma senha/credencial e enviada pela UI ou aceita neste protocolo.
"""
import json
import os
import secrets
import socket
import struct
import threading
import time
import uuid

from deepfreezer import DeepFreezer, DeepFreezeError

MAX_BYTES = 16384
ACTIONS = ("status", "prepare", "freeze", "discard", "commit")
MUTATIONS = ("prepare", "freeze", "discard", "commit")


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
    allowed = {"v", "id", "action", "target", "confirm", "operation"}
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
        raw = entry["target"]
        if not raw.strip() or not os.path.isabs(raw):
            raise ProtocolError("config: alvo precisa ser caminho absoluto")
        name = os.path.abspath(os.path.expanduser(raw))
        if name in result:
            raise ProtocolError("config: alvo repetido ou vazio")
        result[name] = {
            "target": name,
            "overlay": entry.get("overlay"),
            "verify": bool(entry.get("verify", False)),
        }
    return result


def overlay_usage(path, file_limit=5000):
    """Limita o custo da contagem e nunca segue symlinks dos arquivos."""
    import stat
    if not os.path.isdir(path) or os.path.islink(path):
        return 0, False
    total, counted = 0, 0
    for root, dirs, filenames in os.walk(path, followlinks=False):
        # Arestas reparse ou symlink nao sao percorridas.
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in filenames:
            counted += 1
            if counted > file_limit:
                return total, True
            try:
                info = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total, False


class Broker(object):
    """Handler desacoplado do transporte; auth do kernel em todo pedido."""

    def __init__(self, config_path, status_path, audit=None):
        self.config_path = config_path
        self.status_path = status_path
        self.audit = audit
        self._mutex = threading.RLock()
        self._pending = {}  # nonce -> (peer, acao, alvo, expira no monotonic)

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
                        row = {
                            "target": key, "overlay": cfg["overlay"] or key + ".dfreezer",
                            "state": x.get("state", "error"),
                            "error": x.get("error", ""),
                            "baseline_paths": x.get("baseline_paths", 0),
                        }
                        # Snapshot atual apenas da API. Erro de lock ou
                        # manifesto nao e' silenciosamente healthy.
                        try:
                            with DeepFreezer(key, overlay=cfg["overlay"],
                                             lock_timeout=0.1) as df:
                                observed = df.status()
                            row["frozen"] = observed["frozen"]
                            row["pending_ops"] = observed["overlay_ops"]
                            row["pending_seq"] = observed["pending_seq"]
                            size, partial = overlay_usage(row["overlay"])
                            row["overlay_bytes"] = size
                            row["overlay_size_partial"] = partial
                        except (OSError, DeepFreezeError) as exc:
                            row["frozen"] = None
                            row["pending_ops"] = {}
                            row["overlay_bytes"] = None
                            row["overlay_size_partial"] = False
                            row["runtime_error"] = str(exc)
                        result["targets"].append(row)
                else:
                    target = obj.get("target")
                    if not isinstance(target, str) or target not in targets:
                        raise PermissionError("alvo nao configurado")
                    # Nonces de curta duracao, vinculados ao token do peer:
                    # nao ha replay de confirmacoes entre processos.
                    now = time.monotonic()
                    self._pending = {
                        tok: value for tok, value in self._pending.items()
                        if value[3] > now
                    }
                    if obj["action"] == "prepare":
                        operation = obj.get("operation")
                        if operation not in ("discard", "commit"):
                            raise ProtocolError("operacao de preparo invalida")
                        if len(self._pending) >= 128:
                            raise ProtocolError("muitas autorizacoes pendentes")
                        token = secrets.token_urlsafe(24)
                        self._pending[token] = (identity, operation, target, now + 30)
                        result = {"token": token, "operation": operation,
                                  "target": target, "expires_in": 30}
                        self._audit(identity, obj, True, "nonce criado")
                        return {"v": 1, "id": obj["id"], "ok": True, "result": result}
                    if obj["action"] in ("discard", "commit"):
                        token = obj.get("confirm")
                        if not isinstance(token, str):
                            raise ProtocolError("nonce de confirmacao ausente")
                        prepared = self._pending.pop(token, None)
                        if prepared != (identity, obj["action"], target, prepared[3] if prepared else None):
                            raise PermissionError("confirmacao expirada ou de outro peer")
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


def _validate_unix_socket_directory(directory):
    """Falha fechada se um pai do socket puder ser substituido por usuario comum.

    Permite /tmp com sticky bit, mas exige que o diretorio final pertença
    ao UID efetivo e nao permita escrita por grupo/outros. Rejeita links
    simbolicos em qualquer ancestral do caminho.
    """
    import stat
    if not os.path.isabs(directory):
        raise RuntimeError("diretorio do IPC deve ser absoluto")
    current = os.path.sep
    for component in os.path.normpath(directory).split(os.path.sep)[1:]:
        if not component:
            continue
        current = os.path.join(current, component)
        info = os.lstat(current)
        if not stat.S_ISDIR(info.st_mode):
            raise RuntimeError("ancestral do IPC nao e diretorio real: %s" % current)
        if info.st_mode & 0o022:
            # Sticky bit em /tmp protege entradas de usuarios distintos.
            if not (info.st_mode & stat.S_ISVTX):
                raise RuntimeError("diretorio ancestral gravavel por terceiros: %s" %
                                   current)
    info = os.lstat(directory)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise RuntimeError("diretorio do IPC exige proprietario do servico e modo seguro")


def serve_unix(broker, path, stop_event=None):
    """Unix socket local; status leitura comum, mutacoes SOMENTE uid=0."""
    if os.name == "nt":
        raise RuntimeError("usar named pipe no Windows")
    stop_event = stop_event or threading.Event()
    if not os.path.isabs(path):
        raise RuntimeError("caminho do socket IPC deve ser absoluto")
    directory = os.path.dirname(path)
    # Não seguir links preexistentes durante a criação: a validacao
    # posterior recusa ancestrais simbolicos ou gravaveis por terceiros.
    os.makedirs(directory, mode=0o755, exist_ok=True)
    _validate_unix_socket_directory(directory)
    if os.path.lexists(path):
        if not stat_is_socket(path) or os.lstat(path).st_uid != os.geteuid():
            raise RuntimeError("socket antigo inseguro ou de outro proprietario")
        # Restos de crash sao recuperados apenas dentro de runtime dir
        # controlado. Nunca apagar socket de servidor respondendo.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            try:
                probe.connect(path)
            except ConnectionRefusedError:
                os.unlink(path)
            else:
                raise RuntimeError("servidor IPC ja ativo")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bound_identity = None
    try:
        server.bind(path)
        # Nao remover socket de outro processo se o pathname for trocado.
        bound = os.lstat(path)
        bound_identity = (bound.st_dev, bound.st_ino)
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
        # Se o pathname tiver sido substituido, nao apagar a entrada nova.
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            pass
        else:
            import stat
            if (bound_identity is not None and stat.S_ISSOCK(info.st_mode)
                    and (info.st_dev, info.st_ino) == bound_identity):
                os.unlink(path)


def stat_is_socket(path):
    import stat
    return stat.S_ISSOCK(os.lstat(path).st_mode)


def request_unix(path, action="status", target=None, confirm=None,
                 operation=None, timeout=5):
    obj = {"v": 1, "id": str(uuid.uuid4()), "action": action}
    if target is not None:
        obj["target"] = target
    if confirm is not None:
        obj["confirm"] = confirm
    if operation is not None:
        obj["operation"] = operation
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

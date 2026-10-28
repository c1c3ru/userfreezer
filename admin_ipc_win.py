#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Named pipe local protegido por SDDL, Windows 7 / Python 3.8 / pywin32.

O serviço verifica o token de cada CLIENTE após ler a mensagem com
ImpersonateNamedPipeClient; verificar apenas o prompt da UI seria inseguro.
"""
import json
import uuid

PIPE_NAME = r"\\.\pipe\DeepFreezerAdmin"
MAX_BYTES = 16384


def _dependencies():
    import pywintypes
    import win32api
    import win32con
    import win32file
    import win32pipe
    import win32security
    return pywintypes, win32api, win32con, win32file, win32pipe, win32security


def _peer_identity(handle, deps):
    _, win32api, win32con, _file, win32pipe, sec = deps
    # Impersonation e' baseada no ULTIMO request lido da instancia pipe.
    # Se falhar, nao aceitar nem operacoes de leitura.
    sec.ImpersonateNamedPipeClient(handle)
    try:
        token = sec.OpenThreadToken(win32api.GetCurrentThread(),
                                    win32con.TOKEN_QUERY, True)
        try:
            sid = sec.GetTokenInformation(token, sec.TokenUser)[0]
            admin_sid = sec.CreateWellKnownSid(sec.WinBuiltinAdministratorsSid, None)
            return bool(sec.CheckTokenMembership(token, admin_sid)), sec.ConvertSidToStringSid(sid)
        finally:
            token.Close()
    finally:
        sec.RevertToSelf()


def serve_windows(broker, stop_event=None, log=None):
    from admin_ipc import decode_message
    deps = _dependencies()
    pywintypes, _api, _con, win32file, win32pipe, sec = deps
    # Configurado ANTES da criação: SYSTEM e admins GA, qualquer
    # usuario local pode ler status, mas SEM permissão administrativa.
    # O servidor aplica impersonation + CheckTokenMembership em cada pedido.
    sddl = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;WD)"
    attrs = sec.SECURITY_ATTRIBUTES()
    attrs.SECURITY_DESCRIPTOR = sec.ConvertStringSecurityDescriptorToSecurityDescriptor(
        sddl, sec.SDDL_REVISION_1)
    # Instancia inicial unica: o handle permanece aberto entre clientes,
    # impedindo sequestro do nome no intervalo entre duas conexoes.
    handle = win32pipe.CreateNamedPipe(
        PIPE_NAME,
        win32pipe.PIPE_ACCESS_DUPLEX | 0x00080000,  # FIRST_PIPE_INSTANCE
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE |
        win32pipe.PIPE_WAIT | 0x00000008,  # REJECT_REMOTE_CLIENTS
        1, MAX_BYTES, MAX_BYTES, 5000, attrs)
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                win32pipe.ConnectNamedPipe(handle, None)
            except pywintypes.error as exc:
                if exc.winerror != 535:  # ERROR_PIPE_CONNECTED
                    raise
            try:
                rc, raw = win32file.ReadFile(handle, MAX_BYTES + 1)
                if rc != 0 or len(raw) > MAX_BYTES:
                    raise ValueError("request invalido ou muito grande")
                is_admin, identity = _peer_identity(handle, deps)
                response = broker.process(raw, is_admin=is_admin, identity=identity)
            except Exception as exc:
                if log:
                    log.warning("ipc pipe rejeitado: %s", exc)
                response = {"v": 1, "id": None, "ok": False,
                            "error": {"code": "ProtocolError",
                                      "message": "requisicao rejeitada"}}
            encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
            try:
                if len(encoded) <= MAX_BYTES:
                    win32file.WriteFile(handle, encoded)
            except pywintypes.error as exc:
                # O peer pode fechar logo apos conectar (health-check)
                # ou ao receber erro. Isso NAO deve matar o servidor IPC.
                if log:
                    log.debug("cliente pipe desconectado: %s", exc)
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(handle)
                except pywintypes.error:
                    pass
    finally:
        win32file.CloseHandle(handle)


def request_windows(action="status", target=None, confirm=None, operation=None):
    from admin_ipc import decode_reply
    _pywintypes, _api, con, win32file, win32pipe, _sec = _dependencies()
    win32pipe.WaitNamedPipe(PIPE_NAME, 5000)
    handle = win32file.CreateFile(PIPE_NAME,
                                  con.GENERIC_READ | con.GENERIC_WRITE, 0,
                                  None, con.OPEN_EXISTING, 0, None)
    obj = {"v": 1, "id": str(uuid.uuid4()), "action": action}
    if target is not None:
        obj["target"] = target
    if confirm is not None:
        obj["confirm"] = confirm
    if operation is not None:
        obj["operation"] = operation
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("request muito grande")
    try:
        win32file.WriteFile(handle, raw)
        rc, data = win32file.ReadFile(handle, MAX_BYTES)
        if rc != 0:
            raise OSError("erro na resposta do IPC")
        reply = decode_reply(data)
        if reply.get("id") != obj["id"]:
            raise ValueError("ID da resposta incorreto")
        return reply
    finally:
        win32file.CloseHandle(handle)

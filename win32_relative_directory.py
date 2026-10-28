#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXPERIMENTAL: handle-relative directory traversal via NtCreateFile.

Windows 7+ / ctypes / no pywin32. Not integrated with commit.
The root must be a TRUSTED directory: this module does not yet
pin every ancestor above that root. It cannot provide a complete safe commit
or recursive deletion API and must never be marketed as #63 resolved.

Relative NtCreateFile(... RootDirectory=parent_handle) is used
instead of check-then-open by pathname for child directories.
"""
import contextlib
import ctypes
from ctypes import wintypes
import os

FILE_READ_ATTRIBUTES = 0x80
FILE_TRAVERSE = 0x20
FILE_ADD_FILE = 0x2
FILE_ADD_SUBDIRECTORY = 0x4
FILE_WRITE_DATA = 0x2
DELETE = 0x10000
SYNCHRONIZE = 0x100000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
FILE_SHARE_DELETE = 0x4
OPEN_EXISTING = 3
FILE_OPEN = 1
FILE_CREATE = 2
FILE_DISPOSITION_INFO_CLASS = 4
FILE_RENAME_INFORMATION_CLASS = 10
FILE_NON_DIRECTORY_FILE = 0x40
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_DIRECTORY_FILE = 0x1
FILE_SYNCHRONOUS_IO_NONALERT = 0x20
FILE_OPEN_REPARSE_POINT = 0x00200000
OBJ_CASE_INSENSITIVE = 0x40
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT),
                ("MaximumLength", wintypes.USHORT),
                ("Buffer", wintypes.LPWSTR)]


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Length", wintypes.ULONG),
                ("RootDirectory", wintypes.HANDLE),
                ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
                ("Attributes", wintypes.ULONG),
                ("SecurityDescriptor", wintypes.LPVOID),
                ("SecurityQualityOfService", wintypes.LPVOID)]


class _IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]


class _FILE_RENAME_INFORMATION(ctypes.Structure):
    _fields_ = [("ReplaceIfExists", wintypes.BOOL),
                ("RootDirectory", wintypes.HANDLE),
                ("FileNameLength", wintypes.ULONG),
                ("FileName", wintypes.WCHAR * 1)]


class _FILE_DISPOSITION_INFO(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOL)]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


def _dlls():
    if os.name != "nt":
        raise OSError("NtCreateFile relative so existe no Windows")
    kernel = ctypes.windll.kernel32
    nt = ctypes.windll.ntdll
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID,
                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                 wintypes.LPVOID]
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel.FlushFileBuffers.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    nt.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG,
        ctypes.POINTER(_OBJECT_ATTRIBUTES), ctypes.POINTER(_IO_STATUS_BLOCK),
        wintypes.LPVOID, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
        wintypes.ULONG, wintypes.LPVOID, wintypes.ULONG]
    nt.NtCreateFile.restype = wintypes.LONG
    nt.NtSetInformationFile.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_IO_STATUS_BLOCK),
        wintypes.LPVOID, wintypes.ULONG, ctypes.c_int]
    nt.NtSetInformationFile.restype = wintypes.LONG
    nt.RtlNtStatusToDosError.argtypes = [wintypes.LONG]
    nt.RtlNtStatusToDosError.restype = wintypes.ULONG
    return kernel, nt


def _validate_component(name):
    if (not isinstance(name, str) or not name or name in (".", "..")
            or any(c in name for c in "/\\:\x00")
            or name[-1] in (".", " ")):
        raise ValueError("componente relativo de diretorio inseguro")
    return name


def _check_directory(kernel, handle):
    data = _BY_HANDLE_FILE_INFORMATION()
    if not kernel.GetFileInformationByHandle(handle, ctypes.byref(data)):
        raise ctypes.WinError()
    if not data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY:
        raise OSError("handle nao representa diretorio")
    if data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError("reparse point nao permitido em componente")
    return (data.dwVolumeSerialNumber, data.nFileIndexHigh, data.nFileIndexLow)


@contextlib.contextmanager
def open_trusted_root(root):
    """Abre root absoluto. A identidade/ancestres devem ser confiaveis."""
    kernel, _ = _dlls()
    if not os.path.isabs(root):
        raise ValueError("raiz precisa ser absoluta")
    handle = kernel.CreateFileW(
        root, FILE_TRAVERSE | FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY |
        FILE_READ_ATTRIBUTES | SYNCHRONIZE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, None)
    if handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError()
    try:
        _check_directory(kernel, handle)
        yield handle
    finally:
        kernel.CloseHandle(handle)


@contextlib.contextmanager
def open_relative_directory(parent, name):
    """Abre componente no OBJETO de diretorio parent, nao em pathname."""
    _validate_component(name)
    kernel, nt = _dlls()
    name_buffer = ctypes.create_unicode_buffer(name)
    byte_length = len(name.encode("utf-16-le"))
    uni = _UNICODE_STRING(
        byte_length, byte_length, ctypes.cast(name_buffer, wintypes.LPWSTR))
    attrs = _OBJECT_ATTRIBUTES(
        ctypes.sizeof(_OBJECT_ATTRIBUTES), parent,
        ctypes.pointer(uni), OBJ_CASE_INSENSITIVE, None, None)
    io = _IO_STATUS_BLOCK()
    handle = wintypes.HANDLE()
    status = nt.NtCreateFile(
        ctypes.byref(handle),
        FILE_READ_ATTRIBUTES | FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY |
        FILE_TRAVERSE | SYNCHRONIZE,
        ctypes.byref(attrs), ctypes.byref(io), None, 0,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        FILE_OPEN,
        FILE_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT |
        FILE_SYNCHRONOUS_IO_NONALERT,
        None, 0)
    if status < 0:
        winerror = nt.RtlNtStatusToDosError(status)
        raise ctypes.WinError(winerror)
    try:
        _check_directory(kernel, handle)
        yield handle
    finally:
        kernel.CloseHandle(handle)


def directory_identity(handle):
    kernel, _ = _dlls()
    return _check_directory(kernel, handle)


def create_relative_file(parent, name, data):
    """EXPERIMENTAL: cria novo arquivo usando SOMENTE RootDirectory.

    Nao substitui arquivo existente (FILE_CREATE), nao usa pathname para
    abertura e rejeita reparse points. Sem rename/exclusao: NAO serve
    como backend de commit. Retorna numero de bytes gravados.
    """
    _validate_component(name)
    if not isinstance(data, bytes):
        raise TypeError("conteudo deve ser bytes")
    kernel, nt = _dlls()
    name_buffer = ctypes.create_unicode_buffer(name)
    count = len(name.encode("utf-16-le"))
    uni = _UNICODE_STRING(count, count, ctypes.cast(name_buffer, wintypes.LPWSTR))
    attrs = _OBJECT_ATTRIBUTES(
        ctypes.sizeof(_OBJECT_ATTRIBUTES), parent, ctypes.pointer(uni),
        OBJ_CASE_INSENSITIVE, None, None)
    io = _IO_STATUS_BLOCK()
    handle = wintypes.HANDLE()
    status = nt.NtCreateFile(
        ctypes.byref(handle),
        FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
        ctypes.byref(attrs), ctypes.byref(io), None, 0,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        FILE_CREATE,
        FILE_NON_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT |
        FILE_SYNCHRONOUS_IO_NONALERT,
        None, 0)
    if status < 0:
        raise ctypes.WinError(nt.RtlNtStatusToDosError(status))
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError()
        if info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT):
            raise OSError("arquivo reparse/diretorio nao permitido")
        position = 0
        while position < len(data):
            chunk = data[position:position + 1024 * 1024]
            buf = ctypes.create_string_buffer(chunk)
            written = wintypes.DWORD()
            if not kernel.WriteFile(handle, buf, len(chunk), ctypes.byref(written), None):
                raise ctypes.WinError()
            if written.value == 0:
                raise OSError("WriteFile sem progresso")
            position += written.value
        if not kernel.FlushFileBuffers(handle):
            raise ctypes.WinError()
        return position
    finally:
        kernel.CloseHandle(handle)


def create_relative_directory(parent, name):
    """EXPERIMENTAL: mkdir no objeto pai, jamais reconstruindo pathname.

    FILE_CREATE recusa se o nome ja existe: sem seguir links/junctions.
    Retorna identidade do novo diretorio, validada por handle.
    Nao integrada a _commit_windows ate operacoes restantes seguras.
    """
    _validate_component(name)
    kernel, nt = _dlls()
    name_buffer = ctypes.create_unicode_buffer(name)
    count = len(name.encode("utf-16-le"))
    uni = _UNICODE_STRING(count, count, ctypes.cast(name_buffer, wintypes.LPWSTR))
    attrs = _OBJECT_ATTRIBUTES(
        ctypes.sizeof(_OBJECT_ATTRIBUTES), parent, ctypes.pointer(uni),
        OBJ_CASE_INSENSITIVE, None, None)
    io = _IO_STATUS_BLOCK()
    handle = wintypes.HANDLE()
    status = nt.NtCreateFile(
        ctypes.byref(handle),
        FILE_READ_ATTRIBUTES | FILE_TRAVERSE | FILE_ADD_FILE |
        FILE_ADD_SUBDIRECTORY | SYNCHRONIZE,
        ctypes.byref(attrs), ctypes.byref(io), None, FILE_ATTRIBUTE_DIRECTORY,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        FILE_CREATE,
        FILE_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT |
        FILE_SYNCHRONOUS_IO_NONALERT,
        None, 0)
    if status < 0:
        raise ctypes.WinError(nt.RtlNtStatusToDosError(status))
    try:
        return _check_directory(kernel, handle)
    finally:
        kernel.CloseHandle(handle)


def delete_relative_file(parent, name):
    """EXPERIMENTAL: unlink por HANDLE do arquivo, nunca por caminho.

    Rejeita diretórios e reparse points, inclusive symlinks/junctions.
    FileDispositionInfo suportado no Windows 7; arquivo deve nao estar
    aberto com compartilhamento incompatível. Sem suporte a rmtree.
    """
    _validate_component(name)
    kernel, nt = _dlls()
    name_buffer = ctypes.create_unicode_buffer(name)
    count = len(name.encode("utf-16-le"))
    uni = _UNICODE_STRING(count, count, ctypes.cast(name_buffer, wintypes.LPWSTR))
    attrs = _OBJECT_ATTRIBUTES(
        ctypes.sizeof(_OBJECT_ATTRIBUTES), parent, ctypes.pointer(uni),
        OBJ_CASE_INSENSITIVE, None, None)
    io = _IO_STATUS_BLOCK()
    handle = wintypes.HANDLE()
    status = nt.NtCreateFile(
        ctypes.byref(handle),
        DELETE | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
        ctypes.byref(attrs), ctypes.byref(io), None, 0,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        FILE_OPEN,
        FILE_NON_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT |
        FILE_SYNCHRONOUS_IO_NONALERT,
        None, 0)
    if status < 0:
        raise ctypes.WinError(nt.RtlNtStatusToDosError(status))
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError()
        if info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY |
                                   FILE_ATTRIBUTE_REPARSE_POINT):
            raise OSError("delete recusado: diretorio ou reparse point")
        disposition = _FILE_DISPOSITION_INFO(True)
        if not kernel.SetFileInformationByHandle(
                handle, FILE_DISPOSITION_INFO_CLASS,
                ctypes.byref(disposition), ctypes.sizeof(disposition)):
            raise ctypes.WinError()
    finally:
        kernel.CloseHandle(handle)


def rename_relative_file(parent, source, destination, replace=False):
    """EXPERIMENTAL: rename atomico por handle e RootDirectory do pai.

    Nao segue reparse points na origem. O destino e resolvido pelo
    handle do pai, em vez de pathname, inclusive se uma junction
    substituir o caminho original. So arquivo regular; ainda nao
    implementa commit seguro, hardlinks/ACL/atomicidade entre operacoes.
    """
    _validate_component(source)
    _validate_component(destination)
    if source.casefold() == destination.casefold():
        raise ValueError("origem e destino identicos")
    kernel, nt = _dlls()
    name_buffer = ctypes.create_unicode_buffer(source)
    count = len(source.encode("utf-16-le"))
    uni = _UNICODE_STRING(count, count, ctypes.cast(name_buffer, wintypes.LPWSTR))
    attrs = _OBJECT_ATTRIBUTES(
        ctypes.sizeof(_OBJECT_ATTRIBUTES), parent, ctypes.pointer(uni),
        OBJ_CASE_INSENSITIVE, None, None)
    io = _IO_STATUS_BLOCK()
    handle = wintypes.HANDLE()
    status = nt.NtCreateFile(
        ctypes.byref(handle),
        DELETE | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
        ctypes.byref(attrs), ctypes.byref(io), None, 0,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        FILE_OPEN,
        FILE_NON_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT |
        FILE_SYNCHRONOUS_IO_NONALERT,
        None, 0)
    if status < 0:
        raise ctypes.WinError(nt.RtlNtStatusToDosError(status))
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError()
        if info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT |
                                   FILE_ATTRIBUTE_DIRECTORY):
            raise OSError("rename recusado: reparse point ou diretorio")
        encoded = destination.encode("utf-16-le")
        # A estrutura tem um WCHAR flexivel no final; a contagem de
        # FileNameLength e em bytes e dispensa terminador NUL.
        offset = _FILE_RENAME_INFORMATION.FileName.offset
        length = offset + len(encoded)
        buffer = ctypes.create_string_buffer(length + 2)
        details = ctypes.cast(buffer, ctypes.POINTER(_FILE_RENAME_INFORMATION))
        details.contents.ReplaceIfExists = bool(replace)
        details.contents.RootDirectory = parent
        details.contents.FileNameLength = len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + offset,
                       encoded, len(encoded))
        result = _IO_STATUS_BLOCK()
        status = nt.NtSetInformationFile(
            handle, ctypes.byref(result), buffer, length,
            FILE_RENAME_INFORMATION_CLASS)
        if status < 0:
            raise ctypes.WinError(nt.RtlNtStatusToDosError(status))
    finally:
        kernel.CloseHandle(handle)

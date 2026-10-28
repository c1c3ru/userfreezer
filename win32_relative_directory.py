#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXPERIMENTAL: handle-relative directory traversal via NtCreateFile.

Windows 7+ / ctypes / no pywin32. Not integrated with commit.
The root must be a TRUSTED directory: this module does not yet
pin every ancestor above that root. It cannot provide a safe write
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
SYNCHRONIZE = 0x100000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
FILE_SHARE_DELETE = 0x4
OPEN_EXISTING = 3
FILE_OPEN = 1
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
        root, FILE_TRAVERSE | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
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
        FILE_READ_ATTRIBUTES | FILE_TRAVERSE | SYNCHRONIZE,
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

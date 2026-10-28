#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bloqueio de ancestrais por HANDLE, Windows 7+ (stdlib ctypes).

CreateFileW(FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS)
abre cada diretorio sem seguir o ultimo componente; sem FILE_SHARE_DELETE,
o Windows impede rename/delete do diretorio enquanto o handle existir.
Isso fecha a janela check-then-use dos ANCESTRAIS do commit. Filhos que
surgem no intervalo sao verificados da mesma forma antes do uso.
"""
import contextlib
import ctypes
from ctypes import wintypes
import ntpath
import os
import stat

FILE_READ_ATTRIBUTES = 0x80
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


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


def _kernel():
    if os.name != "nt":
        raise RuntimeError("Win32 handles so estao disponiveis no Windows")
    k = ctypes.windll.kernel32
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                              wintypes.DWORD, wintypes.LPVOID,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.CreateFileW.restype = wintypes.HANDLE
    k.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)]
    k.GetFileInformationByHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


def _open_directory(path, kernel):
    handle = kernel.CreateFileW(
        path, FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        None)
    if handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError()
    info = _BY_HANDLE_FILE_INFORMATION()
    if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
        err = ctypes.WinError()
        kernel.CloseHandle(handle)
        raise err
    if not (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY):
        kernel.CloseHandle(handle)
        raise OSError("nao e diretorio: %s" % path)
    if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
        kernel.CloseHandle(handle)
        raise OSError("reparse point/junction proibido: %s" % path)
    return handle


@contextlib.contextmanager
def guarded_parent(root, parts, create=False):
    """Mantem abertos TODOS os ancestrais ate o fim da mutacao.

    O caller valida os componentes (sem '..', drive, ADS etc.) ANTES.
    Em Windows 7 NTFS, handles sem FILE_SHARE_DELETE impedem troca de
    diretorios por junction entre verificacao e escrita.
    """
    target = ntpath.abspath(root)
    drive, tail = ntpath.splitdrive(target)
    if not drive or not tail.startswith("\\"):
        raise OSError("alvo Windows absoluto exigido")
    rootdir = drive + "\\"
    base = [x for x in tail.split("\\") if x]
    names = base + list(parts[:-1])
    k = _kernel()
    handles = []
    current = rootdir
    try:
        handles.append(_open_directory(current, k))
        for i, item in enumerate(names):
            current = ntpath.join(current, item)
            if create and i >= len(base):
                try:
                    os.mkdir(current)
                except FileExistsError:
                    pass
            handles.append(_open_directory(current, k))
        yield current
    finally:
        for handle in reversed(handles):
            k.CloseHandle(handle)


def secure_rmtree(root, parts):
    """Exclusao recursiva sem seguir junctions e sem permitir troca de pais."""
    with guarded_parent(root, parts + ["_sentinel_"], create=False):
        path = ntpath.join(root, *parts)
        # O ultimo componente (path) esta protegido por HANDLE acima.
        with os.scandir(path) as it:
            children = [(ent.name, ent.is_dir(follow_symlinks=False))
                        for ent in it]
        for name, is_dir in children:
            full = ntpath.join(path, name)
            lst = os.lstat(full)
            attrs = getattr(lst, "st_file_attributes", 0)
            if stat.S_ISLNK(lst.st_mode) or attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("reparse point em remocao recursiva: %s" % full)
            if is_dir:
                secure_rmtree(root, parts + [name])
            else:
                os.unlink(full)
    os.rmdir(path)

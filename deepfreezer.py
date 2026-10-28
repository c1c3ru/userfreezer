#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deepfreezer — Deep Freezer cross-platform (Windows/Linux), Python 3.6+, só stdlib.

Modelo (equivalente ao Deep Freeze comercial):
  freeze() : snapshot da arvore T (manifest com tamanho/mtime/hash opcional).
             Depois disso, todo cambio passa pela camada de overlay. A arvore
             original fica intocada em disco.
  write/read/rm/mkdirs/list : operam na view congelada (baseline + overlay).
  thaw()             : semantica de "desligar" — overlay descartado, T volta
                       exatamente ao estado congelado.
  thaw(commit=True)  : merge do overlay em T e descarte.

Layout do overlay (default: <T>.dfreezer):
  manifest.json, journal.log, payloads/<id>, md/<rel>, del/<rel>
  <T>.dfreezer.lock (trava externa persistente)
  <T>.dfreezer.discarding (marcador de recuperacao, transitorio)
  files/<rel> (payload legado de overlays antigos)

Crash-safety: cada op = (1) payload escrito atomicamente (tmp+rename),
(2) linha de journal + fsync. Journal e' a fonte da verdade; payloads
orfaos (crash entre as etapas) sao ignorados na reabertura.
"""
import argparse
import hashlib
import json
import ntpath
import os
import secrets
import shutil
import stat
import sys
import time

DF_VERSION = 1
KIND_SUBDIR = {"W": "files", "M": "md", "D": "del"}


def _long(p):
    """Prefixo \\\\?\\" para caminhos longos no Windows."""
    if os.name == "nt" and len(p) > 170 and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + p
    return p


class DeepFreezeError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Lock de instancia unica (travamento pelo SO; liberacao apos crash)
# ---------------------------------------------------------------------------
class _Lock(object):
    """Trava um byte do arquivo LOCK; o kernel solta a trava se o processo cair.

    Nao remove o arquivo no release: apagar um arquivo de lock cria uma
    corrida entre processos que abriram inodes/handles diferentes. O lock
    fica como IRMAO do overlay e permanece apos thaw().
    Suporta Python 3.8/Windows 7 (msvcrt) e Linux (fcntl), sem dependencias.
    """

    def __init__(self, path, timeout=10.0):
        self.path = _long(path)
        self.timeout = timeout
        self.fd = None

    @staticmethod
    def _os_lock(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _os_unlock(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)

    def acquire(self):
        if self.fd is not None:
            raise DeepFreezeError("lock ja adquirido nesta instancia")
        # O arquivo continua existindo entre sessoes: sua idade nao define
        # se a trava esta ocupada. Nao trunca antes de adquirir o lock.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b" ")
            start = time.monotonic()
            while True:
                try:
                    self._os_lock(fd)
                    break
                except OSError as exc:
                    if time.monotonic() - start >= self.timeout:
                        raise DeepFreezeError(
                            "overlay bloqueado por outra instancia (timeout)") from exc
                    time.sleep(0.1)
            self.fd = fd
            payload = json.dumps({"pid": os.getpid(), "ts": time.time()}).encode("utf-8")
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, payload)
            os.ftruncate(fd, len(payload))
            os.fsync(fd)
        except BaseException:
            if self.fd == fd:
                self.fd = None
            os.close(fd)
            raise

    def release(self):
        if self.fd is None:
            return
        fd = self.fd
        self.fd = None
        try:
            self._os_unlock(fd)
        finally:
            os.close(fd)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Nucleo
# ---------------------------------------------------------------------------
class DeepFreezer(object):
    """df = DeepFreezer(alvo); df.freeze(); df.write('a.txt', b'oi'); df.thaw()"""

    def __init__(self, target, overlay=None, verify=False, lock_timeout=10.0):
        self.target = os.path.abspath(os.path.expanduser(target))
        if not os.path.isdir(self.target):
            raise DeepFreezeError("alvo nao existe ou nao e diretorio: %s" % self.target)
        if overlay is None:
            overlay = self.target.rstrip("/\\") + ".dfreezer"
        self.overlay = os.path.abspath(overlay)
        if self.overlay == self.target or self.overlay.startswith(self.target + os.sep):
            raise DeepFreezeError("overlay nao pode ficar dentro do alvo")
        self.verify_hashes = verify
        self.frozen = False
        self.manifest = None
        self.ops = {}      # rel -> (seq, kind 'W'|'M'|'D', d: 0=arquivo 1=dir)
        self._write_payloads = {}  # rel -> ID imutavel de escrita confirmada
        self._seq = 0
        # Trava FORA do overlay: permite deletar seu conteudo com a trava
        # ainda adquirida, inclusive no Windows 7 (arquivo aberto no NTFS
        # nao pode ser apagado como parte do rmtree).
        self._lock = _Lock(self.overlay + ".lock", lock_timeout)
        self._discard_marker = self.overlay + ".discarding"
        self._discarding = False
        self._open()

    # -- ciclo de vida ------------------------------------------------------
    def _open(self):
        # A trava protege freeze(), thaw() E a remocao. Nao se admite
        # outra instancia enquanto um overlay esta em descarte.
        parent = os.path.dirname(self.overlay)
        os.makedirs(parent, exist_ok=True)
        self._lock.acquire()
        try:
            if os.path.isfile(self._discard_marker):
                # Crash durante rmtree: a marca fica fora do overlay e
                # sobrevive mesmo se manifest/LOCK foram removidos.
                self._finish_discard()
            if os.path.isdir(self.overlay):
                # Compatibilidade: se um processo de versao antiga ainda
                # segura overlay/LOCK, recusar abrir. Nao executar duas
                # versoes simultaneamente (elas usam travas diferentes).
                legacy = os.path.join(self.overlay, "LOCK")
                if os.path.isfile(legacy):
                    legacy_lock = _Lock(legacy, self._lock.timeout)
                    try:
                        legacy_lock.acquire()
                    finally:
                        legacy_lock.release()
                man = self._jread(os.path.join(self.overlay, "manifest.json"))
                if man is None:
                    raise DeepFreezeError("overlay existe sem manifest (corrompido?)")
                self.manifest = man
                self.frozen = True
                self._load_journal()
            elif os.path.lexists(self.overlay):
                raise DeepFreezeError("caminho do overlay ja existe (nao eh dir)")
        except BaseException:
            self._lock.release()
            raise

    def _finish_discard(self):
        # Chamado EXCLUSIVAMENTE com a trava externa em posse desta instancia.
        try:
            if os.path.isdir(self.overlay):
                shutil.rmtree(self.overlay)
            elif os.path.lexists(self.overlay):
                raise DeepFreezeError("overlay nao e diretorio: %s" % self.overlay)
            if os.path.lexists(self.overlay):
                raise DeepFreezeError("overlay nao foi completamente descartado")
            if os.path.exists(self._discard_marker):
                os.unlink(self._discard_marker)
        except OSError as exc:
            raise DeepFreezeError(
                "falha ao descartar overlay %s: %s (sera recuperado na "
                "proxima abertura)" % (self.overlay, exc)) from exc

    def _clear_frozen_state(self):
        self.frozen = False
        self.manifest = None
        self.ops = {}
        self._write_payloads = {}
        self._seq = 0
        self._discarding = False

    def _load_journal(self):
        best_seq = 0
        path = os.path.join(self.overlay, "journal.log")
        if os.path.isfile(path):
            with open(path, "rb") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line.decode("utf-8"))
                    except ValueError:
                        break  # linha truncada no fim (crash): ignora o resto
                    best_seq = max(best_seq, int(rec.get("seq", 0)))
                    key = rec.get("p")
                    if not key:
                        continue
                    cur = self.ops.get(key)
                    if cur is None or int(rec.get("seq", 0)) >= cur[0]:
                        kind = rec["op"]
                        self.ops[key] = (int(rec["seq"]), kind, int(rec.get("d", 0)))
                        # Journals anteriores nao possuem campo "src": continuar
                        # lendo payloads legados em files/<rel>.
                        src = rec.get("src")
                        if kind == "W" and src is not None:
                            if not (isinstance(src, str) and src.isdigit()
                                    and len(src) <= 32):
                                raise DeepFreezeError("ID de payload invalido no journal")
                            self._write_payloads[key] = src
                        else:
                            self._write_payloads.pop(key, None)
        # valida payloads confirmados: ignorar registro sem conteudo.
        dead = []
        for rel, (s, k, d) in self.ops.items():
            if k not in KIND_SUBDIR:
                raise DeepFreezeError("operacao invalida no journal: %r" % k)
            p = self._payload_path(rel) if k == "W" else os.path.join(
                self.overlay, KIND_SUBDIR[k], *rel.split("/"))
            if not os.path.isfile(p):
                dead.append(rel)
        for rel in dead:
            self.ops.pop(rel)
            self._write_payloads.pop(rel, None)
        self._seq = best_seq

    def freeze(self):
        if self.frozen:
            raise DeepFreezeError("ja esta congelado")
        entries, hashes = {}, {}
        t0 = time.time()
        for dirpath, dirnames, filenames in os.walk(self.target, followlinks=False):
            rel_d = os.path.relpath(dirpath, self.target).replace(os.sep, "/")
            if rel_d != ".":
                entries[rel_d] = {"t": "d"}
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                rel = fn if rel_d == "." else (rel_d + "/" + fn)
                lst = os.lstat(p)
                typ = "l" if os.path.islink(p) else "f"
                ent = {"t": typ, "size": lst.st_size, "mtime": lst.st_mtime_ns}
                if self.verify_hashes:
                    ent["sha256"] = self._sha256(p)
                    hashes[rel] = ent["sha256"]
                entries[rel] = ent
        if self._lock.fd is None or self._discarding:
            raise DeepFreezeError("instancia fechada ou descarte pendente")
        os.makedirs(self.overlay, exist_ok=True)
        man = {"v": DF_VERSION, "root": self.target,
               "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "entries": entries, "hashes": hashes}
        self._jwrite(os.path.join(self.overlay, "manifest.json"),
                     json.dumps(man).encode())
        open(os.path.join(self.overlay, "journal.log"), "wb").close()
        self.manifest = man
        self.frozen = True
        self.ops = {}
        self._write_payloads = {}
        self._seq = 0
        return {"seconds": round(time.time() - t0, 3), "paths": len(entries)}

    def thaw(self, commit=False):
        if self._lock.fd is None:
            raise DeepFreezeError("instancia fechada")
        if self._discarding:
            # Permite repetir a limpeza depois de uma falha de I/O.
            self._finish_discard()
            self._clear_frozen_state()
            return
        if not self.frozen:
            raise DeepFreezeError("nada congelado para descongelar")
        if commit:
            self._apply_commit()
        # Escreve a marca de descarte em arquivo IRMAO antes de iniciar
        # o rmtree. A marca persiste se o processo morrer no meio.
        # Na proxima abertura, _open() conclui a limpeza antes de aceitar
        # novas operacoes. Nao apagar a trava externa aqui: ela evita
        # reabertura enquanto o rmtree esta em andamento.
        self._jwrite(self._discard_marker, b'{"state":"discarding"}')
        self._discarding = True
        self._finish_discard()
        self._clear_frozen_state()

    def close(self):
        self._lock.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _commit_parts(self, rel):
        """Rejeita caminhos ambiguos e rotas que podem sair do alvo."""
        if not isinstance(rel, str) or not rel or "\x00" in rel:
            raise DeepFreezeError("caminho de commit invalido")
        path = rel.replace("\\", "/")
        if path.startswith("/") or ntpath.splitdrive(path)[0]:
            raise DeepFreezeError("caminho absoluto nao permitido no commit")
        parts = path.split("/")
        if any(p in ("", ".", "..") for p in parts):
            raise DeepFreezeError("componente de caminho invalido no commit")
        if os.name == "nt":
            for part in parts:
                # ADS, nomes especiais e aliases (pontos/espacos finais).
                name = part.split(".")[0].upper()
                reserved = ("CON", "PRN", "AUX", "NUL",
                            "COM1", "COM2", "COM3", "COM4", "COM5",
                            "COM6", "COM7", "COM8", "COM9",
                            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5",
                            "LPT6", "LPT7", "LPT8", "LPT9")
                if (":" in part or part[-1] in (" ", ".")
                        or name in reserved):
                    raise DeepFreezeError("nome de arquivo inseguro no Windows: %r" % part)
        return parts

    @staticmethod
    def _is_reparse(path):
        """Windows 7/Python 3.8: detecta junctions e outros reparse points."""
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return False
        attrs = getattr(info, "st_file_attributes", 0)
        return (stat.S_ISLNK(info.st_mode) or
                bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))

    def _check_commit_path(self, parts):
        # Preflight de toda a cadeia. Os caminhos sao revalidados antes de
        # cada operacao. Em POSIX as mutacoes usam dir_fd + O_NOFOLLOW.
        if self._is_reparse(self.target):
            raise DeepFreezeError("alvo do commit e link/reparse point")
        current = self.target
        for part in parts:
            current = os.path.join(current, part)
            if self._is_reparse(current):
                raise DeepFreezeError("link/reparse point nao permitido: %s" % current)
        final = os.path.abspath(current)
        root = os.path.abspath(self.target)
        try:
            inside = os.path.commonpath((os.path.normcase(root),
                                         os.path.normcase(final))) == os.path.normcase(root)
        except ValueError:
            inside = False
        if not inside:
            raise DeepFreezeError("caminho fora do alvo")
        return _long(final)

    def _commit_parent_fd(self, parts, create=False):
        """Abre diretórios relativos ao FD raiz sem seguir links (POSIX)."""
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.target, flags)
        try:
            for part in parts[:-1]:
                try:
                    child = os.open(part, flags, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, dir_fd=fd)
                    child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _remove_tree_fd(fd):
        """Apaga filhos via dir_fd, sem seguir symlink durante a travessia."""
        for entry in os.scandir(fd):
            if entry.is_dir(follow_symlinks=False):
                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY |
                                os.O_NOFOLLOW, dir_fd=fd)
                try:
                    DeepFreezer._remove_tree_fd(child)
                finally:
                    os.close(child)
                os.rmdir(entry.name, dir_fd=fd)
            else:
                os.unlink(entry.name, dir_fd=fd)

    def _commit_posix(self, parts, kind, directory, src=None):
        try:
            parent = self._commit_parent_fd(parts, create=kind in ("W", "M"))
        except FileNotFoundError:
            if kind == "D":
                return
            raise
        try:
            name = parts[-1]
            # Nunca operar em link existente (incluindo symlink quebrado).
            self._check_commit_path(parts)
            if kind == "W":
                tmp = ".deepfreezer-%s.tmp" % secrets.token_hex(12)
                fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                             0o600, dir_fd=parent)
                try:
                    with os.fdopen(fd, "wb") as out, open(src, "rb") as fin:
                        shutil.copyfileobj(fin, out)
                        out.flush()
                        os.fsync(out.fileno())
                    # replace() troca o link em si, nunca segue o destino.
                    self._check_commit_path(parts)
                    os.replace(tmp, name, src_dir_fd=parent, dst_dir_fd=parent)
                finally:
                    try:
                        os.unlink(tmp, dir_fd=parent)
                    except FileNotFoundError:
                        pass
            elif kind == "M":
                try:
                    os.mkdir(name, dir_fd=parent)
                except FileExistsError:
                    self._check_commit_path(parts)
                    if not os.path.isdir(os.path.join(self.target, *parts)):
                        raise
            elif kind == "D":
                try:
                    if directory:
                        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY |
                                     os.O_NOFOLLOW, dir_fd=parent)
                        try:
                            self._remove_tree_fd(fd)
                        finally:
                            os.close(fd)
                        os.rmdir(name, dir_fd=parent)
                    else:
                        os.unlink(name, dir_fd=parent)
                except FileNotFoundError:
                    pass
        finally:
            os.close(parent)

    def _commit_windows(self, parts, kind, directory, src=None):
        # Compatível com Win7/3.8, sem sintaxe de PowerShell moderno.
        # Revalidação de todos os componentes. Para mitigar TOCTOU,
        # escreve primeiro em temporário e faz replace do nome final.
        dst = self._check_commit_path(parts)
        if kind == "W":
            parent = os.path.dirname(dst)
            os.makedirs(parent, exist_ok=True)
            self._check_commit_path(parts)
            tmp = os.path.join(parent, ".deepfreezer-%s.tmp" % secrets.token_hex(12))
            try:
                with open(src, "rb") as fin, open(tmp, "xb") as out:
                    shutil.copyfileobj(fin, out)
                    out.flush()
                    os.fsync(out.fileno())
                self._check_commit_path(parts)
                os.replace(tmp, dst)
            finally:
                if os.path.lexists(tmp):
                    os.unlink(tmp)
        elif kind == "M":
            os.makedirs(dst, exist_ok=True)
            self._check_commit_path(parts)
        elif kind == "D":
            if directory:
                if os.path.isdir(dst):
                    shutil.rmtree(dst)  # sem ignore_errors; Win7 nao segue junction
            elif os.path.lexists(dst):
                os.unlink(dst)

    def _apply_commit(self):
        ordered = sorted(self.ops.items(), key=lambda kv: kv[1][0])
        prepared = []
        for rel, (seq, kind, directory) in ordered:
            if kind not in KIND_SUBDIR:
                raise DeepFreezeError("operacao invalida no commit")
            parts = self._commit_parts(rel)
            self._check_commit_path(parts)
            src = self._payload_path(rel) if kind == "W" else None
            prepared.append((parts, kind, directory, src))
        for parts, kind, directory, src in prepared:
            self._check_commit_path(parts)
            if os.name == "nt":
                self._commit_windows(parts, kind, directory, src)
            else:
                self._commit_posix(parts, kind, directory, src)

    # -- helpers ------------------------------------------------------------
    def _require_frozen(self):
        if self._discarding:
            raise DeepFreezeError("overlay em descarte pendente; conclua thaw()")
        if not self.frozen or self._lock.fd is None:
            raise DeepFreezeError("chame freeze() antes")

    @staticmethod
    def _sha256(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _jread(p):
        try:
            with open(p, "rb") as f:
                return json.loads(f.read())
        except (OSError, ValueError):
            return None

    def _jwrite(self, p, data):
        tmp = p + ".tmp%d" % os.getpid()
        with open(_long(tmp), "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)

    def _norm(self, rel):
        rel = (rel or "").replace("\\", "/").strip().lstrip("/")
        if not rel:
            return []
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if ".." in parts or rel in ("/", "\\"):
            raise DeepFreezeError("caminho relativo invalido: %r" % rel)
        return parts

    def _payload_path(self, rel):
        payload_id = self._write_payloads.get(rel)
        if payload_id is not None:
            return os.path.join(self.overlay, "payloads", payload_id)
        return os.path.join(self.overlay, "files", *rel.split("/"))

    def _put_payload(self, kind, rel, data=b"", payload_id=None):
        if payload_id is not None:
            if kind != "W":
                raise DeepFreezeError("somente escrita usa payload versionado")
            dst = os.path.join(self.overlay, "payloads", payload_id)
        else:
            dst = os.path.join(self.overlay, KIND_SUBDIR[kind], *rel.split("/"))
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        tmp = dst + ".tmp%d" % os.getpid()
        with open(_long(tmp), "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dst)
        # Assegura persistencia do nome do payload antes do journal
        # nos sistemas POSIX que aceitam fsync em diretorios.
        if os.name != "nt":
            dfd = os.open(os.path.dirname(dst), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)

    def _journal(self, op, rel, d=0, payload_id=None):
        self._seq += 1
        rec = {"seq": self._seq, "op": op, "p": rel, "d": d}
        if payload_id is not None:
            rec["src"] = payload_id
        line = json.dumps(rec) + "\n"
        jp = os.path.join(self.overlay, "journal.log")
        with open(_long(jp), "ab") as f:
            f.write(line.encode())
            f.flush()
            os.fsync(f.fileno())

    def _entry_at_freeze(self, rel):
        """metadado do caminho no momento do freeze (None se nao existia)"""
        return (self.manifest or {}).get("entries", {}).get(rel)

    # -- resolucao baseline/overlay ------------------------------------------
    def _classify(self, parts):
        """Resolve a view: ultima operacao sobre o caminho/ancestrais,
        seguida de descendentes que podem recriar diretorios implicitos.

        Uma exclusao de pai invalida operacoes anteriores nos filhos.
        Uma escrita posterior em filho recria o pai virtualmente.
        """
        if not parts:
            return "BASE"
        full = "/".join(parts)
        # Operacao mais recente que cobre diretamente este caminho.
        covering = None
        covering_path = None
        for i in range(1, len(parts) + 1):
            key = "/".join(parts[:i])
            rec = self.ops.get(key)
            if rec is not None and (covering is None or rec[0] > covering[0]):
                covering, covering_path = rec, key

        anchor_seq = covering[0] if covering is not None else 0
        # Existem filhos escritos/criados APOS a ultima operacao neste
        # caminho/ancestral? Ignora descendentes invalidados por pai mais
        # recente (inclusive D e W).
        prefix = full + "/"
        has_live_child = False
        for child, (seq, kind, _is_dir) in self.ops.items():
            if not child.startswith(prefix) or kind == "D" or seq <= anchor_seq:
                continue
            segments = child.split("/")
            shadowed = False
            for i in range(1, len(segments)):
                parent_key = "/".join(segments[:i])
                parent_op = self.ops.get(parent_key)
                if parent_op is not None and parent_op[0] > seq:
                    shadowed = True
                    break
            if not shadowed:
                has_live_child = True
                break

        if covering is None:
            return "IMPLICIT_DIR" if has_live_child else "BASE"
        if covering_path == full:
            kind = covering[1]
            if kind == "D":
                return "IMPLICIT_DIR" if has_live_child else "DELETED"
            if kind == "M":
                return "M_DIR"
            return "IMPLICIT_DIR" if has_live_child else "NEW"
        return "IMPLICIT_DIR" if has_live_child else "GONE"

    # -- API ------------------------------------------------------------------
    def write(self, rel, data):
        self._require_frozen()
        parts = self._norm(rel)
        if not parts:
            raise DeepFreezeError("caminho relativo invalido: %r" % rel)
        key = "/".join(parts)
        # Payload por operacao: uma escrita ainda nao confirmada nao pode
        # sobrescrever o payload da ultima escrita confirmada (issue #46).
        payload_id = "%016d" % (self._seq + 1)
        self._put_payload("W", key, data if isinstance(data, (bytes, bytearray))
                          else str(data).encode(), payload_id=payload_id)
        self._journal("W", key, payload_id=payload_id)
        self.ops[key] = (self._seq, "W", 0)
        self._write_payloads[key] = payload_id

    def read(self, rel):
        self._require_frozen()
        parts = self._norm(rel)
        c = self._classify(parts)
        key = "/".join(parts)
        if c == "NEW":
            with open(self._payload_path(key), "rb") as f:
                return f.read()
        if c == "BASE":
            p = _long(os.path.join(self.target, *parts))
            if not os.path.isfile(p):
                raise FileNotFoundError(rel)
            with open(p, "rb") as f:
                return f.read()
        raise FileNotFoundError(rel)

    def mkdirs(self, rel):
        self._require_frozen()
        parts = self._norm(rel)
        c = self._classify(parts)
        key = "/".join(parts)
        if c in ("M_DIR", "IMPLICIT_DIR"):
            return
        if c == "BASE":
            if os.path.isdir(os.path.join(self.target, *parts)):
                return
        self._put_payload("M", key)
        self._journal("M", key, d=1)
        self.ops[key] = (self._seq, "M", 1)

    def remove(self, rel):
        self._require_frozen()
        parts = self._norm(rel)
        if not parts:
            raise DeepFreezeError("nao se remove a raiz")
        key = "/".join(parts)
        is_dir = self.is_dir(rel)
        self._put_payload("D", key)
        self._journal("D", key, d=1 if is_dir else 0)
        self.ops[key] = (self._seq, "D", 1 if is_dir else 0)

    def exists(self, rel):
        self._require_frozen()
        parts = self._norm(rel)
        c = self._classify(parts)
        if c in ("NEW", "M_DIR", "IMPLICIT_DIR"):
            return True
        if c in ("DELETED", "GONE"):
            return False
        return os.path.exists(_long(os.path.join(self.target, *parts)))

    def is_dir(self, rel):
        self._require_frozen()
        parts = self._norm(rel)
        c = self._classify(parts)
        if c in ("M_DIR", "IMPLICIT_DIR"):
            return True
        if c in ("NEW", "DELETED", "GONE"):
            return False
        return os.path.isdir(_long(os.path.join(self.target, *parts)))

    def size(self, rel):
        self._require_frozen()
        parts = self._norm(rel)
        c = self._classify(parts)
        if c == "NEW":
            return os.path.getsize(self._payload_path("/".join(parts)))
        if c in ("DELETED", "GONE"):
            raise FileNotFoundError(rel)
        if c in ("M_DIR", "IMPLICIT_DIR"):
            raise IsADirectoryError(rel)
        return os.stat(_long(os.path.join(self.target, *parts))).st_size

    def iterdir(self, rel=""):
        self._require_frozen()
        parts = self._norm(rel)
        c = self._classify(parts)
        if c == "NEW":
            raise DeepFreezeError("nao e diretorio: %r" % rel)
        if c in ("DELETED", "GONE"):
            raise FileNotFoundError(rel)
        prefix = ("/".join(parts) + "/") if parts else ""
        names = set()
        if c == "BASE":
            bp = _long(os.path.join(self.target, *parts)) if parts else _long(self.target)
            if not os.path.isdir(bp):
                raise FileNotFoundError(rel)
            with os.scandir(bp) as it:
                for e in it:
                    names.add(e.name)
        lp = len(prefix)
        for k in self.ops:
            if not k.startswith(prefix):
                continue
            rest = k[lp:]
            seg, _, deeper = rest.partition("/")
            if not deeper:
                names.add(seg)
            elif (prefix + seg) not in self.ops:
                names.add(seg)  # diretorio implicito
        out = []
        for nm in sorted(names):
            if self._classify(parts + [nm]) not in ("GONE", "DELETED"):
                out.append(nm)
        return out

    def diff(self):
        added, modified, deleted = [], [], []
        for rel in sorted(self.ops):
            s, k, d = self.ops[rel]
            base = self._entry_at_freeze(rel)
            if k == "W":
                (modified if base else added).append(rel)
            elif k == "M":
                if not base:
                    added.append(rel + "/")
            elif k == "D":
                if base:
                    deleted.append(rel + ("/" if d == 1 else ""))
        return {"added": added, "modified": modified, "deleted": deleted}

    def status(self):
        man = self.manifest or {}
        counts = {"W": 0, "M": 0, "D": 0}
        for _, k, _ in self.ops.values():
            counts[k] += 1
        return {
            "frozen": self.frozen,
            "target": self.target,
            "overlay": self.overlay,
            "frozen_at": man.get("frozen_at"),
            "baseline_paths": len(man.get("entries", {})),
            "overlay_ops": counts,
            "pending_seq": self._seq,
        }

    def verify(self):
        """revalida baseline contra hashes registrados no freeze (--verify)"""
        bad = []
        for rel, h in sorted((self.manifest or {}).get("hashes", {}).items()):
            p = _long(os.path.join(self.target, *rel.split("/")))
            if self._classify(rel.split("/")) != "BASE":
                continue
            if not os.path.isfile(p) or self._sha256(p) != h:
                bad.append(rel)
        return bad

    # -- conveniencia ---------------------------------------------------------
    def freeze_status(self):
        return self.frozen


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="deepfreezer",
        description="Deep Freezer cross-platform (Python 3.6+, stdlib)")
    sub = ap.add_subparsers(dest="cmd")

    def add_common(p):
        p.add_argument("--overlay", help="dir do overlay (default: <alvo>.dfreezer)")
        p.add_argument("--lock-timeout", type=float, default=10.0)

    p = sub.add_parser("freeze", help="congela a arvore")
    p.add_argument("target")
    p.add_argument("--verify", action="store_true",
                   help="registra sha256 de cada arquivo (mais lento)")
    add_common(p)

    p = sub.add_parser("thaw", help="descongelar (descarta cambios) ou --commit")
    p.add_argument("target")
    p.add_argument("--commit", action="store_true", help="merge do overlay no alvo")
    add_common(p)

    p = sub.add_parser("status"); p.add_argument("target"); add_common(p)
    p = sub.add_parser("list"); p.add_argument("target"); p.add_argument("path", nargs="?")
    add_common(p)
    p = sub.add_parser("cat"); p.add_argument("target"); p.add_argument("path")
    add_common(p)
    p = sub.add_parser("write"); p.add_argument("target"); p.add_argument("path")
    p.add_argument("src", nargs="?", default="-", help="arquivo ou '-' (stdin)")
    add_common(p)
    p = sub.add_parser("rm"); p.add_argument("target"); p.add_argument("path")
    add_common(p)
    p = sub.add_parser("diff"); p.add_argument("target"); add_common(p)

    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2

    def open_df(target, verify=False):
        return DeepFreezer(target, overlay=a.overlay, verify=verify,
                           lock_timeout=a.lock_timeout)

    try:
        if a.cmd == "freeze":
            with open_df(a.target, verify=a.verify) as df:
                r = df.freeze()
                print("congelado: %s (%d caminhos em %.3fs, overlay: %s)"
                      % (df.target, r["paths"], r["seconds"], df.overlay))
        elif a.cmd == "thaw":
            with open_df(a.target) as df:
                df.thaw(commit=a.commit)
                print("ok: %s" % ("overlay mesclado no alvo" if a.commit
                                   else "estado congelado restaurado, overlay descartado"))
        elif a.cmd == "status":
            with open_df(a.target) as df:
                print(json.dumps(df.status(), indent=2))
        elif a.cmd == "list":
            with open_df(a.target) as df:
                for nm in df.iterdir(a.path or ""):
                    print(nm)
        elif a.cmd == "cat":
            with open_df(a.target) as df:
                sys.stdout.buffer.write(df.read(a.path))
        elif a.cmd == "write":
            if a.src == "-":
                data = sys.stdin.buffer.read()
            elif os.path.isfile(a.src):
                with open(a.src, "rb") as f:
                    data = f.read()
            else:
                data = a.src.encode("utf-8")
            with open_df(a.target) as df:
                df.write(a.path, data)
                print("escrito no overlay: %s (%d bytes)" % (a.path, len(data)))
        elif a.cmd == "rm":
            with open_df(a.target) as df:
                df.remove(a.path)
                print("removido da view: %s" % a.path)
        elif a.cmd == "diff":
            with open_df(a.target) as df:
                print(json.dumps(df.diff(), indent=2))
        return 0
    except DeepFreezeError as e:
        print("erro: %s" % e, file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print("erro: nao encontrado: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

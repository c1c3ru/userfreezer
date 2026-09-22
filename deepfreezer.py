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
  LOCK, manifest.json, journal.log
  files/<rel>  (conteudo novo/alterado)   md/<rel> (mkdir)   del/<rel> (tombstone)

Crash-safety: cada op = (1) payload escrito atomicamente (tmp+rename),
(2) linha de journal + fsync. Journal e' a fonte da verdade; payloads
orfaos (crash entre as etapas) sao ignorados na reabertura.
"""
import argparse
import hashlib
import json
import os
import shutil
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
# Lock de instancia unica (atomic create; staleness por timestamp)
# ---------------------------------------------------------------------------
class _Lock(object):
    def __init__(self, path, timeout=10.0):
        self.path = _long(path)
        self.timeout = timeout
        self.fd = None

    def acquire(self):
        st = time.time()
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                try:
                    with open(self.path, "rb") as f:
                        meta = json.loads(f.read() or b"{}")
                    if time.time() - float(meta.get("ts", 0)) > 86400:
                        try:
                            os.remove(self.path)
                        except OSError:
                            pass
                        continue
                except (ValueError, OSError):
                    pass
                if time.time() - st > self.timeout:
                    raise DeepFreezeError(
                        "overlay bloqueado por outra instancia (ou lock stale antigo)")
                time.sleep(0.1)
            else:
                os.write(fd, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode())
                os.fsync(fd)
                self.fd = fd
                return

    def release(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
            try:
                os.remove(self.path)
            except OSError:
                pass


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
        self._seq = 0
        self._lock = _Lock(os.path.join(self.overlay, "LOCK"), lock_timeout)
        self._open()

    # -- ciclo de vida ------------------------------------------------------
    def _open(self):
        if os.path.isdir(self.overlay):
            self._lock.acquire()
            man = self._jread(os.path.join(self.overlay, "manifest.json"))
            if man is None:
                raise DeepFreezeError("overlay existe sem manifest (corrompido?)")
            self.manifest = man
            self.frozen = True
            self._load_journal()
        elif os.path.exists(self.overlay):
            raise DeepFreezeError("caminho do overlay ja existe (nao eh dir)")

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
                        self.ops[key] = (int(rec["seq"]), rec["op"], int(rec.get("d", 0)))
        # valida payloads (crash entre etapas => op irrealizavel e' descartada)
        dead = []
        for rel, (s, k, d) in self.ops.items():
            p = os.path.join(self.overlay, KIND_SUBDIR[k], *rel.split("/"))
            if not os.path.isfile(p):
                dead.append(rel)
        for rel in dead:
            self.ops.pop(rel)
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
        os.makedirs(self.overlay, exist_ok=True)
        if not self.frozen:
            self._lock.acquire()
        man = {"v": DF_VERSION, "root": self.target,
               "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "entries": entries, "hashes": hashes}
        self._jwrite(os.path.join(self.overlay, "manifest.json"),
                     json.dumps(man).encode())
        open(os.path.join(self.overlay, "journal.log"), "wb").close()
        self.manifest = man
        self.frozen = True
        self.ops = {}
        self._seq = 0
        return {"seconds": round(time.time() - t0, 3), "paths": len(entries)}

    def thaw(self, commit=False):
        if not self.frozen:
            raise DeepFreezeError("nada congelado para descongelar")
        if commit:
            self._apply_commit()
        shutil.rmtree(self.overlay, ignore_errors=True)
        self._lock.release()
        self.frozen = False
        self.manifest = None
        self.ops = {}
        self._seq = 0

    def close(self):
        self._lock.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _apply_commit(self):
        ordered = sorted(self.ops.items(), key=lambda kv: kv[1][0])
        for rel, (s, k, d) in ordered:
            dst = _long(os.path.join(self.target, *rel.split("/")))
            if k == "W":
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                src = os.path.join(self.overlay, "files", *rel.split("/"))
                with open(src, "rb") as fin, open(dst, "wb") as fout:
                    shutil.copyfileobj(fin, fout)
                    fout.flush()
                    os.fsync(fout.fileno())
            elif k == "M":
                os.makedirs(dst, exist_ok=True)
            elif k == "D":
                if d == 1:
                    if os.path.isdir(dst) and not os.path.islink(dst):
                        shutil.rmtree(dst, ignore_errors=True)
                elif os.path.isfile(dst) or os.path.islink(dst):
                    try:
                        os.unlink(dst)
                    except PermissionError:
                        raise DeepFreezeError(
                            "nao consegui remover %s (arquivo em uso?)" % dst)

    # -- helpers ------------------------------------------------------------
    def _require_frozen(self):
        if not self.frozen:
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

    def _put_payload(self, kind, rel, data=b""):
        dst = os.path.join(self.overlay, KIND_SUBDIR[kind], *rel.split("/"))
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        tmp = dst + ".tmp%d" % os.getpid()
        with open(_long(tmp), "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dst)

    def _journal(self, op, rel, d=0):
        self._seq += 1
        line = json.dumps({"seq": self._seq, "op": op, "p": rel, "d": d}) + "\n"
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
        n = len(parts)
        if n == 0:
            return "BASE"
        full = "/".join(parts)
        best_i = 0
        for i in range(n, 0, -1):
            if "/".join(parts[:i]) in self.ops:
                best_i = i
                break
        if best_i == 0:
            return "BASE"
        bseq, bkind, _bd = self.ops["/".join(parts[:best_i])]
        prefix = "/".join(parts[:best_i]) + "/"
        best_re = None
        for k, (s, kk, dd) in self.ops.items():
            if k.startswith(prefix) and s > bseq:
                cand = (len(k), s, k, kk)
                if best_re is None or cand > best_re:
                    best_re = cand
        if best_re is not None:
            _, _, rk, rkk = best_re
            if rk == full:
                return {"W": "NEW", "M": "M_DIR", "D": "DELETED"}[rkk]
            return {"W": "GONE", "M": "IMPLICIT_DIR", "D": "GONE"}[rkk]
        if best_i == n:
            return {"W": "NEW", "M": "M_DIR", "D": "DELETED"}[bkind]
        return {"W": "GONE", "M": "IMPLICIT_DIR", "D": "GONE"}[bkind]

    # -- API ------------------------------------------------------------------
    def write(self, rel, data):
        self._require_frozen()
        parts = self._norm(rel)
        if not parts:
            raise DeepFreezeError("caminho relativo invalido: %r" % rel)
        key = "/".join(parts)
        self._put_payload("W", key, data if isinstance(data, (bytes, bytearray))
                          else str(data).encode())
        self._journal("W", key)
        self.ops[key] = (self._seq, "W", 0)

    def read(self, rel):
        self._require_frozen()
        parts = self._norm(rel)
        c = self._classify(parts)
        key = "/".join(parts)
        if c == "NEW":
            with open(os.path.join(self.overlay, "files", *parts), "rb") as f:
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
            return os.path.getsize(os.path.join(self.overlay, "files", *parts))
        return os.stat(_long(os.path.join(self.target, *parts))).st_size

    def iterdir(self, rel=""):
        self._require_frozen()
        parts = self._norm(rel)
        c = self._classify(parts)
        if c == "NEW":
            raise DeepFreezeError("nao e diretorio: %r" % rel)
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

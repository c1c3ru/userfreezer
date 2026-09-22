#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes do nucleo de congelamento (deepfreezer.py) -- so' stdlib, como o
resto do core. Roda em qualquer SO com sistema de arquivos gravavel.

Cobre o ciclo completo: freeze de uma arvore, escrita por cima com o
disco real intocado, thaw (descarte), thaw --commit (merge) e a
recuperacao do journal depois de uma interrupcao.

NAO cobre a CLI nem o servico de boot: a CLI e' casca fina sobre a
classe, e o servico so' pode ser validado numa maquina real.

Uso: python3 test_deepfreezer.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deepfreezer import DeepFreezer, DeepFreezeError  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def snapshot_tree(root):
    """{rel: b'conteudo'} para arquivos e {rel + '/': None} para dirs."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_d = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_d != ".":
            out[rel_d + "/"] = None
        for fn in filenames:
            rel = fn if rel_d == "." else (rel_d + "/" + fn)
            with open(os.path.join(dirpath, fn), "rb") as f:
                out[rel] = f.read()
    return out


class _ShutilEspiao(object):
    """Delega tudo ao shutil real, avisando antes de cada rmtree."""

    def __init__(self, real, ao_remover):
        self._real = real
        self._ao_remover = ao_remover

    def __getattr__(self, nome):
        return getattr(self._real, nome)

    def rmtree(self, *a, **kw):
        self._ao_remover()
        return self._real.rmtree(*a, **kw)


class BaseCase(unittest.TestCase):
    """Cria uma arvore de teste e garante a limpeza do tmpdir."""

    TREE = {
        "a.txt": b"conteudo a",
        "b.bin": b"\x00\x01\x02\xff",
        "sub/c.txt": b"conteudo c",
        "sub/deep/d.txt": b"conteudo d",
    }
    EMPTY_DIRS = ["vazio"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dftest-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.target = os.path.join(self.tmp, "alvo")
        os.makedirs(self.target)
        for rel, data in self.TREE.items():
            p = os.path.join(self.target, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
        for d in self.EMPTY_DIRS:
            os.makedirs(os.path.join(self.target, d))
        self.baseline = snapshot_tree(self.target)

    def open_df(self, **kw):
        """DeepFreezer no alvo, fechado automaticamente no fim do teste."""
        df = DeepFreezer(self.target, **kw)
        self.addCleanup(df.close)
        return df

    def frozen_df(self, **kw):
        df = self.open_df(**kw)
        df.freeze()
        return df

    def assertDiskIntact(self):
        self.assertEqual(snapshot_tree(self.target), self.baseline,
                         "o disco real do alvo foi alterado")


# ---------------------------------------------------------------------------
# 1. freeze
# ---------------------------------------------------------------------------
class FreezeTests(BaseCase):
    def test_freeze_cria_overlay_com_manifest_e_journal(self):
        df = self.frozen_df()
        self.assertTrue(df.frozen)
        self.assertEqual(df.overlay, self.target + ".dfreezer")
        self.assertTrue(os.path.isdir(df.overlay))
        self.assertTrue(os.path.isfile(os.path.join(df.overlay, "manifest.json")))
        self.assertEqual(
            os.path.getsize(os.path.join(df.overlay, "journal.log")), 0)

    def test_freeze_registra_todos_os_caminhos_no_manifest(self):
        df = self.frozen_df()
        entries = df.manifest["entries"]
        for rel in self.TREE:
            self.assertIn(rel, entries)
            self.assertEqual(entries[rel]["t"], "f")
            self.assertEqual(entries[rel]["size"], len(self.TREE[rel]))
        for d in ["sub", "sub/deep", "vazio"]:
            self.assertEqual(entries[d], {"t": "d"})
        self.assertNotIn(".", entries)

    def test_freeze_reporta_contagem_e_nao_toca_no_disco(self):
        df = self.open_df()
        r = df.freeze()
        self.assertEqual(r["paths"], len(df.manifest["entries"]))
        self.assertGreaterEqual(r["seconds"], 0.0)
        self.assertDiskIntact()

    def test_freeze_duas_vezes_e_erro(self):
        df = self.frozen_df()
        with self.assertRaises(DeepFreezeError):
            df.freeze()

    def test_freeze_com_verify_grava_sha256(self):
        df = self.frozen_df(verify=True)
        hashes = df.manifest["hashes"]
        self.assertEqual(sorted(hashes), sorted(self.TREE))
        self.assertEqual(df.verify(), [])

    def test_alvo_inexistente_e_erro(self):
        with self.assertRaises(DeepFreezeError):
            DeepFreezer(os.path.join(self.tmp, "nao-existe"))

    def test_overlay_dentro_do_alvo_e_erro(self):
        with self.assertRaises(DeepFreezeError):
            DeepFreezer(self.target, overlay=os.path.join(self.target, "ov"))

    def test_operar_sem_freeze_e_erro(self):
        df = self.open_df()
        with self.assertRaises(DeepFreezeError):
            df.write("a.txt", b"x")
        with self.assertRaises(DeepFreezeError):
            df.read("a.txt")

    def test_caminho_com_dotdot_e_erro(self):
        df = self.frozen_df()
        for ruim in ["../fuga.txt", "sub/../../fuga.txt", "/"]:
            with self.assertRaises(DeepFreezeError):
                df.write(ruim, b"x")

    def test_segunda_instancia_no_mesmo_overlay_e_bloqueada(self):
        self.frozen_df()
        with self.assertRaises(DeepFreezeError):
            DeepFreezer(self.target, lock_timeout=0.2)


# ---------------------------------------------------------------------------
# 2. escrita por cima: a view muda, o disco real nao
# ---------------------------------------------------------------------------
class OverlayWriteTests(BaseCase):
    def test_write_sobre_arquivo_existente_nao_toca_no_disco(self):
        df = self.frozen_df()
        df.write("a.txt", b"sobrescrito")
        self.assertEqual(df.read("a.txt"), b"sobrescrito")
        self.assertDiskIntact()

    def test_write_de_arquivo_novo_em_dir_novo(self):
        df = self.frozen_df()
        df.write("novo/x.txt", b"xis")
        self.assertEqual(df.read("novo/x.txt"), b"xis")
        self.assertIn("novo", df.iterdir(""))
        self.assertDiskIntact()

    def test_write_aceita_texto_e_bytes(self):
        df = self.frozen_df()
        df.write("t.txt", "acentuacao nao, mas texto sim")
        self.assertEqual(df.read("t.txt"), b"acentuacao nao, mas texto sim")
        df.write("t.txt", bytearray(b"bytes"))
        self.assertEqual(df.read("t.txt"), b"bytes")

    def test_read_de_arquivo_intocado_vem_do_baseline(self):
        df = self.frozen_df()
        self.assertEqual(df.read("sub/deep/d.txt"), self.TREE["sub/deep/d.txt"])

    def test_read_de_inexistente_levanta_filenotfound(self):
        df = self.frozen_df()
        with self.assertRaises(FileNotFoundError):
            df.read("nao/existe.txt")

    def test_remove_de_arquivo_some_da_view_e_fica_no_disco(self):
        df = self.frozen_df()
        self.assertTrue(df.exists("sub/c.txt"))
        df.remove("sub/c.txt")
        self.assertFalse(df.exists("sub/c.txt"))
        self.assertNotIn("c.txt", df.iterdir("sub"))
        with self.assertRaises(FileNotFoundError):
            df.read("sub/c.txt")
        self.assertDiskIntact()

    def test_remove_de_diretorio_leva_o_conteudo_junto(self):
        df = self.frozen_df()
        df.remove("sub")
        self.assertFalse(df.exists("sub"))
        self.assertFalse(df.exists("sub/deep/d.txt"))
        self.assertNotIn("sub", df.iterdir(""))
        self.assertDiskIntact()

    def test_write_depois_de_remove_ressuscita_o_caminho(self):
        df = self.frozen_df()
        df.remove("a.txt")
        self.assertFalse(df.exists("a.txt"))
        df.write("a.txt", b"de volta")
        self.assertTrue(df.exists("a.txt"))
        self.assertEqual(df.read("a.txt"), b"de volta")

    def test_remove_depois_de_write_apaga_o_caminho(self):
        df = self.frozen_df()
        df.write("a.txt", b"temporario")
        df.remove("a.txt")
        self.assertFalse(df.exists("a.txt"))

    def test_remove_da_raiz_e_erro(self):
        df = self.frozen_df()
        with self.assertRaises(DeepFreezeError):
            df.remove("")

    def test_mkdirs_cria_dir_so_na_view(self):
        df = self.frozen_df()
        df.mkdirs("nova/pasta")
        self.assertTrue(df.exists("nova/pasta"))
        self.assertTrue(df.is_dir("nova/pasta"))
        self.assertFalse(os.path.exists(os.path.join(self.target, "nova")))
        self.assertDiskIntact()

    def test_mkdirs_em_dir_que_ja_existe_e_no_op(self):
        df = self.frozen_df()
        df.mkdirs("sub")
        df.mkdirs("sub")
        self.assertEqual(df.diff()["added"], [])

    def test_iterdir_mistura_baseline_e_overlay(self):
        df = self.frozen_df()
        self.assertEqual(df.iterdir(""), ["a.txt", "b.bin", "sub", "vazio"])
        df.write("z.txt", b"z")
        df.remove("b.bin")
        df.mkdirs("nova")
        self.assertEqual(df.iterdir(""), ["a.txt", "nova", "sub", "vazio", "z.txt"])
        self.assertEqual(df.iterdir("sub"), ["c.txt", "deep"])

    def test_iterdir_de_arquivo_e_erro(self):
        df = self.frozen_df()
        df.write("arq.txt", b"x")
        with self.assertRaises(DeepFreezeError):
            df.iterdir("arq.txt")

    def test_size_le_overlay_ou_baseline(self):
        df = self.frozen_df()
        self.assertEqual(df.size("a.txt"), len(self.TREE["a.txt"]))
        df.write("a.txt", b"123")
        self.assertEqual(df.size("a.txt"), 3)

    def test_diff_classifica_adicionado_modificado_e_removido(self):
        df = self.frozen_df()
        df.write("a.txt", b"mudou")        # modificado (existia no freeze)
        df.write("novo.txt", b"novo")      # adicionado
        df.mkdirs("nova")                  # adicionado (dir)
        df.remove("b.bin")                 # removido
        df.remove("vazio")                 # removido (dir)
        self.assertEqual(df.diff(), {
            "added": ["nova/", "novo.txt"],
            "modified": ["a.txt"],
            "deleted": ["b.bin", "vazio/"],
        })

    def test_status_reflete_as_operacoes_pendentes(self):
        df = self.frozen_df()
        df.write("a.txt", b"1")
        df.mkdirs("nova")
        df.remove("b.bin")
        st = df.status()
        self.assertTrue(st["frozen"])
        self.assertEqual(st["target"], self.target)
        self.assertEqual(st["overlay_ops"], {"W": 1, "M": 1, "D": 1})
        self.assertEqual(st["baseline_paths"], len(df.manifest["entries"]))
        self.assertEqual(st["pending_seq"], 3)

    def test_verify_detecta_escrita_fora_da_api(self):
        df = self.frozen_df(verify=True)
        with open(os.path.join(self.target, "a.txt"), "wb") as f:
            f.write(b"alterado por fora")
        self.assertEqual(df.verify(), ["a.txt"])


# ---------------------------------------------------------------------------
# 3. thaw: descarte
# ---------------------------------------------------------------------------
class ThawDiscardTests(BaseCase):
    def test_thaw_descarta_tudo_e_restaura_o_estado_congelado(self):
        df = self.frozen_df()
        df.write("a.txt", b"mudou")
        df.write("novo.txt", b"novo")
        df.mkdirs("nova/pasta")
        df.remove("sub/c.txt")
        df.remove("vazio")
        overlay = df.overlay
        df.thaw()
        self.assertFalse(df.frozen)
        self.assertIsNone(df.manifest)
        self.assertEqual(df.ops, {})
        self.assertFalse(os.path.exists(overlay))
        self.assertDiskIntact()

    def test_reabrir_depois_do_thaw_nao_ve_overlay(self):
        df = self.frozen_df()
        df.write("a.txt", b"mudou")
        df.thaw()
        df2 = self.open_df()
        self.assertFalse(df2.frozen)

    def test_thaw_solta_o_lock_antes_de_apagar_o_overlay(self):
        """Regressao: no Windows nao se apaga arquivo aberto.

        O LOCK mora dentro do overlay e fica aberto ate' o release(). Se o
        rmtree vier primeiro, no Windows ele falha em silencio (por causa
        do ignore_errors=True), o overlay sobra e a reabertura seguinte
        morre com "overlay existe sem manifest". No Linux passa nas duas
        ordens, entao o teste checa a ordem, nao so' o resultado.
        """
        import deepfreezer as dfmod
        df = self.frozen_df()
        visto = {}

        def ao_remover():
            visto["fd_aberto"] = df._lock.fd is not None
            visto["lock_em_disco"] = os.path.exists(
                os.path.join(df.overlay, "LOCK"))

        real = dfmod.shutil
        dfmod.shutil = _ShutilEspiao(real, ao_remover)
        try:
            df.thaw()
        finally:
            dfmod.shutil = real

        self.assertFalse(visto["fd_aberto"],
                         "LOCK ainda aberto no rmtree: quebra no Windows")
        self.assertFalse(visto["lock_em_disco"],
                         "LOCK ainda em disco no rmtree: quebra no Windows")
        self.assertFalse(os.path.exists(df.overlay))

    def test_thaw_sem_freeze_e_erro(self):
        df = self.open_df()
        with self.assertRaises(DeepFreezeError):
            df.thaw()


# ---------------------------------------------------------------------------
# 4. thaw --commit: merge
# ---------------------------------------------------------------------------
class ThawCommitTests(BaseCase):
    def test_commit_aplica_write_mkdirs_e_remove_no_disco(self):
        df = self.frozen_df()
        df.write("a.txt", b"mudou")
        df.write("novo/x.txt", b"xis")
        df.mkdirs("nova/pasta")
        df.remove("b.bin")
        df.remove("sub/deep")
        overlay = df.overlay
        df.thaw(commit=True)

        disco = snapshot_tree(self.target)
        self.assertEqual(disco["a.txt"], b"mudou")
        self.assertEqual(disco["novo/x.txt"], b"xis")
        self.assertIn("nova/pasta/", disco)
        self.assertNotIn("b.bin", disco)
        self.assertNotIn("sub/deep/d.txt", disco)
        self.assertNotIn("sub/deep/", disco)
        # o que nao foi tocado continua igual
        self.assertEqual(disco["sub/c.txt"], self.TREE["sub/c.txt"])
        self.assertIn("vazio/", disco)
        self.assertFalse(os.path.exists(overlay))
        self.assertFalse(df.frozen)

    def test_commit_respeita_a_ordem_das_operacoes(self):
        df = self.frozen_df()
        df.write("a.txt", b"primeiro")
        df.remove("a.txt")
        df.write("b.bin", b"antes")
        df.write("b.bin", b"depois")
        df.thaw(commit=True)
        disco = snapshot_tree(self.target)
        self.assertNotIn("a.txt", disco)
        self.assertEqual(disco["b.bin"], b"depois")

    def test_commit_de_remove_seguido_de_write_mantem_o_arquivo(self):
        df = self.frozen_df()
        df.remove("a.txt")
        df.write("a.txt", b"ressuscitado")
        df.thaw(commit=True)
        with open(os.path.join(self.target, "a.txt"), "rb") as f:
            self.assertEqual(f.read(), b"ressuscitado")

    def test_commit_sem_alteracoes_deixa_o_disco_igual(self):
        df = self.frozen_df()
        df.thaw(commit=True)
        self.assertDiskIntact()

    def test_freeze_de_novo_depois_do_commit(self):
        df = self.frozen_df()
        df.write("a.txt", b"v2")
        df.thaw(commit=True)
        r = df.freeze()
        self.assertGreater(r["paths"], 0)
        self.assertEqual(df.read("a.txt"), b"v2")
        df.thaw()
        with open(os.path.join(self.target, "a.txt"), "rb") as f:
            self.assertEqual(f.read(), b"v2")


# ---------------------------------------------------------------------------
# 5. recuperacao do journal depois de uma interrupcao
# ---------------------------------------------------------------------------
class JournalRecoveryTests(BaseCase):
    def crash(self, df):
        """Simula o processo morrendo: solta o lock, overlay fica no disco."""
        df.close()

    def append_journal(self, overlay, raw):
        with open(os.path.join(overlay, "journal.log"), "ab") as f:
            f.write(raw)

    def test_reabrir_recupera_write_mkdirs_e_remove(self):
        df = self.frozen_df()
        df.write("a.txt", b"sobreviveu")
        df.write("novo.txt", b"novo")
        df.mkdirs("nova/pasta")
        df.remove("sub/c.txt")
        self.crash(df)

        df2 = self.open_df()
        self.assertTrue(df2.frozen)
        self.assertEqual(df2.read("a.txt"), b"sobreviveu")
        self.assertEqual(df2.read("novo.txt"), b"novo")
        self.assertTrue(df2.is_dir("nova/pasta"))
        self.assertFalse(df2.exists("sub/c.txt"))
        self.assertDiskIntact()

    def test_reabrir_e_thaw_ainda_restaura_o_estado_congelado(self):
        df = self.frozen_df()
        df.write("a.txt", b"mudou")
        df.remove("b.bin")
        self.crash(df)

        df2 = self.open_df()
        df2.thaw()
        self.assertDiskIntact()

    def test_reabrir_e_commit_aplica_o_que_estava_no_journal(self):
        df = self.frozen_df()
        df.write("a.txt", b"mudou")
        df.remove("b.bin")
        self.crash(df)

        df2 = self.open_df()
        df2.thaw(commit=True)
        disco = snapshot_tree(self.target)
        self.assertEqual(disco["a.txt"], b"mudou")
        self.assertNotIn("b.bin", disco)

    def test_seq_continua_depois_de_reabrir(self):
        df = self.frozen_df()
        df.remove("a.txt")
        seq_antes = df.status()["pending_seq"]
        self.crash(df)

        df2 = self.open_df()
        self.assertEqual(df2.status()["pending_seq"], seq_antes)
        df2.write("a.txt", b"depois do crash")
        self.assertGreater(df2.status()["pending_seq"], seq_antes)
        # a op nova e' mais recente que o remove, entao ela vence
        self.assertTrue(df2.exists("a.txt"))
        self.assertEqual(df2.read("a.txt"), b"depois do crash")

    def test_linha_truncada_no_fim_do_journal_e_ignorada(self):
        df = self.frozen_df()
        df.write("bom.txt", b"ok")
        overlay = df.overlay
        self.crash(df)
        # crash no meio do fsync da linha: JSON cortado, sem \n
        self.append_journal(overlay, b'{"seq": 99, "op": "W", "p": "truncado')

        df2 = self.open_df()
        self.assertEqual(df2.read("bom.txt"), b"ok")
        self.assertFalse(df2.exists("truncado"))

    def test_journal_para_na_primeira_linha_invalida(self):
        df = self.frozen_df()
        df.write("bom.txt", b"ok")
        overlay = df.overlay
        self.crash(df)
        self.append_journal(overlay, b'{"seq": 99, "op": "W", "p": "trunc')
        # linha integra depois da truncada: o resto do journal e' descartado
        self.append_journal(
            overlay, json.dumps({"seq": 100, "op": "W", "p": "tarde.txt",
                                 "d": 0}).encode() + b"\n")
        with open(os.path.join(overlay, "files", "tarde.txt"), "wb") as f:
            f.write(b"tarde demais")

        df2 = self.open_df()
        self.assertEqual(df2.read("bom.txt"), b"ok")
        self.assertFalse(df2.exists("tarde.txt"))

    def test_op_sem_payload_e_descartada(self):
        """Crash entre a linha do journal e o payload: op irrealizavel."""
        df = self.frozen_df()
        df.write("bom.txt", b"ok")
        overlay = df.overlay
        self.crash(df)
        self.append_journal(
            overlay, json.dumps({"seq": 50, "op": "W", "p": "orfao.txt",
                                 "d": 0}).encode() + b"\n")

        df2 = self.open_df()
        self.assertNotIn("orfao.txt", df2.ops)
        self.assertFalse(df2.exists("orfao.txt"))
        self.assertEqual(df2.read("bom.txt"), b"ok")

    def test_payload_sem_linha_no_journal_e_ignorado(self):
        """Crash entre o payload e a linha: journal e' a fonte da verdade."""
        df = self.frozen_df()
        overlay = df.overlay
        self.crash(df)
        os.makedirs(os.path.join(overlay, "files"), exist_ok=True)
        with open(os.path.join(overlay, "files", "a.txt"), "wb") as f:
            f.write(b"payload orfao")

        df2 = self.open_df()
        self.assertEqual(df2.ops, {})
        self.assertEqual(df2.read("a.txt"), self.TREE["a.txt"])

    def test_overlay_sem_manifest_e_erro(self):
        df = self.frozen_df()
        overlay = df.overlay
        self.crash(df)
        os.remove(os.path.join(overlay, "manifest.json"))
        with self.assertRaises(DeepFreezeError):
            DeepFreezer(self.target)

    def test_lock_remanescente_de_um_crash_nao_trava_para_sempre(self):
        df = self.frozen_df()
        overlay = df.overlay
        df.write("a.txt", b"x")
        self.crash(df)
        # lock stale (> 24h) deixado por um processo que morreu
        with open(os.path.join(overlay, "LOCK"), "wb") as f:
            f.write(json.dumps({"pid": 999999, "ts": 0}).encode())
        df2 = self.open_df(lock_timeout=0.2)
        self.assertEqual(df2.read("a.txt"), b"x")


if __name__ == "__main__":
    unittest.main(verbosity=2)

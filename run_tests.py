#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roda toda a suite de testes do repositorio de uma vez so'.

Existe porque os testes nao vivem num pacote unico: `packaging/` e
`packaging/windows/` nao tem `__init__.py`, entao um
`python3 -m unittest discover` na raiz nao acha nada (a descoberta do
unittest so' desce por diretorios importaveis). Este script procura
cada pasta que contenha arquivos `test_*.py` e roda o discover dentro
dela, com a raiz do repositorio no sys.path pra quem fizer
`import deepfreezer`.

Novos testes nao precisam registrar nada aqui: basta o arquivo se
chamar `test_*.py` e estar em qualquer lugar do repositorio.

So' stdlib, igual ao resto do projeto.

Uso: python3 run_tests.py [-v]
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))

# Pastas que nunca contem teste nosso (artefato de build, cache, venv).
IGNORADAS = {
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def pastas_com_teste(raiz):
    """Todas as pastas sob `raiz` que contem pelo menos um test_*.py."""
    encontradas = []
    for pasta, subpastas, arquivos in os.walk(raiz):
        # os.walk le esta lista pra decidir onde descer -- filtrar aqui
        # poda a arvore inteira (inclusive .git, que e' enorme).
        subpastas[:] = sorted(
            d for d in subpastas
            if d not in IGNORADAS and not d.startswith(".")
        )
        if any(a.startswith("test_") and a.endswith(".py") for a in arquivos):
            encontradas.append(pasta)
    return sorted(encontradas)


def main(argv):
    verbosidade = 2 if ("-v" in argv or "--verbose" in argv) else 1

    pastas = pastas_com_teste(ROOT)
    if not pastas:
        print("ERRO: nenhum arquivo test_*.py encontrado em %s" % ROOT,
              file=sys.stderr)
        return 1

    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for pasta in pastas:
        print("descobrindo testes em %s" % (os.path.relpath(pasta, ROOT),))
        # Cada pasta e' sua propria raiz de descoberta: os testes de
        # packaging/windows importam `os_detect` como modulo solto.
        suite.addTest(loader.discover(
            start_dir=pasta, pattern="test_*.py", top_level_dir=pasta,
        ))

    # Erro ao *carregar* um teste (import quebrado, por exemplo) vira um
    # caso falho dentro da suite, mas o loader tambem registra aqui --
    # imprimir ajuda a entender uma falha de import no log do CI.
    for erro in getattr(loader, "errors", []):
        print(erro, file=sys.stderr)

    resultado = unittest.TextTestRunner(verbosity=verbosidade).run(suite)

    if resultado.testsRun == 0:
        # Suite vazia passaria como sucesso e o CI ficaria verde sem ter
        # verificado nada -- isso e' falha, nao sucesso.
        print("ERRO: nenhum teste foi executado", file=sys.stderr)
        return 1

    return 0 if resultado.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

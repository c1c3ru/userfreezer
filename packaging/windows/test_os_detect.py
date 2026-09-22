#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes de os_detect.classify() -- so' a parte pura (build+edition ->
estrategia), sem tocar em registro do Windows, entao roda em qualquer
SO (inclusive no sandbox Linux usado pra desenvolver este repo).

NAO cobre get_os_info() (leitura real via winreg): isso so' pode ser
validado numa maquina Windows de verdade, rodando
`python os_detect.py` e conferindo o resultado.

Uso: python3 packaging/windows/test_os_detect.py
"""
import os
import sys
import unittest

# dirname/abspath, e nao rsplit("/"): no Windows o separador e' barra
# invertida, entao o rsplit devolvia o caminho do proprio arquivo em
# vez da pasta dele, e o import abaixo quebrava.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from os_detect import classify  # noqa: E402


class ClassifyTests(unittest.TestCase):
    # -- Windows 11 --------------------------------------------------
    def test_win11_enterprise_usa_uwf(self):
        r = classify(22631, "Enterprise")
        self.assertEqual(r["windows_version"], "11")
        self.assertEqual(r["strategy"], "uwf")

    def test_win11_iot_enterprise_usa_uwf(self):
        r = classify(26100, "IoTEnterprise")
        self.assertEqual(r["strategy"], "uwf")

    def test_win11_pro_cai_no_vhdx(self):
        r = classify(26100, "Professional")
        self.assertEqual(r["windows_version"], "11")
        self.assertEqual(r["strategy"], "vhdx_diff")

    def test_win11_home_cai_no_vhdx(self):
        r = classify(22631, "Core")
        self.assertEqual(r["strategy"], "vhdx_diff")

    # -- Windows 10 ---------------------------------------------------
    def test_win10_education_usa_uwf(self):
        r = classify(19045, "Education")
        self.assertEqual(r["windows_version"], "10")
        self.assertEqual(r["strategy"], "uwf")

    def test_win10_home_cai_no_vhdx(self):
        r = classify(19045, "Core")
        self.assertEqual(r["windows_version"], "10")
        self.assertEqual(r["strategy"], "vhdx_diff")

    def test_win10_build_minimo_ainda_e_10(self):
        r = classify(10240, "Enterprise")
        self.assertEqual(r["windows_version"], "10")

    # -- Windows 7 ------------------------------------------------------
    def test_win7_embedded_usa_ewf_fbwf(self):
        r = classify(7601, "Embedded")
        self.assertEqual(r["windows_version"], "7")
        self.assertEqual(r["strategy"], "ewf_fbwf")

    def test_win7_professional_cai_no_vhdx(self):
        r = classify(7601, "Professional")
        self.assertEqual(r["windows_version"], "7")
        self.assertEqual(r["strategy"], "vhdx_diff")

    def test_win7_home_premium_cai_no_vhdx(self):
        r = classify(7600, "HomePremium")
        self.assertEqual(r["strategy"], "vhdx_diff")

    # -- fora do escopo suportado -----------------------------------
    def test_win8_fica_unsupported(self):
        r = classify(9200, "Professional")
        self.assertEqual(r["strategy"], "unsupported")

    def test_win81_fica_unsupported(self):
        r = classify(9600, "Core")
        self.assertEqual(r["strategy"], "unsupported")

    def test_build_zero_fica_unsupported(self):
        r = classify(0, "")
        self.assertEqual(r["strategy"], "unsupported")

    def test_build_anterior_ao_win7_fica_unsupported(self):
        r = classify(6002, "Ultimate")  # Windows Vista SP2
        self.assertEqual(r["strategy"], "unsupported")

    # -- edicao desconhecida nunca assume write filter nativo -------
    def test_edicao_win10_desconhecida_cai_no_vhdx_nao_uwf(self):
        r = classify(19045, "AlgumaEdicaoNovaQueNaoEstaNaLista")
        self.assertEqual(r["strategy"], "vhdx_diff")

    def test_edicao_win7_desconhecida_cai_no_vhdx_nao_ewf(self):
        r = classify(7601, "AlgumaEdicaoNovaQueNaoEstaNaLista")
        self.assertEqual(r["strategy"], "vhdx_diff")


if __name__ == "__main__":
    unittest.main()

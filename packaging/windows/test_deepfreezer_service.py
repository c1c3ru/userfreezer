#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes do despacho do servico Windows (`deepfreezer_service.main`).

Rodam em qualquer SO, sem pywin32: os modulos do pywin32 sao
substituidos por dublês em `sys.modules` antes do import, e o que se
verifica e' a ORDEM das chamadas, nao o efeito no Windows.

O que esta' sob teste e' o bug do evento 7009 (timeout de 30s do SCM
esperando o processo se conectar): qualquer chamada que bloqueie antes
de `StartServiceCtrlDispatcher()` derruba o start do servico sem deixar
log nem excecao. Por isso os testes checam que nada modal acontece no
caminho do SCM -- inclusive com SESSIONNAME presente, que era
exatamente o gatilho da versao antiga.
"""
import logging
import os
import sys
import types
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
for _p in (AQUI, RAIZ):
    if _p not in sys.path:
        sys.path.insert(0, _p)

NOMES_PYWIN32 = ("servicemanager", "win32event", "win32service",
                 "win32serviceutil")


class ErroWin32(Exception):
    """Faz o papel de pywintypes.error: o codigo e' lido do atributo
    `winerror`, igual ao erro de verdade do pywin32."""

    def __init__(self, winerror, mensagem=""):
        Exception.__init__(self, mensagem or ("winerror %d" % winerror))
        self.winerror = winerror


def _dubles(chamadas, erro_do_dispatcher=None, erro_do_initialize=None):
    servicemanager = types.ModuleType("servicemanager")
    servicemanager.EVENTLOG_ERROR_TYPE = 1
    servicemanager.EVENTLOG_INFORMATION_TYPE = 4
    servicemanager.PYS_SERVICE_STARTED = 1

    def initialize(*a):
        chamadas.append("Initialize")
        if erro_do_initialize is not None:
            raise erro_do_initialize

    def dispatcher(*a):
        chamadas.append("StartServiceCtrlDispatcher")
        if erro_do_dispatcher is not None:
            raise erro_do_dispatcher

    servicemanager.Initialize = initialize
    servicemanager.PrepareToHostSingle = (
        lambda *a: chamadas.append("PrepareToHostSingle"))
    servicemanager.StartServiceCtrlDispatcher = dispatcher
    servicemanager.LogMsg = lambda *a, **k: chamadas.append("LogMsg")

    win32event = types.ModuleType("win32event")
    win32event.INFINITE = -1
    win32event.CreateEvent = lambda *a: object()
    win32event.SetEvent = lambda *a: None
    win32event.WaitForSingleObject = lambda *a: None

    win32service = types.ModuleType("win32service")
    win32service.SERVICE_RUNNING = 4
    win32service.SERVICE_STOP_PENDING = 3

    win32serviceutil = types.ModuleType("win32serviceutil")

    class ServiceFramework(object):
        def __init__(self, args):
            pass

        def ReportServiceStatus(self, estado):
            pass

    win32serviceutil.ServiceFramework = ServiceFramework
    win32serviceutil.HandleCommandLine = (
        lambda *a: chamadas.append("HandleCommandLine"))

    return {
        "servicemanager": servicemanager,
        "win32event": win32event,
        "win32service": win32service,
        "win32serviceutil": win32serviceutil,
    }


class DespachoDoServico(unittest.TestCase):
    """Cada teste carrega o modulo de novo, ligado aos seus proprios
    dublês, e registra o que foi chamado em `self.chamadas`."""

    def setUp(self):
        self.chamadas = []
        self._modulos_salvos = {}
        self._argv = sys.argv
        self._sessionname = os.environ.get("SESSIONNAME")

    def tearDown(self):
        sys.argv = self._argv
        for nome, mod in self._modulos_salvos.items():
            if mod is None:
                sys.modules.pop(nome, None)
            else:
                sys.modules[nome] = mod
        sys.modules.pop("deepfreezer_service", None)
        if self._sessionname is None:
            os.environ.pop("SESSIONNAME", None)
        else:
            os.environ["SESSIONNAME"] = self._sessionname

    def carrega(self, **kwargs):
        for nome, mod in _dubles(self.chamadas, **kwargs).items():
            self._modulos_salvos[nome] = sys.modules.get(nome)
            sys.modules[nome] = mod
        self._modulos_salvos.setdefault("deepfreezer_service",
                                        sys.modules.get("deepfreezer_service"))
        sys.modules.pop("deepfreezer_service", None)
        import deepfreezer_service as svc

        self.assertTrue(
            svc._HAVE_PYWIN32,
            "os dublês do pywin32 deveriam ter sido importados pelo modulo")

        # Sem tocar em C:\ProgramData (que no Linux viraria uma pasta com
        # esse nome literal no cwd) e sem MessageBox de verdade.
        log = logging.getLogger("teste-deepfreezerd")
        log.addHandler(logging.NullHandler())
        log.propagate = False
        svc._setup_logging = lambda: log
        svc._msgbox = lambda *a, **k: self.chamadas.append("_msgbox")

        sys.argv = ["deepfreezer_service.exe"]
        return svc

    # -- o caminho do SCM --------------------------------------------

    def test_despacha_pro_scm_sem_nada_bloqueante_antes(self):
        svc = self.carrega()
        self.assertEqual(svc.main(), 0)
        self.assertEqual(
            self.chamadas,
            ["Initialize", "PrepareToHostSingle", "StartServiceCtrlDispatcher"])

    def test_sessionname_presente_nao_abre_caixa_no_caminho_do_scm(self):
        """A regressao do evento 7009: com SESSIONNAME setada (herdada
        como variavel de sistema), a versao antiga abria uma MessageBox
        modal na sessao 0 e o processo nunca se conectava ao SCM."""
        os.environ["SESSIONNAME"] = "Console"
        svc = self.carrega()
        self.assertEqual(svc.main(), 0)
        self.assertNotIn("_msgbox", self.chamadas)
        self.assertIn("StartServiceCtrlDispatcher", self.chamadas)

    def test_initialize_que_falha_nao_impede_o_despacho(self):
        """Registrar a fonte de evento e' opcional: se ela falhar, o
        despacho tem que acontecer de todo jeito -- senao volta a dar
        timeout no SCM sem explicacao."""
        svc = self.carrega(erro_do_initialize=ErroWin32(5, "acesso negado"))
        self.assertEqual(svc.main(), 0)
        self.assertIn("StartServiceCtrlDispatcher", self.chamadas)

    # -- duplo clique (o SCM nao iniciou o processo) -------------------

    def test_erro_1063_com_sessao_interativa_mostra_a_caixa(self):
        os.environ["SESSIONNAME"] = "Console"
        svc = self.carrega(erro_do_dispatcher=ErroWin32(1063, "sem SCM"))
        self.assertEqual(1063, svc.ERRO_NAO_INICIADO_PELO_SCM)
        self.assertEqual(svc.main(), 1)
        self.assertEqual(self.chamadas[-1], "_msgbox")

    def test_erro_1063_sem_sessao_interativa_nao_mostra_a_caixa(self):
        os.environ.pop("SESSIONNAME", None)
        svc = self.carrega(erro_do_dispatcher=ErroWin32(1063, "sem SCM"))
        self.assertEqual(svc.main(), 1)
        self.assertNotIn("_msgbox", self.chamadas)

    def test_erro_diferente_de_1063_propaga(self):
        """Qualquer outra falha do dispatcher e' um problema de verdade e
        nao pode ser confundida com duplo clique."""
        svc = self.carrega(erro_do_dispatcher=ErroWin32(1053, "timeout"))
        with self.assertRaises(ErroWin32):
            svc.main()

    # -- os outros modos continuam intactos ---------------------------

    def test_argumento_conhecido_vai_pro_handlecommandline(self):
        svc = self.carrega()
        sys.argv = ["deepfreezer_service.exe", "install"]
        svc.main()
        self.assertEqual(self.chamadas, ["HandleCommandLine"])
        self.assertNotIn("StartServiceCtrlDispatcher", self.chamadas)


if __name__ == "__main__":
    unittest.main()

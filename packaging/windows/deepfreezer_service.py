#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servico Windows do DeepFreezer -- dois modos de uso:

1) Servico nativo via pywin32 (requer 'pip install pywin32'):
     python deepfreezer_service.py install
     python deepfreezer_service.py start
   (ver install_service_pywin32.ps1)

2) Processo simples envolvido pelo NSSM -- nao depende de pywin32,
   funciona tambem a partir do .exe gerado por PyInstaller:
     nssm install DeepFreezer python.exe "deepfreezer_service.py --foreground"
   (ver install_service_nssm.ps1)

Em ambos os modos, no start: para cada alvo do config descarta o
overlay da sessao anterior (thaw sem commit) e recongela; em seguida
restringe a ACL do overlay a Administradores/SYSTEM via icacls.

Config: mesmo formato JSON do Linux (ver packaging/config.example.json),
por padrao em C:\\ProgramData\\DeepFreezer\\config.json (sobreponivel
pela variavel de ambiente DEEPFREEZER_CONFIG).
"""
import ctypes
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deepfreezer import DeepFreezer, DeepFreezeError  # noqa: E402

try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
    _HAVE_PYWIN32 = True
except ImportError:
    _HAVE_PYWIN32 = False

MB_ICONWARNING = 0x30

# "The service process could not connect to the service controller" --
# e' o que StartServiceCtrlDispatcher() devolve quando o processo NAO
# foi iniciado pelo SCM (duplo clique, por exemplo).
ERRO_NAO_INICIADO_PELO_SCM = 1063


def _msgbox(text, title="DeepFreezer", icon=MB_ICONWARNING):
    """Caixa de mensagem nativa do Windows (nao depende de console nem
    de pywin32) -- unico jeito de dar feedback visivel num .exe
    empacotado com --noconsole quando ele e' executado errado (ex.:
    duplo clique direto, sem estar instalado como servico)."""
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, icon)
    except Exception:
        pass


def _running_interactively():
    """Heuristica: sessoes interativas (login local/RDP) tem a env var
    SESSIONNAME setada pelo Terminal Services; a sessao 0 (onde o SCM
    inicia servicos) nao tem. Usada so' para decidir se e' seguro (e
    util) mostrar uma MessageBox -- nunca pra alterar o caminho real
    de inicializacao do servico via SCM."""
    return bool(os.environ.get("SESSIONNAME"))


CONFIG_PATH = os.environ.get(
    "DEEPFREEZER_CONFIG", r"C:\ProgramData\DeepFreezer\config.json")
LOG_DIR = r"C:\ProgramData\DeepFreezer"


def _setup_logging():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        pass
    log = logging.getLogger("deepfreezerd")
    log.setLevel(logging.INFO)
    if not log.handlers:
        try:
            handler = logging.handlers.RotatingFileHandler(
                os.path.join(LOG_DIR, "deepfreezer.log"),
                maxBytes=1 << 20, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s deepfreezerd %(levelname)s: %(message)s"))
            log.addHandler(handler)
        except OSError:
            log.addHandler(logging.StreamHandler())
    return log


def _harden_overlay(path, log):
    """Restringe a ACL do overlay a Administradores (S-1-5-32-544) e
    SYSTEM (S-1-5-18), removendo a heranca (inclui o acesso padrao do
    grupo Usuarios)."""
    try:
        subprocess.run(
            ["icacls", path, "/inheritance:r",
             "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
             "/grant:r", "*S-1-5-18:(OI)(CI)F"],
            check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        log.warning("hardening de ACL parcial em %s: %s", path, e)


def _event_log(is_error, msg):
    """Registra tambem no Visualizador de Eventos do Windows (log
    Application), alem do arquivo em C:\\ProgramData\\DeepFreezer --
    e' onde um administrador de verdade vai procurar feedback quando o
    enforcement falhar, em vez de caca ao arquivo de log. So' funciona
    com pywin32 disponivel; nunca deve derrubar o enforcement se a
    fonte de evento nao estiver registrada ou algo do tipo."""
    if not _HAVE_PYWIN32:
        return
    try:
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_ERROR_TYPE if is_error
            else servicemanager.EVENTLOG_INFORMATION_TYPE,
            0xF000,
            ("DeepFreezer", msg))
    except Exception:
        pass


def enforce_all(log):
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        msg = "erro lendo config %s: %s" % (CONFIG_PATH, e)
        log.error(msg)
        _event_log(True, msg)
        return False
    targets = cfg.get("targets", [])
    if not targets:
        msg = "config sem 'targets': %s" % CONFIG_PATH
        log.error(msg)
        _event_log(True, msg)
        return False

    ok = True
    for entry in targets:
        target = entry.get("target")
        try:
            df = DeepFreezer(target, overlay=entry.get("overlay"),
                              verify=bool(entry.get("verify", False)))
        except DeepFreezeError as e:
            msg = "%s: %s" % (target, e)
            log.error(msg)
            _event_log(True, msg)
            ok = False
            continue
        try:
            if df.frozen:
                log.info("%s: overlay de sessao anterior encontrado, descartando", target)
                df.thaw(commit=False)
            r = df.freeze()
            msg = "%s: congelado (%d caminhos, %.3fs, overlay=%s)" % (
                target, r["paths"], r["seconds"], df.overlay)
            log.info(msg)
            _event_log(False, msg)
            _harden_overlay(df.overlay, log)
        except DeepFreezeError as e:
            msg = "%s: %s" % (target, e)
            log.error(msg)
            _event_log(True, msg)
            ok = False
        finally:
            df.close()
    return ok


def run_foreground():
    """Modo NSSM: roda o enforcement uma vez e fica residente ate o
    NSSM encerrar o processo (nssm stop / servico parado)."""
    log = _setup_logging()
    enforce_all(log)
    while True:
        time.sleep(3600)


if _HAVE_PYWIN32:
    class DeepFreezerService(win32serviceutil.ServiceFramework):
        _svc_name_ = "DeepFreezer"
        _svc_display_name_ = "DeepFreezer"
        _svc_description_ = ("Retem o estado congelado das arvores de "
                              "diretorio configuradas; mudancas caem em "
                              "overlay e sao descartadas no proximo boot.")

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.log = _setup_logging()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            try:
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STARTED,
                    (self._svc_name_, ""))
            except Exception:
                # so' um log informativo -- nao pode derrubar o servico se a
                # fonte de evento nao estiver registrada corretamente (visto
                # na pratica num .exe frozen pelo PyInstaller: essa chamada
                # sem guarda travava o start inteiro com "Cannot start
                # service", exatamente o mesmo risco que _event_log() ja
                # existe pra evitar em todo o resto do arquivo).
                pass
            enforce_all(self.log)
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)


def _dispatch_or_explain():
    """Chamado sem argumentos: pode ser o SCM iniciando o servico ou
    alguem dando duplo clique no .exe.

    Despacha pro SCM PRIMEIRO e decide pelo resultado, em vez de tentar
    adivinhar o contexto antes. O caminho do SCM nao admite nada que
    bloqueie: ele espera 30s pelo processo se conectar e, se a conexao
    nao vier, aborta com o evento 7009 e nenhum log nem excecao Python.

    A versao anterior decidia por heuristica (a env var SESSIONNAME)
    ANTES de despachar, e abria uma MessageBox modal quando ela estava
    presente. Num servico isso e' fatal: SESSIONNAME e' herdada pelo
    processo do servico se existir como variavel de ambiente de
    sistema, e a caixa entao abre na sessao 0, invisivel e sem ninguem
    pra fechar -- o processo fica bloqueado pra sempre e nunca chega a
    se conectar. Resultado exato: 7009.

    Ja o erro 1063 do dispatcher e' um teste confiavel de "nao fui
    iniciado pelo SCM", e ele nunca bloqueia."""
    log = _setup_logging()
    log.info("iniciado sem argumentos (frozen=%s): despachando pro SCM",
             bool(getattr(sys, "frozen", False)))

    try:
        servicemanager.Initialize()
    except Exception:
        # Registrar a fonte de evento e' opcional, igual ao LogMsg do
        # SvcDoRun: nao pode impedir o despacho, senao volta a virar
        # timeout no SCM sem explicacao nenhuma.
        log.warning("servicemanager.Initialize() falhou; seguindo sem ele")

    servicemanager.PrepareToHostSingle(DeepFreezerService)
    try:
        servicemanager.StartServiceCtrlDispatcher()
    except Exception as e:
        # E' um pywintypes.error; comparado pelo atributo winerror pra
        # nao precisar importar pywintypes so' por causa disto.
        if getattr(e, "winerror", None) != ERRO_NAO_INICIADO_PELO_SCM:
            log.exception("falha despachando o servico pro SCM")
            raise
        log.info("nao foi o SCM que iniciou este processo (erro 1063)")
        if _running_interactively():
            # Duplo clique direto no .exe. Aqui bloquear e' inofensivo:
            # ha' um usuario na frente da tela pra fechar a caixa.
            _msgbox(
                "DeepFreezer nao esta instalado como servico do Windows.\n\n"
                "Executar este .exe com duplo clique nao faz nada de util: ele "
                "so' protege as pastas configuradas quando roda como servico, "
                "reforcando o congelamento a cada boot.\n\n"
                "Abra o PowerShell como Administrador e rode:\n"
                "  install_service_exe.ps1\n\n"
                "(ver packaging\\windows\\README.md para as formas de "
                "instalar o servico)",
                title="DeepFreezer - nao instalado como servico")
        return 1
    return 0


def main():
    if not _HAVE_PYWIN32:
        if "--foreground" not in sys.argv:
            sys.stderr.write(
                "aviso: pywin32 nao encontrado; rodando em modo --foreground (NSSM)\n")
            if _running_interactively():
                _msgbox(
                    "DeepFreezer esta rodando em modo --foreground (sem pywin32) "
                    "porque foi executado diretamente, sem argumentos.\n\n"
                    "Isso faz o enforcement UMA VEZ agora, mas nao registra nada "
                    "como servico do Windows -- ao fechar esta janela/processo, a "
                    "protecao para. Para funcionar de verdade a cada boot, instale "
                    "via NSSM (ver packaging\\windows\\README.md).")
        return run_foreground()
    if "--foreground" in sys.argv:
        return run_foreground()
    if len(sys.argv) == 1:
        # Sem argumentos: pode ser o SCM ou duplo clique.
        # win32serviceutil.HandleCommandLine() decidiria isso sozinho,
        # mas a heuristica dele foi desenhada pra frozen exe no estilo
        # py2exe -- num .exe congelado com PyInstaller ela pode nao
        # reconhecer o contexto do SCM, e o start falha com "Cannot
        # start service" genérico, sem nenhum log/excecao Python
        # (SvcDoRun nunca chega a rodar; confirmado na pratica:
        # install/sc.exe config/"debug" funcionam, so' o start real via
        # SCM nao). Despacha direto pro SCM em vez de confiar nela.
        return _dispatch_or_explain()
    win32serviceutil.HandleCommandLine(DeepFreezerService)


if __name__ == "__main__":
    sys.exit(main())

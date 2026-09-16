#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deteccao de versao/edicao do Windows e escolha da estrategia de
protecao a nivel de SO (write filter nativo, fora do escopo do core
application-level do deepfreezer.py) mais adequada para a maquina.

Uso:
    python os_detect.py            # imprime um JSON com o resultado
    from os_detect import detect_strategy

Estrategias possiveis (campo "strategy" do resultado):
  "uwf"        -- Unified Write Filter (Windows 10/11 Enterprise,
                  Education ou IoT Enterprise). Nativo da Microsoft,
                  zero driver proprio; orquestrado via uwfmgr.exe.
  "ewf_fbwf"   -- Enhanced/File-Based Write Filter, os equivalentes do
                  UWF no Windows 7 Embedded Standard / POSReady.
                  Nativo, zero driver proprio; orquestrado via
                  ewfmgr.exe / fbwfmgr.exe.
  "vhdx_diff"  -- Nenhum write filter nativo disponivel (edicoes Home
                  ou Pro em qualquer versao, ou edicao nao
                  reconhecida). Unico caminho pra proteger a maquina
                  inteira nesse caso: disco diferencial VHDX no boot
                  -- exige reprovisionar a maquina, nao e' so instalar
                  um servico em cima do Windows ja instalado.
  "unsupported" -- versao do Windows fora do escopo suportado (mais
                  antiga que o Windows 7, ou Windows 8/8.1 -- nao
                  pedido no escopo atual), ou informacao insuficiente
                  pra decidir com seguranca.

Import seguro em qualquer SO: soh a leitura real (get_os_info) toca o
registro do Windows via winreg; classify() e' pura (recebe build +
edition ja lidos) e roda/testa em qualquer plataforma.

**Cobertura de EditionID nao e' garantida.** As listas abaixo cobrem
os valores documentados pela Microsoft (UWF) e os mais comuns de
imagens Windows 7 Embedded Standard/POSReady, mas variam por OEM e
versao de imagem. Qualquer EditionID nao reconhecido cai no fallback
seguro (vhdx_diff) -- este modulo nunca assume que um write filter
nativo existe sem casar com uma lista explicita. Isso NAO foi testado
contra Windows real (ambiente de desenvolvimento e' Linux); antes de
confiar em producao, rode `python os_detect.py` numa maquina Windows
de cada versao/edicao alvo e confira o resultado.
"""
import json
import sys

try:
    import winreg  # so' existe no Windows
except ImportError:
    winreg = None


# EditionID (registro HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion)
# -> tem Unified Write Filter nativo (Windows 10/11).
# Fonte: Microsoft Learn, pagina do UWF (Enterprise/Education/IoT
# Enterprise) -- https://learn.microsoft.com/windows/configuration/unified-write-filter/
_WIN10_11_NATIVE_EDITIONS = {
    "Enterprise", "EnterpriseN", "EnterpriseS", "EnterpriseSN",
    "Education", "EducationN",
    "IoTEnterprise", "IoTEnterpriseS", "IoTEnterpriseK", "IoTEnterpriseSK",
}

# EditionID -> tem EWF/FBWF nativo (Windows 7 Embedded Standard /
# POSReady). Lista mais incerta que a do UWF -- varia mais por OEM;
# tratar como ponto de partida, nao como fonte definitiva.
_WIN7_NATIVE_EDITIONS = {
    "Embedded", "EmbeddedStandard", "WindowsEmbeddedStandard",
    "PosReady", "POSReady",
}

# Build number -> versao, pros casos que nao caem limpo num intervalo
# (Windows 7 SP1 e Windows 8/8.1 estao todos abaixo de 10240).
_KNOWN_BUILDS = {
    7600: "7",      # Windows 7 RTM
    7601: "7",      # Windows 7 SP1
    9200: "8",      # Windows 8 -- fora do escopo suportado aqui
    9600: "8.1",    # Windows 8.1 -- fora do escopo suportado aqui
}


def get_os_info():
    """Le major build + EditionID reais da maquina via winreg. So'
    funciona no Windows; levanta RuntimeError fora dele (uso real e'
    sempre Windows -- deepfreezer_service.py so chama isso depois de
    _HAVE_PYWIN32 confirmar que estamos no Windows)."""
    if winreg is None:
        raise RuntimeError("get_os_info() so funciona no Windows (winreg indisponivel)")
    key = winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
    try:
        try:
            edition = winreg.QueryValueEx(key, "EditionID")[0]
        except OSError:
            edition = ""
        try:
            build = int(winreg.QueryValueEx(key, "CurrentBuildNumber")[0])
        except OSError:
            build = 0
        try:
            product_name = winreg.QueryValueEx(key, "ProductName")[0]
        except OSError:
            product_name = ""
    finally:
        winreg.CloseKey(key)
    return {"edition": edition, "build": build, "product_name": product_name}


def _windows_version_from_build(build):
    if build in _KNOWN_BUILDS:
        return _KNOWN_BUILDS[build]
    if build >= 22000:
        return "11"
    if 10240 <= build < 22000:
        return "10"
    if 0 < build < 7600:
        return "pre-7"
    return "desconhecida"


def classify(build, edition):
    """Pura -- so' recebe build number + EditionID ja lidos, sem tocar
    em registro/WMI. Testavel em qualquer plataforma."""
    version = _windows_version_from_build(build)

    if version in ("pre-7", "desconhecida"):
        return {"windows_version": version, "edition": edition,
                "strategy": "unsupported",
                "reason": "build number nao mapeado ou anterior ao Windows 7"}

    if version in ("8", "8.1"):
        return {"windows_version": version, "edition": edition,
                "strategy": "unsupported",
                "reason": "Windows 8/8.1 fora do escopo suportado (so' 7/10/11)"}

    if version in ("10", "11"):
        if edition in _WIN10_11_NATIVE_EDITIONS:
            return {"windows_version": version, "edition": edition,
                    "strategy": "uwf",
                    "reason": "edicao com Unified Write Filter nativo"}
        return {"windows_version": version, "edition": edition,
                "strategy": "vhdx_diff",
                "reason": "edicao Home/Pro (ou nao reconhecida) sem write filter nativo"}

    # version == "7"
    if edition in _WIN7_NATIVE_EDITIONS:
        return {"windows_version": "7", "edition": edition,
                "strategy": "ewf_fbwf",
                "reason": "edicao Embedded Standard/POSReady com EWF/FBWF nativo"}
    return {"windows_version": "7", "edition": edition,
            "strategy": "vhdx_diff",
            "reason": "edicao Home/Pro/Ultimate (ou nao reconhecida) sem write filter nativo"}


def detect_strategy():
    info = get_os_info()
    result = classify(info["build"], info["edition"])
    result["product_name"] = info["product_name"]
    result["build"] = info["build"]
    return result


if __name__ == "__main__":
    try:
        result = detect_strategy()
    except RuntimeError as e:
        result = {"windows_version": "n/a", "strategy": "unsupported",
                  "reason": str(e)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)

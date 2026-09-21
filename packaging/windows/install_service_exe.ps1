# Instala o DeepFreezer como servico Windows nativo a partir do
# deepfreezer_service.exe JA COMPILADO (baixado da pagina de
# Releases do GitHub) -- nao precisa de Python nem do repositorio
# clonado na maquina alvo.
#
# Use install_service_pywin32.ps1 em vez deste se voce tem Python +
# pywin32 instalados e prefere rodar a partir do codigo-fonte.
#
# Windows 7: baixe deepfreezer_service_win7.exe (nao o
# deepfreezer_service.exe normal) e renomeie pra
# deepfreezer_service.exe antes de rodar este script -- o binario
# padrao e' compilado com uma versao de Python que nao roda em
# Windows 7 (ver packaging/windows/README.md).
#
# Rodar em PowerShell elevado (Administrador).
#
# Uso:
#   coloque deepfreezer_service.exe na MESMA PASTA deste script, entao:
#   .\install_service_exe.ps1
#   .\install_service_exe.ps1 -Uninstall

param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "rode este script como Administrador"
}

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceExe    = Join-Path $ScriptDir "deepfreezer_service.exe"
$InstallDir   = "C:\Program Files\DeepFreezer"
$ConfigDir    = "C:\ProgramData\DeepFreezer"
$InstalledExe = Join-Path $InstallDir "deepfreezer_service.exe"

if ($Uninstall) {
    if (Get-Service -Name DeepFreezer -ErrorAction SilentlyContinue) {
        & $InstalledExe stop
    }
    & $InstalledExe remove

    # DeleteService() so' marca o servico "pendente de remocao" -- ele
    # some do SCM (Get-Service) um instante depois, nao na hora (visto
    # na pratica: um teste logo em seguida ainda enxergava o servico).
    # Espera ate 10s antes de dar como concluido.
    $deadline = (Get-Date).AddSeconds(10)
    while (Get-Service -Name DeepFreezer -ErrorAction SilentlyContinue) {
        if ((Get-Date) -gt $deadline) {
            throw "servico DeepFreezer ainda aparece no SCM 10s depois do remove"
        }
        Start-Sleep -Milliseconds 300
    }

    Write-Host "servico removido ($InstallDir preservado em disco)"
    exit 0
}

if (-not (Test-Path $SourceExe)) {
    throw ("deepfreezer_service.exe nao encontrado em $ScriptDir -- baixe da " +
        "pagina de Releases (https://github.com/c1c3ru/userfreezer/releases) " +
        "e coloque ao lado deste script antes de rodar")
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ConfigDir  | Out-Null

Copy-Item $SourceExe $InstallDir -Force

$TargetConfig = Join-Path $ConfigDir "config.json"
if (-not (Test-Path $TargetConfig)) {
    '{"targets": []}' | Set-Content -Path $TargetConfig -Encoding UTF8
    Write-Host "criado $TargetConfig vazio -- edite 'targets' antes de iniciar o servico"
}

& $InstalledExe install

# O servico so' fica visivel pro SCM um instante depois do "install"
# retornar (visto na pratica: sc.exe config logo em seguida falhava
# com "OpenService FAILED 1060" porque DeepFreezer ainda nao existia).
# Espera ate 10s antes de seguir pro sc.exe config.
$deadline = (Get-Date).AddSeconds(10)
while (-not (Get-Service -Name DeepFreezer -ErrorAction SilentlyContinue)) {
    if ((Get-Date) -gt $deadline) {
        throw "servico DeepFreezer nao apareceu no SCM 10s depois do install"
    }
    Start-Sleep -Milliseconds 300
}

& sc.exe config DeepFreezer obj= "LocalSystem"
& sc.exe config DeepFreezer start= auto

Write-Host "instalado. revise $TargetConfig e rode: Start-Service DeepFreezer"

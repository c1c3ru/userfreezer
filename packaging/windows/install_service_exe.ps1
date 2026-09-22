# Instala o DeepFreezer como servico Windows nativo a partir do
# deepfreezer_service.exe JA COMPILADO (baixado da pagina de
# Releases do GitHub) -- nao precisa de Python nem do repositorio
# clonado na maquina alvo.
#
# Use install_service_pywin32.ps1 em vez deste se voce tem Python +
# pywin32 instalados e prefere rodar a partir do codigo-fonte.
#
# Sao publicados dois .exe, um por familia de Windows:
#
#   deepfreezer_service_windows-10-11.exe   Windows 10 e 11
#   deepfreezer_service_windows-7-8.exe     Windows 7, 8 e 8.1
#
# Este script aceita qualquer um dos dois (e os nomes antigos
# deepfreezer_service.exe / deepfreezer_service_win7.exe, usados ate' a
# v0.1.6) -- NAO e' preciso renomear nada. Com os dois na mesma pasta,
# ele escolhe sozinho pelo Windows em que esta' rodando.
#
# Rodar em PowerShell elevado (Administrador).
#
# Uso:
#   coloque o .exe baixado na MESMA PASTA deste script, entao:
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
$InstallDir   = "C:\Program Files\DeepFreezer"
$ConfigDir    = "C:\ProgramData\DeepFreezer"
$InstalledExe = Join-Path $InstallDir "deepfreezer_service.exe"

# Primeiro build do Windows 10; tudo abaixo disso e' 8.1 ou mais velho.
$Win10FirstBuild = 10240

# Acha o .exe na pasta do script, aceitando os dois nomes publicados
# (um por familia de Windows) e os dois nomes antigos, usados ate' a
# v0.1.6. Com os dois atuais presentes, escolhe pelo build do Windows.
# O binario instalado sempre se chama deepfreezer_service.exe, venha de
# qual arquivo vier, pro -Uninstall nao depender de qual foi usado.
function Find-SourceExe {
    $modern = Join-Path $ScriptDir "deepfreezer_service_windows-10-11.exe"
    $legacy = Join-Path $ScriptDir "deepfreezer_service_windows-7-8.exe"

    $hasModern = Test-Path $modern
    $hasLegacy = Test-Path $legacy

    if ($hasModern -and $hasLegacy) {
        if ([Environment]::OSVersion.Version.Build -ge $Win10FirstBuild) {
            return $modern
        }
        return $legacy
    }
    if ($hasModern) { return $modern }
    if ($hasLegacy) { return $legacy }

    foreach ($antigo in @("deepfreezer_service.exe", "deepfreezer_service_win7.exe")) {
        $caminho = Join-Path $ScriptDir $antigo
        if (Test-Path $caminho) { return $caminho }
    }
    return $null
}

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

$SourceExe = Find-SourceExe
if (-not $SourceExe) {
    throw ("nenhum .exe do DeepFreezer encontrado em $ScriptDir -- baixe da " +
        "pagina de Releases (https://github.com/c1c3ru/userfreezer/releases) " +
        "e coloque ao lado deste script antes de rodar: " +
        "deepfreezer_service_windows-10-11.exe no Windows 10/11, " +
        "deepfreezer_service_windows-7-8.exe no Windows 7/8/8.1")
}

$NomeExe = Split-Path -Leaf $SourceExe
$Build   = [Environment]::OSVersion.Version.Build
Write-Host "usando $NomeExe (Windows build $Build)"

if ($NomeExe -eq "deepfreezer_service_windows-10-11.exe" -and $Build -lt $Win10FirstBuild) {
    Write-Warning ("este .exe e' compilado com Python 3.11 e provavelmente nao " +
        "inicia neste Windows -- baixe deepfreezer_service_windows-7-8.exe " +
        "e rode de novo se o servico nao subir")
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ConfigDir  | Out-Null

Copy-Item $SourceExe $InstalledExe -Force

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

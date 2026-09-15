# Instala o DeepFreezer como servico Windows via NSSM (https://nssm.cc),
# sem depender de pywin32. Requer nssm.exe no PATH. Rodar em PowerShell
# elevado (Administrador).
#
# Uso:
#   .\install_service_nssm.ps1 -PythonExe "C:\Python312\python.exe"
#   .\install_service_nssm.ps1 -Uninstall

param(
    [string]$PythonExe = "python.exe",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ServiceName = "DeepFreezer"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "rode este script como Administrador"
}

if ($Uninstall) {
    nssm stop $ServiceName
    nssm remove $ServiceName confirm
    Write-Host "servico $ServiceName removido (arquivos em disco preservados)"
    exit 0
}

$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot      = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$InstallDir    = "C:\Program Files\DeepFreezer"
$ConfigDir     = "C:\ProgramData\DeepFreezer"
$ServiceScript = Join-Path $InstallDir "deepfreezer_service.py"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ConfigDir  | Out-Null

Copy-Item (Join-Path $RepoRoot "deepfreezer.py") $InstallDir -Force
Copy-Item (Join-Path $ScriptDir "deepfreezer_service.py") $InstallDir -Force

$TargetConfig = Join-Path $ConfigDir "config.json"
if (-not (Test-Path $TargetConfig)) {
    Copy-Item (Join-Path $RepoRoot "packaging\config.example.json") $TargetConfig
    Write-Host "criado $TargetConfig a partir do exemplo -- edite 'targets' antes de iniciar o servico"
}

nssm install $ServiceName $PythonExe "`"$ServiceScript`" --foreground"
nssm set $ServiceName ObjectName LocalSystem
nssm set $ServiceName Start SERVICE_AUTO_START
nssm set $ServiceName AppNoConsole 1
nssm set $ServiceName DisplayName $ServiceName
nssm set $ServiceName Description "Retem o estado congelado das arvores de diretorio configuradas."

Start-Service $ServiceName
Write-Host "instalado e iniciado via NSSM. status: nssm status $ServiceName"

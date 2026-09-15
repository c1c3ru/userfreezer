# Instala o DeepFreezer como servico Windows nativo via pywin32.
# Requer Python 3 + pywin32 (pip install pywin32) no PATH do sistema.
# Rodar em PowerShell elevado (Administrador).
#
# Uso:
#   .\install_service_pywin32.ps1
#   .\install_service_pywin32.ps1 -Uninstall

param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "rode este script como Administrador"
}

$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot      = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$InstallDir    = "C:\Program Files\DeepFreezer"
$ConfigDir     = "C:\ProgramData\DeepFreezer"
$ServiceScript = Join-Path $InstallDir "deepfreezer_service.py"

if ($Uninstall) {
    python $ServiceScript stop
    python $ServiceScript remove
    Write-Host "servico removido ($InstallDir preservado em disco)"
    exit 0
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ConfigDir  | Out-Null

Copy-Item (Join-Path $RepoRoot "deepfreezer.py") $InstallDir -Force
Copy-Item (Join-Path $ScriptDir "deepfreezer_service.py") $InstallDir -Force

$TargetConfig = Join-Path $ConfigDir "config.json"
if (-not (Test-Path $TargetConfig)) {
    Copy-Item (Join-Path $RepoRoot "packaging\config.example.json") $TargetConfig
    Write-Host "criado $TargetConfig a partir do exemplo -- edite 'targets' antes de iniciar o servico"
}

python $ServiceScript install
& sc.exe config DeepFreezer obj= "LocalSystem"
& sc.exe config DeepFreezer start= auto

Write-Host "instalado. revise $TargetConfig e rode: Start-Service DeepFreezer"

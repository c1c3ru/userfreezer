# Instala o DeepFreezer como servico Windows nativo via pywin32.
# Mais facil: clique duas vezes em install.bat (pede elevacao sozinho
# e chama este script sem voce precisar abrir PowerShell). Rodar este
# .ps1 direto tambem funciona, mas precisa de PowerShell elevado e do
# prefixo ".\" (ex.: .\install_service_pywin32.ps1).
#
# Dois jeitos de funcionar, escolhidos automaticamente:
#  - pasta com deepfreezer_service.exe do lado (zip baixado da aba
#    Actions/Releases): usa o exe direto, nao precisa de Python
#    instalado na maquina.
#  - checkout do repositorio (sem o .exe do lado): usa
#    "python deepfreezer_service.py", requer 'pip install pywin32'.
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
    throw "rode como Administrador (ou clique duas vezes em install.bat, que pede elevacao sozinho)"
}

$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir    = "C:\Program Files\DeepFreezer"
$ConfigDir     = "C:\ProgramData\DeepFreezer"
$InstalledExe  = Join-Path $InstallDir "deepfreezer_service.exe"
$ServiceScript = Join-Path $InstallDir "deepfreezer_service.py"

function Invoke-Service {
    # Usa o que estiver de fato instalado em $InstallDir -- nao o que
    # esta ao lado do script (podem divergir se voce rodar -Uninstall
    # de uma pasta diferente da que usou pra instalar).
    param([string[]]$ServiceArgs)
    if (Test-Path $InstalledExe) {
        & $InstalledExe @ServiceArgs
    } else {
        & python $ServiceScript @ServiceArgs
    }
}

if ($Uninstall) {
    Invoke-Service -ServiceArgs @("stop")
    Invoke-Service -ServiceArgs @("remove")
    Write-Host "servico removido ($InstallDir preservado em disco)"
    exit 0
}

$BundledExe = Join-Path $ScriptDir "deepfreezer_service.exe"
$UseExe = Test-Path $BundledExe

if ($UseExe) {
    $ExampleConfig = Join-Path $ScriptDir "config.example.json"
} else {
    $RepoRoot      = Split-Path -Parent (Split-Path -Parent $ScriptDir)
    $ExampleConfig = Join-Path $RepoRoot "packaging\config.example.json"
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ConfigDir  | Out-Null

if ($UseExe) {
    Copy-Item $BundledExe $InstalledExe -Force
} else {
    Copy-Item (Join-Path $RepoRoot "deepfreezer.py") $InstallDir -Force
    Copy-Item (Join-Path $ScriptDir "deepfreezer_service.py") $InstallDir -Force
}

$TargetConfig = Join-Path $ConfigDir "config.json"
if (-not (Test-Path $TargetConfig)) {
    Copy-Item $ExampleConfig $TargetConfig
    Write-Host "criado $TargetConfig a partir do exemplo -- edite 'targets' antes de iniciar o servico"
}

Invoke-Service -ServiceArgs @("install")
& sc.exe config DeepFreezer obj= "LocalSystem"
& sc.exe config DeepFreezer start= auto

Write-Host "instalado. revise $TargetConfig e rode: Start-Service DeepFreezer"

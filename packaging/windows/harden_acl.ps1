# Restringe a ACL de um diretorio de overlay (<alvo>.dfreezer) a
# Administradores e SYSTEM, removendo heranca (inclui o acesso padrao
# do grupo Usuarios). Util para reaplicar o hardening manualmente, ja
# que deepfreezer_service.py faz isso automaticamente a cada start.
# Rodar em PowerShell elevado (Administrador).
#
# Uso: .\harden_acl.ps1 -OverlayPath "C:\lab\app.dfreezer"

param(
    [Parameter(Mandatory = $true)][string]$OverlayPath
)

$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "rode este script como Administrador"
}

if (-not (Test-Path $OverlayPath)) {
    throw "caminho nao encontrado: $OverlayPath"
}

# S-1-5-32-544 = BUILTIN\Administradores, S-1-5-18 = NT AUTHORITY\SYSTEM
# (SIDs bem-conhecidos, independentes do idioma do Windows instalado).
icacls $OverlayPath /inheritance:r `
    /grant:r "*S-1-5-32-544:(OI)(CI)F" `
    /grant:r "*S-1-5-18:(OI)(CI)F"

Write-Host "ACL restrita a Administradores e SYSTEM em $OverlayPath"

# Diagnostico SOMENTE LEITURA, Windows 7 / PowerShell 2.0+.
# NAO ativa UWF/EWF/FBWF, NAO altera BCD, particoes, discos ou volumes.
# Execute como Administrador em VM de teste, salve stdout para evidencia.
$ErrorActionPreference = "Stop"

Write-Host "=== DeepFreezer: inspecao somente leitura da protecao OS-level ==="
$osInfo = Get-WmiObject Win32_OperatingSystem
Write-Host ("SO: " + $osInfo.Caption + ", build " + $osInfo.BuildNumber)
Write-Host ("Arquitetura: " + $osInfo.OSArchitecture)

function Probe-Readonly {
    param([string] $Name, [string[]] $Arguments)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Write-Host ("[NAO INSTALADO] " + $Name)
        return
    }
    Write-Host ("--- " + $Name + " " + ($Arguments -join " ") + " ---")
    try {
        & $Name @Arguments 2>&1 | Out-Host
        Write-Host ("ExitCode: " + $LASTEXITCODE)
    } catch {
        Write-Warning ("Nao foi possivel consultar " + $Name + ": " + $_)
    }
}

# As consultas abaixo nao modificam estado. EWF/FBWF existem apenas em
# edicoes Embedded compativeis. Windows 7 comum NAO oferece UWF.
Probe-Readonly "uwfmgr.exe" @("filter", "get-config")
Probe-Readonly "ewfmgr.exe" @("C:")
Probe-Readonly "fbwfmgr.exe" @("/displayconfig")
# BCD listagem somente leitura; nao invocar /set, /delete ou bootrec.
Probe-Readonly "bcdedit.exe" @("/enum", "{current}")
Write-Host "=== Fim da inspecao. Nenhuma protecao foi ativada ou validada neste script. ==="

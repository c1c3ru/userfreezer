# UserFreezer: UWF native stage in an AUTHORISED, disposable Windows 10/11 VM.
# PowerShell 5.1+. Never enables UWF on Windows 7, Home or Pro.
# No internet, downloads, licensing checks, BCD writes, or reboot.
# Requires the UWF Windows optional feature to be ALREADY installed.
# Default invocation INSPECTS ONLY. A next-boot change requires 3 explicit
# switches and a real, distinct unprotected D: (or chosen) volume.
param(
    [switch]$Stage,
    [switch]$VerifyAfterReboot,
    [string]$ProtectedVolume = "C:",
    [string]$PersistentVolume = "D:",
    [switch]$ConfirmDisposableVM,
    [switch]$ConfirmBackupSnapshot,
    [switch]$ConfirmDiscardWritesAfterReboot
)

$ErrorActionPreference = "Stop"

function Assert-Drive([string] $drive) {
    if ($drive -cnotmatch '^[A-Za-z]:$') { throw "Volume invalido: use C: ou D:" }
    return $drive.ToUpperInvariant()
}

$ProtectedVolume = Assert-Drive $ProtectedVolume
$PersistentVolume = Assert-Drive $PersistentVolume
if ($ProtectedVolume -ne "C:") { throw "Esta etapa so aceita proteger o volume de sistema C:" }
if ($PersistentVolume -eq $ProtectedVolume) { throw "Dados persistentes exigem volume separado; nunca usar C:" }
if ($Stage -and $VerifyAfterReboot) { throw "-Stage e -VerifyAfterReboot sao mutuamente exclusivos" }

$build = [Environment]::OSVersion.Version.Build
if ($build -lt 10240) { throw "UWF nao suportado neste Windows; Win7 requer outro backend" }
$edition = ""
$reg = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey("SOFTWARE\Microsoft\Windows NT\CurrentVersion")
try {
    if ($null -eq $reg) { throw "Registro da edicao Windows nao encontrado" }
    $edition = [string]$reg.GetValue("EditionID", "")
} finally {
    if ($null -ne $reg) { $reg.Close() }
}
$allowed = @("Enterprise","EnterpriseN","EnterpriseS","EnterpriseSN",
             "Education","EducationN","IoTEnterprise","IoTEnterpriseS",
             "IoTEnterpriseK","IoTEnterpriseSK")
if ($allowed -notcontains $edition) {
    throw "Edicao $edition sem compatibilidade UWF comprovada; Windows Home/Pro nao suportado"
}
if ($env:SystemDrive.ToUpperInvariant() -ne $ProtectedVolume) {
    throw "Sistema nao esta em C:; escopo default inseguro"
}

$persistent = Get-WmiObject -Class Win32_LogicalDisk -Filter ("DeviceID='" + $PersistentVolume + "'")
if ($null -eq $persistent -or $persistent.DriveType -ne 3) {
    throw "Volume persistente nao existe ou nao e disco local fixo: $PersistentVolume"
}
if ($persistent.FileSystem -ne "NTFS") {
    throw "Para o laboratorio, o volume persistente separado deve ser NTFS"
}

$namespace = "root\standardcimv2\embedded"
$filter = @(Get-WmiObject -Namespace $namespace -Class UWF_Filter -ErrorAction Stop)
if ($filter.Count -ne 1) { throw "Filtro UWF nao instalado/consultavel de forma unica" }
$volumes = @(Get-WmiObject -Namespace $namespace -Class UWF_Volume -ErrorAction Stop)
$cNow = @($volumes | Where-Object { $_.DriveLetter -ieq $ProtectedVolume -and $_.CurrentSession -eq $true })
$cNext = @($volumes | Where-Object { $_.DriveLetter -ieq $ProtectedVolume -and $_.CurrentSession -eq $false })
$dEntries = @($volumes | Where-Object { $_.DriveLetter -ieq $PersistentVolume })
if ($cNow.Count -gt 1 -or $cNext.Count -gt 1) {
    throw "UWF possui entradas duplicadas para C:"
}
if (@($dEntries | Where-Object { $_.Protected -eq $true }).Count -ne 0) {
    throw "DADOS EM RISCO: volume persistente ja esta protegido em alguma sessao"
}

if ($Stage) {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Solicite elevacao administrativa/UAC antes da ativacao"
    }
    if (-not ($ConfirmDisposableVM -and $ConfirmBackupSnapshot -and $ConfirmDiscardWritesAfterReboot)) {
        throw "Exige VM descartavel, snapshot, consentimento expresso de descarte"
    }
    if ($filter[0].CurrentEnabled -or $filter[0].NextEnabled -or
        @($cNow | Where-Object { $_.Protected }).Count -ne 0 -or
        @($cNext | Where-Object { $_.Protected }).Count -ne 0) {
        throw "UWF ja alterado: recuse aplicar por cima de configuracao existente"
    }

    Write-Host "Preparando SOMENTE proxima sessao: C: protegido, D: persistente"
    $uwfmgr = Join-Path $env:WINDIR "System32\uwfmgr.exe"
    if (-not (Test-Path -LiteralPath $uwfmgr -PathType Leaf)) {
        throw "uwfmgr.exe indisponivel, recurso UWF nao instalado"
    }
    & $uwfmgr volume protect $ProtectedVolume
    if ($LASTEXITCODE -ne 0) {
        throw "UWF volume protect falhou: $LASTEXITCODE"
    }
    try {
        & $uwfmgr filter enable
        if ($LASTEXITCODE -ne 0) {
            throw "UWF filter enable falhou: $LASTEXITCODE"
        }
    } catch {
        # Best-effort rollback of our staging, NEVER claim rollback succeeded.
        try { & $uwfmgr volume unprotect $ProtectedVolume | Out-Null } catch { }
        throw "Ativacao incompleta; revise estado WMI manualmente antes de reiniciar. $($_.Exception.Message)"
    }
    Write-Host "Configuracao AGENDADA. Ainda NAO ativo ate reboot manual."
    Write-Host "Se nao desejar proteger, reverta antes do reboot com uwfmgr volume unprotect C: e uwfmgr filter disable."
}

# Always reread the native UWF provider rather than inferring protection
# from successfully running a command. No localization-dependent parsing.
$filter = @(Get-WmiObject -Namespace $namespace -Class UWF_Filter -ErrorAction Stop)
$volumes = @(Get-WmiObject -Namespace $namespace -Class UWF_Volume -ErrorAction Stop)
$cNow = @($volumes | Where-Object { $_.DriveLetter -ieq $ProtectedVolume -and $_.CurrentSession -eq $true })
$cNext = @($volumes | Where-Object { $_.DriveLetter -ieq $ProtectedVolume -and $_.CurrentSession -eq $false })
if ($cNow.Count -gt 1 -or $cNext.Count -gt 1 -or $filter.Count -ne 1) {
    throw "Estado UWF duplicado/invalido apos comando"
}
$current = ([bool]$filter[0].CurrentEnabled -and
            @($cNow | Where-Object { $_.Protected }).Count -eq 1)
$next = ([bool]$filter[0].NextEnabled -and
         @($cNext | Where-Object { $_.Protected }).Count -eq 1)
if ($Stage -and -not $next) { throw "UWF staging divergente; NAO reinicie sem inspecao" }
if ($VerifyAfterReboot -and -not $current) {
    throw "FAIL: filtro/volume nao estao ativos na sessao atual"
}
$state = if ($current) { "CURRENT_UWF_ENABLED_FOR_C" }
         elseif ($next) { "PENDING_REBOOT_NOT_PROTECTED_YET" }
         else { "NOT_PROTECTED" }

Write-Host "UWF STATE: $state"
Write-Host "PROTECTED VOLUME: C: / PERSISTENT VOLUME: $PersistentVolume"
Write-Host "PROVA DE ROLLBACK EXTERNO: NAO EXECUTADA."
Write-Host "O filtro ativo NAO substitui o teste Explorer/Desktop + segundo reboot."

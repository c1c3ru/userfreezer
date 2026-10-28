# Coleta de evidencias de descarte REAL de escrita externa apos reboot.
# Teste NAO destrutivo: somente cria arquivo de prova com GUID unico.
# PowerShell 2.0 / Windows 7 SP1, Windows 10/11. Nao altera boot/filtro.
#
# PRE-REQUISITOS: VM descartavel, snapshot, recurso de filtro ja configurado.
# EvidenceDir deve ser em volume persistente DIFERENTE do protegido ou
# numa exclusao comprovada pelo filtro.
#
# Preparar: .\vm_probe.ps1 -Prepare -ProbeRoot "C:\DF-Probe" -EvidenceDir "E:\evidencias"
# Reinicie manualmente a VM.
# Verificar: .\vm_probe.ps1 -VerifyAfterReboot -EvidenceDir "E:\evidencias"
param(
    [switch]$Prepare,
    [switch]$VerifyAfterReboot,
    [switch]$Cleanup,
    [string]$ProbeRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceDir,
    [switch]$EvidenceIsExcluded
)

$ErrorActionPreference = "Stop"
$modes = @($Prepare.IsPresent, $VerifyAfterReboot.IsPresent, $Cleanup.IsPresent)
if (($modes | Where-Object { $_ }).Count -ne 1) {
    throw "Escolha apenas -Prepare, -VerifyAfterReboot ou -Cleanup"
}
$evidenceAbs = [IO.Path]::GetFullPath($EvidenceDir)
if ($Prepare) {
    if (-not $ProbeRoot) { throw "-ProbeRoot obrigatorio ao preparar" }
    if (-not (Test-Path -LiteralPath $ProbeRoot -PathType Container)) {
        throw "Crie antes o diretorio ProbeRoot no volume protegido"
    }
    $probeAbs = [IO.Path]::GetFullPath($ProbeRoot)
    $probeVolume = [IO.Path]::GetPathRoot($probeAbs)
    $evVolume = [IO.Path]::GetPathRoot($evidenceAbs)
    if ($probeVolume -eq $evVolume -and -not $EvidenceIsExcluded) {
        throw "Evidencia no mesmo volume protegido sem -EvidenceIsExcluded; use outro volume"
    }
    if (-not (Test-Path -LiteralPath $evidenceAbs -PathType Container)) {
        throw "EvidenceDir persistente deve existir antes do teste"
    }
    $id = [Guid]::NewGuid().ToString("N")
    $marker = Join-Path $probeAbs ("deepfreezer-external-probe-" + $id + ".txt")
    $record = Join-Path $evidenceAbs "deepfreezer-probe-record.txt"
    if (Test-Path -LiteralPath $record) {
        throw "Evidencia antiga existe: $record. Verifique ou arquive antes de novo teste."
    }
    $os = Get-WmiObject Win32_OperatingSystem
    $ts = [DateTime]::UtcNow.ToString("o")
    $lines = @(
        "id=$id", "marker=$marker", "os=$($os.Caption)",
        "build=$($os.BuildNumber)", "start_utc=$ts",
        "evidence_dir=$evidenceAbs",
        "expected=marker_absent_after_reboot")
    [IO.File]::WriteAllLines($record, $lines,
                            (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText($marker, ("External write at " + $ts),
                           (New-Object Text.UTF8Encoding($false)))
    if (-not (Test-Path -LiteralPath $marker)) {
        throw "falha ao criar sentinela externa"
    }
    Write-Host "PREPARADO: $marker"
    Write-Host "Reinicie MANUALMENTE a VM; depois execute -VerifyAfterReboot."
    exit 0
}
$record = Join-Path $evidenceAbs "deepfreezer-probe-record.txt"
if (-not (Test-Path -LiteralPath $record -PathType Leaf)) {
    throw "Registro persistente nao existe: $record"
}
$data = @{}
foreach ($line in [IO.File]::ReadAllLines($record)) {
    $parts = $line.Split(@("="), 2)
    if ($parts.Length -eq 2) { $data[$parts[0]] = $parts[1] }
}
if (-not $data.ContainsKey("marker")) { throw "registro corrompido" }
$prefix = "deepfreezer-external-probe-"
if (-not ([IO.Path]::GetFileName($data["marker"]).StartsWith($prefix))) {
    throw "marker inseguro; abortando"
}
if ($VerifyAfterReboot) {
    $exists = Test-Path -LiteralPath $data["marker"]
    $os = Get-WmiObject Win32_OperatingSystem
    $status = if ($exists) { "FAIL_marker_persistiu" } else { "PASS_marker_descartado" }
    $ts = [DateTime]::UtcNow.ToString("o")
    $result = Join-Path $evidenceAbs "deepfreezer-probe-result.txt"
    [IO.File]::WriteAllLines($result, @(
        "id=$($data['id'])",
        "state=$status",
        "verified_utc=$ts",
        "os=$($os.Caption)",
        "build=$($os.BuildNumber)",
        "marker=$($data['marker'])"),
        (New-Object Text.UTF8Encoding($false)))
    Write-Host "RESULTADO: $status; evidencia: $result"
    if ($exists) {
        throw "FALHA: escrita externa persistiu; protecao OS-level NAO comprovada"
    }
    exit 0
}
if ($Cleanup) {
    # Remove SOMENTE sentinel criado por este teste; jamais reconfigura SO.
    if (Test-Path -LiteralPath $data["marker"]) {
        Remove-Item -LiteralPath $data["marker"] -Force
    }
    Write-Host "Limpeza da sentinela concluida. Evidencias preservadas."
    exit 0
}

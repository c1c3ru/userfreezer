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
    $bootUtc = [Management.ManagementDateTimeConverter]::ToDateTime(
        $os.LastBootUpTime).ToUniversalTime().ToString("o")
    $lines = @(
        "id=$id", "marker=$marker", "os=$($os.Caption)",
        "build=$($os.BuildNumber)", "start_utc=$ts",
        "boot_before_utc=$bootUtc",
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
if (-not $data.ContainsKey("marker") -or
    -not $data.ContainsKey("id") -or
    -not $data.ContainsKey("start_utc")) {
    throw "registro corrompido; ausencia de marker/id/start_utc"
}
if (-not ($data["id"] -match "^[0-9a-f]{32}$")) {
    throw "id GUID invalido"
}
$expectedName = "deepfreezer-external-probe-" + $data["id"] + ".txt"
if ([IO.Path]::GetFileName($data["marker"]) -cne $expectedName) {
    throw "marker nao corresponde ao GUID do registro"
}
if ($VerifyAfterReboot) {
    $os = Get-WmiObject Win32_OperatingSystem
    # A ausencia do arquivo so prova rollback se houve boot NOVO.
    # Caso contrario, exclusao manual/erro de preparo daria falso PASS.
    $bootUtc = [Management.ManagementDateTimeConverter]::ToDateTime(
        $os.LastBootUpTime).ToUniversalTime()
    $preparedUtc = [DateTime]::Parse(
        $data["start_utc"],
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
    if ($bootUtc -le $preparedUtc) {
        $result = Join-Path $evidenceAbs "deepfreezer-probe-result.txt"
        [IO.File]::WriteAllLines($result, @(
            "id=$($data['id'])", "state=FAIL_sem_reboot",
            "prepared_utc=$($preparedUtc.ToString('o'))",
            "observed_boot_utc=$($bootUtc.ToString('o'))"),
            (New-Object Text.UTF8Encoding($false)))
        throw "Reinicializacao NAO comprovada: boot anterior a Prepare; teste invalido"
    }
    $exists = Test-Path -LiteralPath $data["marker"]
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

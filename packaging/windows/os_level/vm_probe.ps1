# Coleta de evidencias de descarte REAL de escrita externa apos reboot.
# Teste NAO destrutivo: somente cria arquivo de prova com GUID unico.
# PowerShell 2.0 / Windows 7 SP1, Windows 10/11. Nao altera boot/filtro.
#
# PRE-REQUISITOS: VM descartavel, snapshot, recurso de filtro ja configurado.
# EvidenceDir deve ser em volume persistente DIFERENTE do protegido ou
# numa exclusao comprovada pelo filtro.
#
# Preparar: .\vm_probe.ps1 -Prepare -ProbeRoot "C:\DF-Probe" -EvidenceDir "E:\evidencias"
# Opcional: -ExcludedRoot "C:\DF-Excluido" (exclusao preconfigurada
# no mesmo volume protegido; deve persistir apos reboot)
# Reinicie manualmente a VM.
# Verificar: .\vm_probe.ps1 -VerifyAfterReboot -EvidenceDir "E:\evidencias"
param(
    [switch]$Prepare,
    [switch]$VerifyAfterReboot,
    [switch]$Cleanup,
    [string]$ProbeRoot,
    [string]$ExcludedRoot,
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
    $excludedAbs = $null
    if ($ExcludedRoot) {
        if (-not (Test-Path -LiteralPath $ExcludedRoot -PathType Container)) {
            throw "ExcludedRoot deve existir e ser uma exclusao real do filtro"
        }
        $excludedAbs = [IO.Path]::GetFullPath($ExcludedRoot)
        if ([IO.Path]::GetPathRoot($excludedAbs) -ne $probeVolume) {
            throw "ExcludedRoot deve estar no MESMO volume protegido"
        }
        if ($excludedAbs -eq $probeAbs -or
            $excludedAbs.StartsWith($probeAbs.TrimEnd("\\") + "\\",
                                     [StringComparison]::OrdinalIgnoreCase)) {
            throw "ExcludedRoot nao pode ficar dentro de ProbeRoot"
        }
    }
    $id = [Guid]::NewGuid().ToString("N")
    $marker = Join-Path $probeAbs ("deepfreezer-external-probe-" + $id + ".txt")
    $excludedMarker = $null
    if ($excludedAbs) {
        $excludedMarker = Join-Path $excludedAbs ("deepfreezer-excluded-probe-" + $id + ".txt")
    }
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
    if ($excludedMarker) {
        $lines += "excluded_marker=$excludedMarker"
        $lines += "expected_exclusion=excluded_marker_present_after_reboot"
    }
    [IO.File]::WriteAllLines($record, $lines,
                            (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText($marker, ("External write at " + $ts),
                           (New-Object Text.UTF8Encoding($false)))
    if (-not (Test-Path -LiteralPath $marker)) {
        throw "falha ao criar sentinela externa"
    }
    if ($excludedMarker) {
        [IO.File]::WriteAllText($excludedMarker, ("Excluded write at " + $ts),
                               (New-Object Text.UTF8Encoding($false)))
        if (-not (Test-Path -LiteralPath $excludedMarker)) {
            throw "falha ao criar sentinela da exclusao"
        }
        Write-Host "EXCLUSAO PREPARADA: $excludedMarker"
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
    # Compatibilidade com PowerShell 2.0/.NET: Split(array, 2) pode
    # resolver 2 como StringSplitOptions, causando erro de conversao.
    $pos = $line.IndexOf("=")
    if ($pos -gt 0) {
        $data[$line.Substring(0, $pos)] = $line.Substring($pos + 1)
    }
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
$hasExcluded = $data.ContainsKey("excluded_marker")
if ($hasExcluded) {
    $exName = "deepfreezer-excluded-probe-" + $data["id"] + ".txt"
    if ([IO.Path]::GetFileName($data["excluded_marker"]) -cne $exName) {
        throw "excluded_marker nao corresponde ao GUID do registro"
    }
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
    $excludedPresent = $false
    if ($hasExcluded) {
        $excludedPresent = Test-Path -LiteralPath $data["excluded_marker"]
    }
    if ($exists) {
        $status = "FAIL_marker_persistiu"
    } elseif ($hasExcluded -and -not $excludedPresent) {
        $status = "FAIL_exclusao_nao_persistiu"
    } elseif ($hasExcluded) {
        $status = "PASS_marker_descartado_exclusao_persistiu"
    } else {
        $status = "PASS_marker_descartado"
    }
    $ts = [DateTime]::UtcNow.ToString("o")
    $result = Join-Path $evidenceAbs "deepfreezer-probe-result.txt"
    $resultLines = @(
        "id=$($data['id'])",
        "state=$status",
        "verified_utc=$ts",
        "os=$($os.Caption)",
        "build=$($os.BuildNumber)",
        "marker=$($data['marker'])")
    if ($hasExcluded) {
        $resultLines += "excluded_marker=$($data['excluded_marker'])"
        $resultLines += "excluded_marker_present=$excludedPresent"
    }
    [IO.File]::WriteAllLines($result, $resultLines,
        (New-Object Text.UTF8Encoding($false)))
    Write-Host "RESULTADO: $status; evidencia: $result"
    if ($exists) {
        throw "FALHA: escrita externa persistiu; protecao OS-level NAO comprovada"
    }
    if ($hasExcluded -and -not $excludedPresent) {
        throw "FALHA: exclusao configurada NAO persistiu apos reboot"
    }
    exit 0
}
if ($Cleanup) {
    # Remove SOMENTE sentinel criado por este teste; jamais reconfigura SO.
    if (Test-Path -LiteralPath $data["marker"]) {
        Remove-Item -LiteralPath $data["marker"] -Force
    }
    if ($hasExcluded -and
        (Test-Path -LiteralPath $data["excluded_marker"])) {
        Remove-Item -LiteralPath $data["excluded_marker"] -Force
    }
    Write-Host "Limpeza das sentinelas concluida. Evidencias preservadas."
    exit 0
}

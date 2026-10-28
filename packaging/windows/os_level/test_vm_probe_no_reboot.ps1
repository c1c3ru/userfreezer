# Regression negativa: sem reboot REAL nao pode haver PASS.
# Windows PowerShell 5.1 CI; script sob teste mantem compativel PowerShell 2.
$ErrorActionPreference = "Stop"
$root = Join-Path $env:TEMP ("df-no-reboot-" + [guid]::NewGuid().ToString("N"))
$target = Join-Path $root "target"
$excluded = Join-Path $root "excluded"
$evidence = Join-Path $root "evidence"
$probe = Join-Path $PSScriptRoot "vm_probe.ps1"
New-Item -ItemType Directory -Force -Path $target, $evidence, $excluded | Out-Null
try {
    # A exclusao deve ser irma do alvo; nunca ficar dentro do proprio
    # diretorio de escrita protegida. Falha ANTES de criar sentinelas.
    $nested = Join-Path $target "nested"
    New-Item -ItemType Directory -Force -Path $nested | Out-Null
    $blocked = $false
    try {
        & $probe -Prepare -ProbeRoot $target -ExcludedRoot $nested -EvidenceDir $evidence -EvidenceIsExcluded
    } catch {
        if ($_.Exception.Message -notmatch "nao pode ficar dentro de ProbeRoot") { throw }
        $blocked = $true
    }
    if (-not $blocked) { throw "ExcludedRoot aninhado foi aceito indevidamente" }
    if (Test-Path (Join-Path $evidence "deepfreezer-probe-record.txt")) {
        throw "Probe criou evidencias mesmo rejeitando caminho aninhado"
    }
    & $probe -Prepare -ProbeRoot $target -ExcludedRoot $excluded -EvidenceDir $evidence -EvidenceIsExcluded
    $excludedMarker = Get-ChildItem -LiteralPath $excluded -Filter "deepfreezer-excluded-probe-*.txt"
    if (@($excludedMarker).Count -ne 1) {
        throw "sentinela da exclusao nao foi criada"
    }
    $record = Get-Content (Join-Path $evidence "deepfreezer-probe-record.txt")
    $markerLine = @($record | Where-Object { $_.StartsWith("marker=") })[0]
    if (-not $markerLine) { throw "marker nao foi gravado" }
    $marker = $markerLine.Substring(7)
    if (-not (Test-Path -LiteralPath $marker)) {
        throw "arquivo externo de prova nao foi criado"
    }
    # Exclui sentinela para reproduzir o antigo falso positivo.
    Remove-Item -LiteralPath $marker -Force
    $failed = $false
    try {
        & $probe -VerifyAfterReboot -EvidenceDir $evidence
    } catch {
        if ($_.Exception.Message -notmatch "Reinicializacao NAO comprovada") {
            throw
        }
        $failed = $true
    }
    if (-not $failed) { throw "Falhou aberto: aceitou rollback SEM reboot" }
    $result = Get-Content (Join-Path $evidence "deepfreezer-probe-result.txt") -Raw
    if ($result -notmatch "state=FAIL_sem_reboot") {
        throw "Resultado FAIL_sem_reboot nao foi preservado"
    }
    Write-Host "OK: VM probe recusa falso positivo sem reboot real"
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}

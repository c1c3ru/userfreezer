# Regression negativa: sem reboot REAL nao pode haver PASS.
# Windows PowerShell 5.1 CI; script sob teste mantem compativel PowerShell 2.
$ErrorActionPreference = "Stop"
$root = Join-Path $env:TEMP ("df-no-reboot-" + [guid]::NewGuid().ToString("N"))
$target = Join-Path $root "target"
$evidence = Join-Path $root "evidence"
$probe = Join-Path $PSScriptRoot "vm_probe.ps1"
New-Item -ItemType Directory -Force -Path $target, $evidence | Out-Null
try {
    & $probe -Prepare -ProbeRoot $target -EvidenceDir $evidence -EvidenceIsExcluded
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

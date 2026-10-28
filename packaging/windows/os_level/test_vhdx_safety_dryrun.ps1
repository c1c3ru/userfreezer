# Negative-only VHDX test. No diskpart, bcdboot, DISM or boot changes.
$ErrorActionPreference = "Stop"
$root = Join-Path $env:TEMP ("df-vhdx-safe-" + [Guid]::NewGuid().ToString("N"))
$script = Join-Path $PSScriptRoot "vhdx_diff_reset.ps1"
New-Item -ItemType Directory -Path $root -Force | Out-Null
try {
    $base = Join-Path $root "base.vhdx"
    $diff = Join-Path $root "diff.vhdx"
    [IO.File]::WriteAllText($base, "dummy-base")
    [IO.File]::WriteAllText($diff, "DO-NOT-DELETE")
    & $script -VhdDir $root -BootDisk "S:"
    if ($LASTEXITCODE -ne 0) { throw "dry-run falhou" }
    if ([IO.File]::ReadAllText($diff) -ne "DO-NOT-DELETE") {
        throw "dry-run alterou o diferencial"
    }
    if (Test-Path "HKLM:\SYSTEM\CurrentControlSet\Control\MiniNT") {
        throw "O runner aparenta ser WinPE; teste de negativa inseguro"
    }
    $rejected = $false
    try {
        & $script -VhdDir $root -BootDisk "S:" -IAcceptTheRisk
    } catch {
        if ($_.Exception.Message -notmatch "somente em WinPE") { throw }
        $rejected = $true
    }
    if (-not $rejected) { throw "reset foi aceito fora do WinPE" }
    if ([IO.File]::ReadAllText($diff) -ne "DO-NOT-DELETE") {
        throw "reset inseguro alterou o diferencial"
    }
    Write-Host "OK: dry-run e WinPE gate preservaram o disco de prova"
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}

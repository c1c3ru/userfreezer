# Consulta somente leitura, compativel com PowerShell 2.0 / Windows 7.
# Execute como Administrador: o status inclui caminhos de alvos protegidos.
$ErrorActionPreference = "Stop"
$StatusFile = Join-Path $env:ProgramData "DeepFreezer\status.json"
if (-not (Test-Path -LiteralPath $StatusFile)) {
    throw "Sem snapshot de enforcement em $StatusFile. Inicie o servico e confira os logs."
}
Write-Host "Relatorio do ultimo enforcement (application-level; nao e protecao do SO):"
[System.IO.File]::ReadAllText($StatusFile, [System.Text.Encoding]::UTF8)

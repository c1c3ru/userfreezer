# Roda os_detect.py, mostra a estrategia de protecao a nivel de SO
# escolhida pra esta maquina, e aponta pro script certo em
# packaging/windows/os_level/ -- nunca executa nada por conta propria
# (as estrategias uwf/ewf_fbwf sao razoavelmente seguras/reversiveis
# via reboot, mas vhdx_diff reconfigura o boot e exige decisoes
# manuais -- ver vhdx_diff_setup.ps1 -- entao a decisao final e' sempre
# do operador, nunca automatica).
#
# Uso (nao precisa ser Administrador so' pra consultar):
#   .\select_strategy.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$OsDetect = Join-Path (Split-Path -Parent $ScriptDir) "os_detect.py"

if (-not (Test-Path $OsDetect)) {
    throw "os_detect.py nao encontrado em $OsDetect"
}

$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python3.exe -ErrorAction SilentlyContinue
}
if (-not $python) {
    throw "python.exe/python3.exe nao encontrado no PATH"
}

$json = & $python.Source $OsDetect
$info = $json | ConvertFrom-Json

Write-Host ""
Write-Host "Windows $($info.windows_version) -- edicao '$($info.edition)' ($($info.product_name), build $($info.build))"
Write-Host "Estrategia: $($info.strategy)"
Write-Host "Motivo: $($info.reason)"
Write-Host ""

switch ($info.strategy) {
    "uwf" {
        Write-Host "Proximo passo: .\uwf_setup.ps1 -Install  (depois -Protect, -Enable -- ver comentarios no topo do arquivo)"
    }
    "ewf_fbwf" {
        Write-Host "Proximo passo: .\ewf_fbwf_setup.ps1 -Status  (depois -Protect, -Enable -- ver comentarios no topo do arquivo)"
    }
    "vhdx_diff" {
        Write-Host ("Proximo passo: .\vhdx_diff_setup.ps1 -- ATENCAO, e' a operacao mais " +
            "arriscada do projeto (reconfigura o boot da maquina). Leia os comentarios " +
            "no topo do arquivo por inteiro antes de rodar, e valide numa VM descartavel " +
            "primeiro.") -ForegroundColor Yellow
    }
    default {
        Write-Host ("Nenhuma estrategia automatizada disponivel para esta maquina " +
            "($($info.windows_version) / $($info.edition)). Ver packaging/windows/README.md.") -ForegroundColor Yellow
    }
}
Write-Host ""

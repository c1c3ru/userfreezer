# Diagnostico somente leitura de protecao em VM Windows 7+.
# Compatibilidade Windows PowerShell 2.0 / Windows 7 SP1.
# NAO altera sistema, registro, filtro, volume, BCD, alvos ou arquivos.
param()
$ErrorActionPreference = "Stop"
Write-Host "=== UserFreezer: diagnostico de protecao contra gravacoes externas ==="
$svc = Get-Service -Name DeepFreezer -ErrorAction SilentlyContinue
if ($null -eq $svc) {
    Write-Host "SERVICO: AUSENTE. Executavel isolado nao instala ou ativa o servico."
} else {
    Write-Host ("SERVICO: " + $svc.Status + " (somente status SCM, nao protecao de disco)")
}
try {
    $os = Get-WmiObject -Class Win32_OperatingSystem
    Write-Host ("WINDOWS: " + $os.Caption + " / versao " + $os.Version)
} catch {
    Write-Warning "Nao foi possivel ler a edicao Windows via WMI"
}
$config = Join-Path $env:ProgramData "DeepFreezer\config.json"
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
    Write-Host "CONFIGURACAO: AUSENTE; nenhum alvo confirmado."
} else {
    try {
        # PS 2.0 nao possui ConvertFrom-Json. A API de .NET 3.5 e usada
        # quando disponivel. Uma falha de parse NUNCA vira 'configurado'.
        Add-Type -AssemblyName System.Web.Extensions
        $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $json = [System.IO.File]::ReadAllText($config)
        $obj = $serializer.DeserializeObject($json)
        $targets = $obj["targets"]
        if (($null -eq $targets) -or ($targets.Count -eq 0)) {
            Write-Host "CONFIGURACAO: SEM ALVOS (targets vazio). Nenhuma pasta configurada."
        } else {
            Write-Host ("CONFIGURACAO: " + $targets.Count + " alvo(s) declarado(s).")
            Write-Host "ATENCAO: alvos configurados protegem somente chamadas da API do UserFreezer."
        }
    } catch {
        Write-Warning "CONFIGURACAO: nao foi possivel verificar lista de alvos; estado DESCONHECIDO."
    }
}
$status = Join-Path $env:ProgramData "DeepFreezer\status.json"
if (Test-Path -LiteralPath $status -PathType Leaf) {
    Write-Host "STATUS: existe status.json; verifique protection_scope (application-level)."
} else {
    Write-Host "STATUS: status.json ausente; enforcement nao comprovado."
}
Write-Host ""
Write-Host "PROTECAO DE GRAVACOES DO EXPLORER/DESKTOP: NAO COMPROVADA PELO SERVICO."
Write-Host "Win7 comum: sem UWF; EWF/FBWF somente quando realmente fornecidos pelo Embedded."
Write-Host "Windows 10/11: UWF somente em edicoes compativeis e quando habilitado."
$uwf = Get-Command uwfmgr.exe -ErrorAction SilentlyContinue
if ($null -ne $uwf) {
    Write-Host "UWF: utilitario encontrado; consultar configuracao atual (somente leitura)."
    & uwfmgr.exe filter get-config
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Consulta UWF falhou; filtro NAO verificado."
    }
} else {
    Write-Host "UWF: utilitario ausente; protecao UWF NAO confirmada."
}
Write-Host ""
Write-Host "RESULTADO: nao considerar a maquina protegida apenas porque DeepFreezer esta Running."
Write-Host "Teste externo exige filtro OS-level ativo no volume da Area de Trabalho, reboot e prova."

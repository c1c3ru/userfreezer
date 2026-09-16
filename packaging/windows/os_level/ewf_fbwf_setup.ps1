# Orquestra o Enhanced Write Filter (EWF) ou o File-Based Write Filter
# (FBWF) do Windows 7 -- os equivalentes do UWF (ver uwf_setup.ps1)
# nas edicoes embarcadas do Windows 7 (Embedded Standard / POSReady).
# So' funcionam se o componente EWF ou FBWF foi incluido na imagem
# original da maquina (nao vem em Windows 7 Home/Pro/Ultimate normal).
#
# Rode packaging\windows\os_detect.py antes pra confirmar que
# "ewf_fbwf" e' a estrategia certa pra esta maquina -- se der
# "vhdx_diff", este script nao serve, ver vhdx_diff_setup.ps1.
#
# ESTE E' O CAMINHO MENOS VERIFICADO DE TODOS. O repositorio foi
# desenvolvido num sandbox Linux (sem Windows 7 real, sem ewfmgr.exe/
# fbwfmgr.exe de verdade), Windows 7 esta fora de suporte da Microsoft
# desde 2020, e a documentacao oficial do EWF/FBWF e' antiga e mais
# escassa que a do UWF -- so' os comandos abaixo foram confirmados
# contra a documentacao (ver packaging/windows/README.md pros links);
# qualquer coisa alem disso, rode "ewfmgr /?" ou "fbwfmgr /?" na
# propria maquina antes de confiar. NUNCA rode isto pela primeira vez
# numa maquina de producao -- valide numa VM descartavel da mesma
# imagem primeiro.
#
# Cada acao (exceto -Status) so' entra em vigor na PROXIMA sessao,
# depois de reiniciar. -Disable e' a saida de emergencia.
#
# Rodar em PowerShell elevado (Administrador).
#
# Uso:
#   .\ewf_fbwf_setup.ps1 -Status                               # mostra qual filtro existe e o estado do volume
#   .\ewf_fbwf_setup.ps1 -Protect C:                            # protege o volume (EWF) ou adiciona o volume (FBWF)
#   .\ewf_fbwf_setup.ps1 -Exclude "C:\ProgramData\DeepFreezer"  # exclui um caminho (so' funciona com FBWF -- EWF nao tem exclusao nativa de pasta)
#   .\ewf_fbwf_setup.ps1 -Enable                                # ativa o filtro pra proxima sessao (pede reboot)
#   .\ewf_fbwf_setup.ps1 -Disable                               # desativa o filtro pra proxima sessao (saida de emergencia)

param(
    [switch]$Status,
    [string]$Protect,
    [string]$Exclude,
    [switch]$Enable,
    [switch]$Disable
)

$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "rode este script como Administrador"
}

$acoes = @($Status.IsPresent, [bool]$Protect, [bool]$Exclude, $Enable.IsPresent, $Disable.IsPresent)
if (($acoes | Where-Object { $_ }).Count -eq 0) {
    Write-Host "nenhuma acao especificada -- ver comentarios no topo do arquivo para o uso"
    exit 1
}
if (($acoes | Where-Object { $_ }).Count -gt 1) {
    throw "especifique uma acao por vez (-Status, -Protect, -Exclude, -Enable ou -Disable)"
}

function Get-FiltroDisponivel {
    # Prefere EWF (paridade mais proxima do UWF: filtro de volume
    # inteiro) quando os dois estao presentes; cai pra FBWF senao.
    if (Get-Command ewfmgr.exe -ErrorAction SilentlyContinue) { return "ewf" }
    if (Get-Command fbwfmgr.exe -ErrorAction SilentlyContinue) { return "fbwf" }
    throw ("nem ewfmgr.exe nem fbwfmgr.exe encontrados no PATH -- esta imagem do " +
        "Windows 7 provavelmente nao inclui o componente EWF/FBWF (comum fora das " +
        "edicoes Embedded Standard/POSReady)")
}

$filtro = Get-FiltroDisponivel
Write-Host "filtro detectado: $filtro"

if ($Status) {
    if ($filtro -eq "ewf") {
        & ewfmgr.exe c:
    } else {
        Write-Host "fbwfmgr nao tem um subcomando de status confirmado neste script -- rode 'fbwfmgr /?' na maquina para ver as opcoes exatas desta imagem"
    }
    exit 0
}

if ($Protect) {
    if ($filtro -eq "ewf") {
        Write-Host "protegendo $Protect via EWF (so' entra em vigor com -Enable + reboot)..."
        & ewfmgr.exe $Protect -enable
    } else {
        Write-Host "adicionando $Protect a protecao FBWF (so' entra em vigor com -Enable + reboot)..."
        & fbwfmgr.exe /addvolume $Protect
    }
    Write-Host "marcado. rode -Enable e reinicie pra ativar de verdade."
    exit 0
}

if ($Exclude) {
    if ($filtro -eq "ewf") {
        throw ("EWF protege o volume inteiro sem um comando nativo de exclusao de " +
            "pasta equivalente ao do UWF/FBWF -- se voce precisa excluir um caminho " +
            "(ex.: logs), use FBWF nesta maquina, ou consulte a documentacao do EWF " +
            "para 'persist' antes de assumir que da pra fazer isso")
    }
    if (-not (Test-Path $Exclude)) {
        throw "caminho de exclusao nao encontrado: $Exclude"
    }
    $volume = (Split-Path -Qualifier $Exclude)
    $relativo = $Exclude.Substring($volume.Length)
    Write-Host "excluindo $Exclude da protecao FBWF (persiste entre reboots)..."
    & fbwfmgr.exe /addexclusion $volume $relativo
    exit 0
}

if ($Enable) {
    Write-Host ("ATENCAO: ativando o filtro para a proxima sessao. Depois de " +
        "reiniciar, toda gravacao no volume protegido vira provisoria e sera " +
        "descartada no boot seguinte. Se algo der errado, rode -Disable e " +
        "reinicie de novo para reverter.") -ForegroundColor Yellow
    if ($filtro -eq "ewf") {
        & ewfmgr.exe -all -enable
    } else {
        & fbwfmgr.exe /enable
    }
    Write-Host "ativado para a proxima sessao. reinicie a maquina para entrar em vigor."
    exit 0
}

if ($Disable) {
    Write-Host "desativando o filtro para a proxima sessao (saida de emergencia)..."
    if ($filtro -eq "ewf") {
        & ewfmgr.exe -all -disable
    } else {
        & fbwfmgr.exe /disable
    }
    Write-Host "desativado para a proxima sessao. reinicie a maquina para entrar em vigor."
    exit 0
}

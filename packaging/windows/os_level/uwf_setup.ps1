# Orquestra o Unified Write Filter (UWF) do Windows -- protecao a
# nivel de SO que intercepta TODA gravacao no volume protegido
# (Explorer, qualquer programa), redirecionando pra um overlay
# descartado no proximo boot. E' o recurso nativo da Microsoft mais
# proximo do Deep Freeze comercial.
#
# So' existe em Windows 10/11 Enterprise, Education ou IoT Enterprise
# (nao em Home/Pro). Rode packaging\windows\os_detect.py antes pra
# confirmar que "uwf" e' a estrategia certa pra esta maquina -- se der
# "vhdx_diff", este script nao serve, ver vhdx_diff_setup.ps1.
#
# NAO TESTADO EM MAQUINA WINDOWS REAL -- este repositorio foi
# desenvolvido num sandbox Linux, sem acesso a uwfmgr.exe de verdade.
# A sintaxe dos comandos foi conferida contra a documentacao da
# Microsoft (ver packaging/windows/README.md pros links), mas NUNCA
# rode isto pela primeira vez numa maquina de producao -- valide numa
# VM Windows descartavel da mesma versao/edicao primeiro.
#
# Cada acao abaixo (exceto -Status) so' entra em vigor na PROXIMA
# sessao, depois de reiniciar -- uwfmgr.exe nunca aplica nada na
# sessao atual. -Disable e' a saida de emergencia se -Enable causar
# algum problema: some com o efeito no proximo reboot, igual habilitar.
#
# Rodar em PowerShell elevado (Administrador).
#
# Uso:
#   .\uwf_setup.ps1 -Install                                  # instala o feature opcional (pede reboot)
#   .\uwf_setup.ps1 -Protect C:                                # marca C: para protecao (so' com -Enable + reboot)
#   .\uwf_setup.ps1 -Exclude "C:\ProgramData\DeepFreezer"      # exclui um caminho (logs, config) da protecao
#   .\uwf_setup.ps1 -Enable                                    # ativa o filtro pra proxima sessao (pede reboot)
#   .\uwf_setup.ps1 -Disable                                   # desativa o filtro pra proxima sessao (saida de emergencia)
#   .\uwf_setup.ps1 -Status                                    # mostra a config atual e a da proxima sessao

param(
    [switch]$Install,
    [string]$Protect,
    [string]$Exclude,
    [switch]$Enable,
    [switch]$Disable,
    [switch]$Status
)

$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "rode este script como Administrador"
}

$acoes = @($Install.IsPresent, [bool]$Protect, [bool]$Exclude, $Enable.IsPresent, $Disable.IsPresent, $Status.IsPresent)
if (($acoes | Where-Object { $_ }).Count -eq 0) {
    Write-Host "nenhuma acao especificada -- ver comentarios no topo do arquivo para o uso"
    exit 1
}
if (($acoes | Where-Object { $_ }).Count -gt 1) {
    throw "especifique uma acao por vez (-Install, -Protect, -Exclude, -Enable, -Disable ou -Status)"
}

function Test-UwfmgrDisponivel {
    if (-not (Get-Command uwfmgr.exe -ErrorAction SilentlyContinue)) {
        throw "uwfmgr.exe nao encontrado no PATH -- rode '.\uwf_setup.ps1 -Install', reinicie, e tente de novo"
    }
}

if ($Install) {
    Write-Host "instalando o feature opcional Client-UnifiedWriteFilter..."
    Enable-WindowsOptionalFeature -Online -FeatureName "Client-UnifiedWriteFilter" -All -NoRestart
    Write-Host "feature instalado. reinicie a maquina (Restart-Computer) antes de usar -Protect/-Enable."
    exit 0
}

if ($Status) {
    Test-UwfmgrDisponivel
    & uwfmgr.exe get-config
    exit 0
}

if ($Protect) {
    Test-UwfmgrDisponivel
    Write-Host "marcando $Protect para protecao UWF (so' entra em vigor com -Enable + reboot)..."
    & uwfmgr.exe volume protect $Protect
    Write-Host "marcado. rode -Enable e reinicie pra ativar de verdade."
    exit 0
}

if ($Exclude) {
    Test-UwfmgrDisponivel
    if (-not (Test-Path $Exclude)) {
        throw "caminho de exclusao nao encontrado: $Exclude"
    }
    Write-Host "excluindo $Exclude da protecao UWF (esse caminho continua gravando normal, persiste entre reboots)..."
    & uwfmgr.exe file add-exclusion $Exclude
    exit 0
}

if ($Enable) {
    Test-UwfmgrDisponivel
    Write-Host ("ATENCAO: ativando o filtro UWF para a proxima sessao. Depois de " +
        "reiniciar, toda gravacao no(s) volume(s) protegido(s) vira provisoria e " +
        "sera descartada no boot seguinte. Se algo der errado, rode -Disable e " +
        "reinicie de novo para reverter.") -ForegroundColor Yellow
    & uwfmgr.exe filter enable
    Write-Host "ativado para a proxima sessao. reinicie (Restart-Computer) para entrar em vigor."
    exit 0
}

if ($Disable) {
    Test-UwfmgrDisponivel
    Write-Host "desativando o filtro UWF para a proxima sessao (saida de emergencia)..."
    & uwfmgr.exe filter disable
    Write-Host "desativado para a proxima sessao. reinicie (Restart-Computer) para entrar em vigor."
    exit 0
}

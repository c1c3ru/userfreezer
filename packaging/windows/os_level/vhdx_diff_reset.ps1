# Recria diff.vhdx a partir de base.vhdx -- descarta qualquer
# gravacao feita durante a sessao anterior, "resetando" a maquina pro
# estado congelado. E' o equivalente a nivel de disco inteiro do que
# enforce_all() em deepfreezer_service.py ja faz a nivel de aplicacao
# (thaw sem commit + freeze) a cada start do servico.
#
# ============================================================
#  TEM QUE RODAR FORA DO WINDOWS QUE ESTA SENDO RESETADO.
#  Nao da pra apagar/recriar o disco que voce esta usando AGORA MESMO
#  pra rodar este script -- ele tem que rodar de um ambiente separado
#  (WinPE, midia de recuperacao) apontando pro disco da maquina alvo.
# ============================================================
#
# Onde rodar isso, na pratica (nenhuma das duas opcoes foi
# automatizada aqui -- ver "O QUE FALTA" no final deste comentario):
#   a) manualmente, booted numa midia WinPE/de recuperacao (ex.:
#      "reagentc /boottore" na maquina alvo + reiniciar pra WinRE, ou
#      um pendrive de instalacao do Windows);
#   b) um "boot de manutencao" dedicado no menu do BCD (bcdedit
#      /displayorder), que o admin escolhe explicitamente antes de
#      reiniciar de volta pro modo normal.
#
# NAO TESTADO EM MAQUINA REAL -- desenvolvido num sandbox Linux, sem
# acesso a diskpart/bcdboot de verdade. Valide numa VM descartavel
# antes de usar em producao.
#
# Rodar em PowerShell elevado (Administrador), de dentro do ambiente
# de manutencao/WinPE -- nunca a partir do proprio diff.vhdx que sera
# substituido.
#
# Uso:
#   .\vhdx_diff_reset.ps1 -VhdDir V:\DeepFreezerVHD -BootDisk S:
#
# Parametros:
#   -VhdDir     pasta onde base.vhdx e diff.vhdx moram (a mesma usada em vhdx_diff_setup.ps1)
#   -BootDisk   letra da particao EFI System (ESP) da maquina alvo, ja montada neste ambiente
#
# O QUE FALTA (nao implementado nem validado ainda):
#   Automatizar o boot no passo (a)/(b) acima, pra esse reset rodar
#   sozinho a cada ciclo em vez de precisar de um passo manual do
#   admin. Isso exigiria customizar a imagem do WinRE (winpeshl.ini ou
#   uma tarefa agendada dentro dela) pra chamar este script sozinha no
#   boot -- e' a parte mais arriscada e menos documentada de todo o
#   processo (um erro na imagem de recuperacao pode quebrar a
#   recuperacao embutida do Windows tambem), entao ficou de fora
#   deliberadamente ate dar pra validar em hardware real.

param(
    [string]$VhdDir = "V:\DeepFreezerVHD",
    [Parameter(Mandatory = $true)][string]$BootDisk
)

$ErrorActionPreference = "Stop"

$BasePath = Join-Path $VhdDir "base.vhdx"
$DiffPath = Join-Path $VhdDir "diff.vhdx"

if (-not (Test-Path $BasePath)) {
    throw "base.vhdx nao encontrado em $VhdDir -- confirme -VhdDir (ele deveria ter sido criado por vhdx_diff_setup.ps1)"
}

function Invoke-Diskpart {
    # Roda um script diskpart a partir de uma string multi-linha --
    # diskpart /s exige um ARQUIVO, entao isso grava num temporario,
    # roda, e sempre limpa depois (mesmo se der erro no meio).
    param([Parameter(Mandatory = $true)][string]$Script)
    $tmp = New-TemporaryFile
    try {
        Set-Content -Path $tmp -Value $Script -Encoding ASCII
        & diskpart.exe /s $tmp.FullName
        if ($LASTEXITCODE -ne 0) {
            throw "diskpart terminou com codigo $LASTEXITCODE -- veja a saida acima"
        }
    } finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
}

if (Test-Path $DiffPath) {
    Write-Host "descartando diff.vhdx da sessao anterior..."
    Remove-Item $DiffPath -Force
}

Write-Host "criando novo diff.vhdx (filho de base.vhdx)..."
Invoke-Diskpart @"
create vdisk file="$DiffPath" parent="$BasePath"
select vdisk file="$DiffPath"
attach vdisk
assign letter=W
"@

Write-Host "repontando o boot para o diff.vhdx novo..."
& bcdboot.exe W:\Windows /s $BootDisk /f UEFI

Invoke-Diskpart @"
select vdisk file="$DiffPath"
detach vdisk
"@

Write-Host "reset concluido -- o proximo boot normal usa o diff.vhdx novo (estado limpo)." -ForegroundColor Green

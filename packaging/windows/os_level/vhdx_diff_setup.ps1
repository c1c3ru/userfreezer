# Provisiona uma maquina pra bootar nativamente de um VHDX diferencial
# (native boot to VHD) -- o unico caminho pra proteger o DISCO INTEIRO
# contra qualquer gravacao em edicoes Windows sem write filter nativo
# (Home/Pro, em qualquer versao -- ver os_detect.py; se der "uwf" ou
# "ewf_fbwf", use uwf_setup.ps1 / ewf_fbwf_setup.ps1 em vez deste).
#
# ============================================================
#  ESTA E A OPERACAO MAIS ARRISCADA DE TODO O PROJETO.
#  Reconfigura como a maquina inicializa. Um erro aqui pode deixar a
#  maquina sem bootar, exigindo reinstalacao completa a partir de
#  midia -- nao existe undo automatico.
# ============================================================
#
# NAO TESTADO EM MAQUINA REAL. Desenvolvido num sandbox Linux, sem
# acesso a diskpart/dism/bcdboot de verdade -- a sequencia de comandos
# foi conferida contra a documentacao da Microsoft (ver
# packaging/windows/README.md pros links), mas cada ambiente
# (BIOS/UEFI, layout de disco existente, versao do install.wim) tem
# particularidades que este script sozinho nao cobre. So' cobre o
# caso mais comum hoje: disco NOVO/em branco + boot UEFI/GPT. Legado
# BIOS/MBR fica fora de escopo deste script (a sequencia diskpart e'
# diferente -- "convert mbr" em vez de "convert gpt", sem ESP/MSR).
#
# PRE-REQUISITOS OBRIGATORIOS:
#   - Rode a partir de um ambiente Windows/WinPE que NAO seja o disco
#     que sera transformado -- ex.: boot pela midia de instalacao do
#     Windows, Shift+F10 durante o setup pra abrir um prompt. NUNCA
#     rode contra o C:\ que a maquina esta usando AGORA MESMO pra
#     rodar este script -- isso reescreve o boot enquanto o SO que fez
#     a escrita ainda depende dele.
#   - So' provisiona uma maquina NOVA/reimageada -- nao converte uma
#     instalacao existente em uso (isso seria P2V, fora de escopo e
#     risco bem maior).
#   - Um install.wim/install.esd valido (da midia de instalacao, mesma
#     edicao/licenca que sera usada).
#   - O disco alvo (-TargetDiskNumber) deve estar em branco/descartavel
#     -- este script converte pra GPT e reparticiona do zero, apagando
#     tudo que tiver ali.
#
# Nada roda sem confirmacao: o script mostra o plano completo e para,
# a nao ser que -IAcceptTheRisk seja passado E o operador digite
# "CONFIRMO" quando perguntado.
#
# Rodar em PowerShell elevado (Administrador), dentro do WinPE/ambiente
# de instalacao -- nunca na maquina de producao em uso.
#
# Uso:
#   .\vhdx_diff_setup.ps1 -ImageFile D:\sources\install.wim -ImageIndex 1 `
#       -TargetDiskNumber 0 -SizeGB 60 -IAcceptTheRisk
#
# Parametros:
#   -ImageFile         caminho do install.wim/install.esd
#   -ImageIndex        indice da edicao dentro da imagem (Dism /Get-ImageInfo /ImageFile:<arquivo> pra listar)
#   -TargetDiskNumber  numero do disco fisico alvo, conforme "diskpart > list disk" (ERRADO AQUI = disco errado apagado)
#   -SizeGB            tamanho maximo do disco base, em GB (default 60)
#   -IAcceptTheRisk    flag obrigatoria -- sem ela o script so mostra o plano e para

param(
    [Parameter(Mandatory = $true)][string]$ImageFile,
    [int]$ImageIndex = 1,
    [Parameter(Mandatory = $true)][int]$TargetDiskNumber,
    [int]$SizeGB = 60,
    [switch]$IAcceptTheRisk
)

$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "rode este script como Administrador (dentro do WinPE/ambiente de instalacao)"
}

if (-not (Test-Path $ImageFile)) {
    throw "ImageFile nao encontrado: $ImageFile"
}

$plano = @"

PLANO (nada foi executado ainda):

  1. Apagar e converter o disco fisico $TargetDiskNumber inteiro para GPT
  2. Criar particoes: EFI System (FAT32, 260MB), MSR, Dados (NTFS, resto do disco)
  3. Criar base.vhdx ($SizeGB GB, expansivel) na particao de Dados
  4. Aplicar $ImageFile (indice $ImageIndex) dentro do base.vhdx
  5. Criar diff.vhdx como filho diferencial de base.vhdx
  6. Configurar o boot (bcdboot) pra iniciar a partir do diff.vhdx
  7. Marcar base.vhdx como somente-leitura (nunca deve ser escrito direto)

  Isso APAGA TUDO que existir hoje no disco fisico $TargetDiskNumber.
  Nao ha undo automatico se algo der errado no meio do caminho.

"@
Write-Host $plano -ForegroundColor Yellow

if (-not $IAcceptTheRisk) {
    Write-Host "rode de novo com -IAcceptTheRisk para prosseguir (isso so' mostra o plano)."
    exit 0
}

$confirmacao = Read-Host 'Digite "CONFIRMO" (maiusculas, exato) para apagar o disco acima e continuar'
if ($confirmacao -ne "CONFIRMO") {
    Write-Host "cancelado -- nada foi alterado."
    exit 1
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

$VhdDir = "V:\DeepFreezerVHD"
$BasePath = Join-Path $VhdDir "base.vhdx"
$DiffPath = Join-Path $VhdDir "diff.vhdx"
$SizeMB = $SizeGB * 1024

# -- 1-2: particiona o disco fisico alvo -----------------------------
Write-Host "particionando o disco $TargetDiskNumber..."
Invoke-Diskpart @"
select disk $TargetDiskNumber
clean
convert gpt
create partition efi size=260
format fs=fat32 quick label="System"
assign letter=S
create partition msr size=16
create partition primary
format fs=ntfs quick label="DeepFreezerData"
assign letter=V
"@

New-Item -ItemType Directory -Force -Path $VhdDir | Out-Null

# -- 3: cria o disco base ---------------------------------------------
Write-Host "criando base.vhdx..."
Invoke-Diskpart @"
create vdisk file="$BasePath" maximum=$SizeMB type=expandable
select vdisk file="$BasePath"
attach vdisk
create partition primary
format fs=ntfs quick label="DeepFreezerBase"
assign letter=W
"@

# -- 4: aplica a imagem do Windows dentro do base.vhdx -----------------
Write-Host "aplicando $ImageFile (indice $ImageIndex) em W:\ ..."
& Dism.exe /Apply-Image /ImageFile:"$ImageFile" /Index:$ImageIndex /ApplyDir:"W:\"

# -- 6a: configura o boot ainda contra o base.vhdx, soh pra gerar os --
#        arquivos de boot no ESP -- o BCD sera repontado pro diff.vhdx
#        no passo seguinte, depois que ele existir.
Write-Host "gravando arquivos de boot iniciais (ESP em S:)..."
& bcdboot.exe W:\Windows /s S: /f UEFI

# desanexa o base.vhdx e marca como somente-leitura em disco
Invoke-Diskpart @"
select vdisk file="$BasePath"
detach vdisk
"@
attrib +R $BasePath

# -- 5: cria o diferencial a partir do base -----------------------------
Write-Host "criando diff.vhdx (filho de base.vhdx)..."
Invoke-Diskpart @"
create vdisk file="$DiffPath" parent="$BasePath"
select vdisk file="$DiffPath"
attach vdisk
assign letter=W
"@

# -- 6b: reaponta o boot pro diff.vhdx (e' o que vai bootar de fato) --
Write-Host "repontando o boot para diff.vhdx..."
& bcdboot.exe W:\Windows /s S: /f UEFI

Invoke-Diskpart @"
select vdisk file="$DiffPath"
detach vdisk
"@

Write-Host ""
Write-Host "provisionamento concluido. base.vhdx (somente-leitura) e diff.vhdx" -ForegroundColor Green
Write-Host "em $VhdDir no disco $TargetDiskNumber. Reinicie a maquina fisica --" -ForegroundColor Green
Write-Host "ela deve bootar a partir de diff.vhdx." -ForegroundColor Green
Write-Host ""
Write-Host "IMPORTANTE: isso ainda nao inclui o reset automatico do diff.vhdx" -ForegroundColor Yellow
Write-Host "a cada boot -- ver vhdx_diff_reset.ps1 e o README para o passo" -ForegroundColor Yellow
Write-Host "manual/semi-automatico que falta pra fechar o ciclo." -ForegroundColor Yellow

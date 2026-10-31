# UserFreezer: ativacao offline de C: e dados persistentes em D:

ESTADO: experimento de VM. Nao certificados Windows 7/10/11 reais.
A instalacao do servico por si so nao intercepta o Windows Explorer.

## Escolha na GUI

Abrir painel com o EXE e selecionar "Sistema/volume Windows".
C: e o volume proposto. D: e o volume persistente sugerido: deve ser
uma unidade NTFS local diferente de C:, com backup/snapshot. A GUI nao
cria essa unidade nem move Desktop, Documentos ou AppData para D:.

Confirmar consentimento e backup e selecionar Exportar proposta offline.
O JSON registra activation_state=NOT_STARTED; nao configura o servico,
nao toca no kernel, nao instala recursos nem solicita elevacao UAC.
Essa proposta e apenas uma declaracao do escopo desejado.

## Windows 10/11 com UWF nativo: ativacao de laboratorio

SO: Windows 10/11 Enterprise, Education ou IoT Enterprise. Nao funciona
em Windows 7 comum ou Windows 10/11 Home/Pro. O recurso Windows UWF deve
estar instalado antes de executar o ensaio, com snapshot e console
do hipervisor disponiveis. Unidade D: NTFS local fixa e nao protegida
e obrigatoria; escolher D: nao implica que os arquivos do Desktop
sejam permanentes (eles ficam em C:).

A primeira ativacao do UWF pode desabilitar paginacao, restauracao do
sistema, indexacao, desfragmentacao e alterar bootstatuspolicy.
Nao usar em maquinas de producao.

Em PowerShell elevado, na raiz do checkout exato:

    .\packaging\windows\os_level\uwf_lab_stage.ps1

Inspeciona sem modificar. Depois de comprovar snapshot e aceitar
explicitamente o descarte, somente em VM descartavel:

    .\packaging\windows\os_level\uwf_lab_stage.ps1 -Stage -ProtectedVolume C: -PersistentVolume D: -ConfirmDisposableVM -ConfirmBackupSnapshot -ConfirmDiscardWritesAfterReboot

O script verifica edicao/build, UWF WMI e D: NTFS nao protegido,
recusa conflitos/preexistencia e usa UWF nativo para agendar a
protecao de C: e ativacao do filtro no PROXIMO boot. Nao reinicia
nem declara que o disco ja esteja congelado.

Em caso de falha apos inicio do agendamento: a VM pode estar
parcialmente configurada. Inspecione e restaure snapshot em vez de
pressupor revertido. Nao usar "filter disable" para consertar
configuracao de terceiros.

## Teste humano com reboot real

Reinicie manualmente e rode:

    .\packaging\windows\os_level\uwf_lab_stage.ps1 -VerifyAfterReboot

O estado nativo ativo de UWF/C: ainda nao comprova o rollback.
Crie pelo Explorer um arquivo no Desktop (C:). Crie outro arquivo
no volume D:. Salve hashes, logs, boot ID e evidencias em D: ou em
volume externo, reinicie NOVAMENTE e confirme:
- Arquivo criado no Desktop desapareceu
- Arquivo no D: permaneceu
- Baseline original nao mudou
- Filtro continua ativo em C: e nao cobre D:

Depois teste exclusoes, overlay cheio, desativacao e recuperacao
a partir do snapshot. Anexar provas humanas nas issues #49 e #54.
Uma instalacao com status Running nao e evidencia de protecao OS-level.

## Limites

O script nao instala UWF opcional, nao cria particoes, nao faz
configuracao autenticada de UWF via GUI/IPC, nao protege Windows 7
comum e nao implementa driver proprietario. A v0.2.0 ESTAVEL
permanece bloqueada. O fluxo Windows NT de commit de arquivos
continua protegido contra uso prematuro pela issue #63.

Referencia Microsoft: https://learn.microsoft.com/windows/configuration/unified-write-filter/

# #63 — Encerramento real, reboot em VM e revisão administrativa NT

**Status:** kit reproduzível entregue; execução de reboot em Windows 7 SP1
ainda exige VM externa e evidências anexadas ao GitHub. Testes em runner
Windows moderno não certificam Windows 7. O commit de produção permanece
bloqueado em DeepFreezer._apply_commit.

## 1. Ensaio com processo real (sem reboot)

Em Windows moderno ou Windows 7 SP1 **descartável**, com Python 3.8 e
pywin32, executar na raiz do checkout do commit que estiver em avaliação:

    python -m unittest -v test_nt_checkpoint_process_kill

O teste prepara três diretórios temporários e um subprocesso Windows. Após
a primeira gravação NT, o subprocesso imprime AFTER_NATIVE_WRITE e bloqueia
antes de DONE(0). O processo pai o encerra por Popen.kill(), reabre o
checkpoint em outro processo Python e exige, em uma árvore de teste:

- o primeiro arquivo contém FIRST;
- o segundo arquivo não existe;
- o registro indica state=uncertain, completed=0, uncertain_index=0;
- outra execução, ainda que com plano diferente, é recusada.

**Não** é injeção de queda de energia. O teste substitui somente no processo
de teste as checagens DPAPI/ACL, porque diretórios temporários não têm
provisionamento do serviço. Ele não é prova de ACL de produção.

## 2. Ensaio pós-reboot no Windows 7 SP1

Requer imagem licenciada, snapshot independente, acesso ao console e
**segundo volume virtual persistente** (exemplo E:) que sobreviva ao reboot
e não esteja sujeito a UWF/EWF/FBWF. O teste **não** configura filtros,
BCD, discos nem reinicia a máquina.

Verificar Python 3.8 e pywin32, build do Windows, arquitetura, NTFS, SID do
executor e hash do checkout/binário. ATENÇÃO: a release v0.1.13 não contém
este probe; usar o checkout exato da branch/PR testada, nunca atribuir o
resultado aos executáveis v0.1.13.

No snapshot inicial, criar E:\df-evidence manualmente e executar, da raiz
do repositório, em **VM descartável**:

    python packaging\windows\nt_checkpoint_vm_reboot_probe.py --prepare --base C:\DF-Checkpoint-Probe --evidence E:\df-evidence\checkpoint-before.json --confirm-disposable-vm

A fase prepare exige que o diretório C:\DF-Checkpoint-Probe e o arquivo
de evidência ainda NÃO existam. Ela cria exclusivamente os diretórios de
ensaio, força o encerramento do subprocesso durante o checkpoint e grava
o estado inicial + Win32_OperatingSystem.LastBootUpTime obtido de WMI.
Não apagar o diretório de ensaio.

Reiniciar a VM manualmente, sem restaurar snapshot entre as duas fases:

    shutdown /r /t 0

Após um **novo boot efetivo**, executar com os MESMOS caminhos:

    python packaging\windows\nt_checkpoint_vm_reboot_probe.py --verify-after-reboot --base C:\DF-Checkpoint-Probe --evidence E:\df-evidence\checkpoint-before.json --confirm-disposable-vm > E:\df-evidence\checkpoint-after.json

O verificador falha se o LastBootUpTime WMI não mudou, se primeiro arquivo
não tem SHA-256 esperado, se segundo arquivo apareceu, se marcadores INTENT/
STARTED/DONE divergiram ou se o hash da intenção foi alterado. Somente um
resultado PASS_SCRATCH_CHECKPOINT_POST_REBOOT vale como evidência **deste**
ensaio de pasta temporária — NÃO certifica durabilidade com perda de energia,
ACL/DPAPI reais nem recuperação do commit de produção.

Anexar os dois JSONs, hashes do checkout e executável, build de Windows,
ACLs (com dados pessoais redigidos), log de reboot, screenshots do sistema e
descrição do snapshot à issue #63. Repetir em Windows 10/11/NTFS. Executar
também testes de alteração concorrente com conta comum, reparse, hardlinks
e token de serviço em laboratório distinto.

## 3. Procedimento administrativo para incidente REAL

A conta executora deve corresponder ao contexto DPAPI do cadastro protegido.
O store é previamente provisionado com owner/DACL confiáveis. Não executar
scripts do probe de scratch contra uma pasta real.

1. **Conter:** desabilitar comandos de commit e escrita, preservar journal,
   overlay, store DPAPI, logs e estado de boot, tirar snapshot/cópia forense
   externa. Não apagar markers, não executar novo thaw(commit=True).
2. **Inspecionar somente leitura** a partir do checkout que contém a rotina:

       python packaging\windows\inspect_nt_checkpoint.py --target C:\Alvo --store C:\ProgramData\DeepFreezer\Enroll

   A inspeção exige identidade DPAPI do alvo e overlay, confere handles e
   ACLs, valida hash da intenção e STARTED/DONE e retorna sempre
   resume_allowed=false. Se qualquer requisito falhar: preservar, escalar.
   A seção write_effects do relatório executa leitura somente por handles NT
   da raiz e diretórios fixados. Cada escrita W recebe uma observação:
   matches_recorded_hash, differs_from_recorded_hash, missing,
   unverifiable ou not_verified_budget. Diretórios criados e exclusões
   permanecem not_verified_for_nonwrite — ausência/presença atual não
   demonstra que uma operação específica ocorreu. O status de marcador
   permanece independente: done, started_uncertain ou not_confirmed.
   **Mesmo matches_recorded_hash não comprova a origem dos bytes,
   durabilidade pós-reboot nem autoriza reexecução.** A leitura verifica
   identidade/ACL e recusa seguir junctions; erros de ACL ou reparse
   são marcados como unverifiable para revisão manual.
3. **Correlacionar:** comparar estado atual de cada destino com o último
   snapshot confiável e hashes dos dados; tratar STARTED sem DONE como
   ambíguo mesmo que o arquivo pareça presente. Verificar efeitos externos,
   reparse points, ACLs, junctions, hardlinks e logs de serviço.
4. **Resolver fora do UserFreezer:** um administrador autorizado escolhe
   restauração a partir do snapshot ou reparação manual **depois** de aprovar
   escopo/impacto. Operações de restauração são externas ao protótipo.
   Documentar comandos, responsáveis, hashes antes/depois e testes de
   integridade em dossiê de incidente; não afirmar rollback automático.
5. **Registrar uma revisão imutável**, usando o SHA-256 do pacote externo
   de evidências e ID opaco do incidente (6 a 64 caracteres):

       python packaging\windows\record_nt_checkpoint_review.py --target C:\Alvo --store C:\ProgramData\DeepFreezer\Enroll --incident INCIDENT_2026_63 --evidence-sha256 HASH_SHA256_64_HEX --acknowledge-no-unlock

   Requer token efetivo elevado (SYSTEM/Administrators) e cria um único
   arquivo REVIEW por handle NT sem substituir dados anteriores. O REVIEW
   registra somente a revisão e a referência à evidência; não é assinatura
   criptográfica nem prova de que a restauração foi correta.
6. **Não liberar retry:** mesmo com REVIEW, o marcador INTENT permanece
   bloqueando qualquer nova tentativa. Abrir issue de recuperação para
   eventual mecanismo futuro de rotação/encerramento de ciclo com snapshots,
   autenticação, validação cruzada e revisão independente. Nunca apagar
   manualmente um INTENT para forçar retry sem uma solução auditada.

## 4. Critérios de aceite e limitações

- [ ] Subprocesso morto externamente no runner Windows: teste CI aprovado.
- [ ] Inspeção por processo separado e recusa de replay: teste CI aprovado.
- [ ] Fase prepare em VM Windows 7 SP1 com hash e snapshot reais: pendente.
- [ ] Reboot observado por WMI + mesmo INTENT/sentinelas: pendente.
- [ ] Incidente real resolvido com cadeia de custódia e aprovação humana:
      depende de operação e evidência externa.
- [ ] Poder rearmar commit sem apagar rastros, prova de queda de energia,
      concorrência e token de serviço: **não implementado**.

O protocolo marca limites de execução, mas a gravação de arquivo com
FlushFileBuffers **não prova** flush de entradas de diretório/NTFS sob perda
de energia. Não promover Windows commit de produção até ensaio e revisão
de consistência dos dados e do namespace.

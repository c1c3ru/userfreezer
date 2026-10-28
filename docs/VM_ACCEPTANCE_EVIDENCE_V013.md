# Protocolo de evidências de aceitação — UserFreezer v0.1.13

**Situação:** protocolo para execução futura, **não** resultado de teste.
**Escopo:** issues #63, #49, #54 e #56. A v0.2.0 continua bloqueada enquanto os gates não forem satisfeitos.

## 1. Identidade e rastreabilidade da execução

Preencher **antes** de cada rodada e anexar à issue apropriada:

| Campo | Valor |
| --- | --- |
| Issue e caso de teste | PENDENTE |
| Operador/data UTC | PENDENTE |
| Versão do produto / SHA do commit | v0.1.13 / `b8ac4e85e07f3907a49238d18e6bdf98f5ab3e36` |
| Nome do artefato e SHA-256 local (comparado com SHA256SUMS) | PENDENTE |
| OS, edição, build, arquitetura e filesystem | PENDENTE |
| Hypervisor, versão e snapshot anterior | PENDENTE |
| Conta/privilégios (sem identificadores pessoais) | PENDENTE |
| Identificador da VM, boot antes e boot depois | PENDENTE |
| Estratégia configurada / estado realmente observado | PENDENTE |
| Evidências (nomes de arquivos, hashes e links) | PENDENTE |
| Resultado | NÃO EXECUTADO |

Resultados permitidos: `PASS`, `FAIL`, `BLOCKED`, `NOT_EXECUTED`, `NOT_APPLICABLE`.
`NOT_APPLICABLE` requer justificativa de plataforma; `BLOCKED` requer causa concreta. Jamais substituir ausência de evidência por `PASS`.

## 2. Critérios gerais de integridade

1. Usar somente VM descartável e licenciada, snapshot externo e mídia ou procedimento de recuperação previamente testado. Nunca executar scripts de particionamento, VHDX ou reset de boot em estação de produção.
2. Verificar os hashes da release antes de instalar; preservar logs e resultados em disco não protegido ou exportá-los para fora da VM.
3. Registrar estado efetivo **antes e depois de reboot real**. Um processo reiniciado ou `umount` não é reboot.
4. Realizar escrita externa com ferramenta comum do SO, sem chamar API do DeepFreezer. Distinguir baseline, arquivo volátil e, quando suportado, exclusão persistente.
5. Fazer teste negativo com filtro inativo, erro de montagem ou falta de permissão e exigir `FAIL` ou `BLOCKED`, nunca `PASS`.
6. Após falha, preservar diagnóstico de mutações parciais. Não alegar rollback/atomicidade onde não há prova.
7. Redigir anexos para remover segredos, tokens, usuários reais, identificadores de disco e caminhos privados. Preservar hashes de arquivos de prova.

## 3. Gates independentes

| Gate | Evidência mínima | Issue | Situação inicial |
| --- | --- | --- | --- |
| NT-01 | operações relativas por handles sob troca concorrente de junction, com sentinela externa intacta | #63 | CI moderno existe; Win7 pendente |
| NT-02 | concorrência iniciada antes e durante abertura da raiz, ACL, UNC, reparse de destino e falha parcial | #63 | PENDENTE |
| NT-03 | Windows 7 SP1 VM, binário exato, serviço, IPC, processo atacante e integridade dos alvos | #63 | PENDENTE |
| NT-04 | integração segura e revisão independente do fluxo real `thaw --commit` | #63 | PENDENTE; commit bloqueado |
| LIN-01 | `findmnt` indica overlay ativo no alvo permitido **após boot** via unit opt-in | #49 | PENDENTE |
| LIN-02 | arquivo externo criado na sessão anterior desaparece; baseline permanece; IDs de boot diferentes | #49/#54 | PENDENTE |
| LIN-03 | gravações anteriores à unit, conflito application-level, erro de mount, falta de espaço e recuperação | #49/#54 | PENDENTE |
| WIN-01 | UWF/EWF/FBWF realmente instalado, compatível, active pós-reboot e escrita externa revertida | #49/#54 | PENDENTE |
| WIN-02 | exclusão persistente onde suportada e disable confirmado após reboot | #49/#54 | PENDENTE |
| WIN-03 | rollback de VHDX/BCD/WinPE em VM isolada, com recuperação demonstrada | #54 | PENDENTE |
| UX-01 | sessão GUI Win7, múltiplos alvos, UAC recusado/aprovado, ACL e ausência de mutação não autorizada | #56 | PENDENTE |

Um `PASS` de LIN-01/LIN-02 nunca qualifica proteção de `/`: o OverlayFS distribuído é **por diretório**. Windows 7 comum não suporta OS-level pelo projeto; registrar `NOT_APPLICABLE` onde apropriado.

## 4. Roteiro Linux systemd (somente VM)

Pré-condições: pacote v0.1.13 verificado, diretório de teste root-owned e sem gravabilidade por terceiros, configuração application-level não sobreposta, snapshot e captura de `journalctl`.

1. Criar **antes** da ativação um arquivo baseline no diretório permitido, por exemplo `/srv/deepfreezer-vm-test/baseline.txt`; registrar seu SHA-256.
2. Habilitar explicitamente a instância de `deepfreezer-overlayfs@.service` seguindo [LINUX_OVERLAYFS_VM.md](LINUX_OVERLAYFS_VM.md); registrar `systemctl is-enabled` e `systemctl cat`.
3. Reiniciar **a VM** e registrar `cat /proc/sys/kernel/random/boot_id`, `findmnt --mountpoint /srv/deepfreezer-vm-test -o TARGET,FSTYPE,OPTIONS`, `systemctl status` e `journalctl -b -u 'deepfreezer-overlayfs@*'`.
4. Com `FSTYPE=overlay` efetivo, criar um arquivo de prova por `tee`/shell comum e salvar o nome/hash em local **não protegido**.
5. Reiniciar novamente; exigir **outro boot_id**, montagem `overlay` ativa, prova volátil ausente e baseline com hash igual. Guardar os dois boot IDs e logs da unit de ambos os boots.
6. Simular erro de configuração e conflito apenas após snapshot e em alvo descartável; conferir estado `failed` e ausência de alegação de proteção.
7. Recuperação: desabilitar a unit para boots futuros, reiniciar e confirmar ausência de overlay; **não** considerar `systemctl disable` sozinho como desmontagem.

A ordenação da unit depois de `local-fs.target` não demonstra interceptação de escritores anteriores à sua ativação. Registrar serviços que possam escrever antes da unit e não elevar LIN-01 a proteção total.

## 5. Roteiro Windows

Seguir [WIN7_MANUAL_TEST.md](WIN7_MANUAL_TEST.md) e [OS_LEVEL_VALIDATION.md](OS_LEVEL_VALIDATION.md). Capturar: versão/edição exata, SHA dos EXEs e ZIP, estado de filtro/pending/active, horários ou boot IDs antes/depois, `inspect_protection.ps1`, `vm_probe.ps1`, saída dos comandos de serviço, screenshots e logs de ações UAC/ACL.

Para #63, executar o ensaio NT com dois processos e sentinela externa; registrar explicitamente limites do teste, inclusive raiz aberta antes da troca, UNC/ACL, privilégios e se o commit de produção continuou `BLOCKED`. Não habilitar `thaw --commit` apenas porque o protótipo passou.

UWF/EWF/FBWF dependem da edição e da presença real do componente. VHDX/WinPE exige ensaio separado de recuperação e não deve ser provisionado automaticamente.

## 6. Regra de publicação

O gate global `RELEASE_V020` somente pode ser `PASS` após (a) cada capacidade anunciada ter plataforma suportada e evidência real, (b) revisão de segurança de #63 e integrações, (c) validação de reboot/rollback #49/#54, (d) validação UX #56, (e) CI e artefatos com hashes e proveniência íntegros. Caso uma estratégia não seja validada, reduzir explicitamente o escopo de suporte e manter a funcionalidade desabilitada. Nenhuma issue é fechada automaticamente por este documento.

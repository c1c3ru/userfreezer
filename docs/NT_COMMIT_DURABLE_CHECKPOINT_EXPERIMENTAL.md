# Checkpoints duráveis de commit NT — protótipo experimental (#63)

Estado: **experimental, isolado do core/CLI/IPC**. O bloqueio de
DeepFreezer.thaw(commit=True) no Windows **não** é removido. Uma transação
completa de múltiplas operações NÃO é atômica; o mecanismo apenas registra
as operações possivelmente aplicadas para diagnóstico.

## Protocolo de execução

1. Reconciliar manifesto/journal, conferir identidades cadastradas do alvo
   e overlay via DPAPI, validar ACLs e preparar TODOS os payloads em memória
   (módulos dos PRs #124–#127).
2. Exigir que alvo, overlay e store protegido sejam árvores distintas.
   Consultar a identidade real do alvo e overlay antes de qualquer escrita.
3. No diretório de cadastro **preexistente e protegido**, criar
   SHA256(raiz).ntcommit.intent por handle relativo NT + FILE_CREATE,
   serializar o plano (tipo, path, tamanho, SHA-256), identidades dos objetos
   e SHA-256 da intenção. Gravar com WriteFile + FlushFileBuffers.
   Reabrir, conferir ACL por handle e bytes antes da primeira mutação.
4. Para cada passo N criar marcador de STARTED, verificar que foi persistido,
   aplicar a operação nativa **com identidade alvo exigida** e só depois
   criar/verificar marcador DONE.
5. Depois do último DONE criar/verificar COMPLETE. O retorno afirma
   sucesso de todas as chamadas e marcadores, não atomicidade de transação.

Os nomes são derivados da raiz. A intenção **não pode ser sobrescrita**:
mesmo que exista COMPLETE, uma segunda execução é bloqueada. Não existe
retomada, exclusão ou arquivamento automático dos registros. Apenas uma
ação administrativa auditada poderá futuramente resolver/reabrir um ciclo.

## Semântica em falhas

- **Nenhuma intenção:** nenhum commit foi iniciado por este protocolo.
- **INTENT sem STARTED:** intenção existente; intervenção administrativa
  exigida antes de qualquer nova tentativa.
- **STARTED sem DONE:** a mutação pode ter acontecido; o estado é
  uncertain e não é possível decidir automaticamente por retry/rollback.
- **DONE parcial:** chamadas anteriores confirmadas; demais etapas
  não são repetidas automaticamente.
- **Todos DONE sem COMPLETE:** operações anteriores foram confirmadas,
  mas o encerramento não; ainda requer auditoria.
- **COMPLETE:** marcadores confirmam a sequência inteira, porém não
  garantem rollback nem atomicidade entre operações.
- **Registro truncado/adulterado/desordenado ou erro de I/O:** falhar
  fechado. **Nunca** apagar/truncar um marcador para "corrigir" falha.

## Escopo dos testes

- Testes multiplataforma: digest e identificação do plano, truncamento,
  etapas inválidas, progresso, estados incertos, divergência, limites.
- Windows runner: escrita real NT em pasta temporária, marker DONE/COMPLETE,
  bloqueio de segunda execução, falha injetada **após mutação e antes do
  DONE**, e preservação de sentinelas.
- Ainda faltam: encerramento abrupto real de processo e queda de energia,
  persistência do namespace em reboot, provisionamento ACL em instalação,
  privilégio e impersonation do serviço, journal/overlay sob processos
  concorrentes, revisão contra hardlinks e rename, e validação Windows 7 SP1
  com a versão exata dos binários gerados.

**Atenção:** FlushFileBuffers sobre arquivos criados não constitui,
por si só, prova de durabilidade de entradas de diretório após perda de
energia. Não declarar recuperação de energia comprovada nem liberar commit
de produção sem teste de VM (incluindo comparação pré/pós reboot), auditoria
independente e plano explícito para transação interrompida.

## API

- apply_checkpointed_plan_experimental(root, overlay_root, store, plan)
- inspect_nt_commit_checkpoint(root, store) (somente leitura)
- apply_reconciled_checkpointed_plan_experimental — caminho com
  validação de journal, identidades e payloads antes da intenção.

A API não permite ignorar identidade cadastrada, não reutiliza um
checkpoint antigo nem realiza rollback disfarçado.

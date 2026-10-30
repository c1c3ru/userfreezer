# Encerramento administrativo imutável de incidente NT — issue #63

**Estado: experimental.** Esta fase acrescenta o marcador `RESOLUTION` à cadeia
`INTENT → STARTED/DONE → REVIEW → RESOLUTION`. Isso encerra **o registro
administrativo do incidente**, não uma transação do sistema de arquivos.
`thaw --commit` Windows continua bloqueado e nenhuma etapa autoriza retry.

## Condições antes de registrar RESOLUTION

1. Conter novas alterações e preservar o snapshot, overlay, checkpoint e
   registros originais. Consultar o relatório somente leitura por handles NT.
2. O incidente precisa ter estado `uncertain` ou `incomplete`, com
   `INTENT` íntegro e identidades DPAPI/ACL do alvo e overlay verificadas.
3. Um `REVIEW` prévio e imutável deve existir, com o mesmo SHA-256 da
   intenção, ID do incidente e estado do checkpoint.
4. Um operador autorizado deve realizar **fora do UserFreezer** a
   restauração a partir de snapshot confiável ou conciliação manual, guardar
   evidências de bytes/ACLs/reparse points e obter aprovação registrada
   separadamente. A API não verifica se essa restauração foi correta.
5. A conta executora deve ser SYSTEM ou administrador com token efetivo
   elevado; conta filtrada por UAC ou processo impersonado não autorizado
   deve falhar fechado.

## Registro único

`record_nt_incident_resolution_experimental(root, store, incident, approval,
sha256_evidencia_recuperacao, decision)` aceita apenas:
- `restored_from_verified_snapshot` — afirmação de restauração a partir
  de snapshot revisado;
- `manually_reconciled` — afirmação de conciliação externa revisada.

A função confere novamente os checkpoints e o `REVIEW`, vincula
`intent_sha256`, `review_sha256`, os dois hashes de evidência externa,
ID do incidente, ID de aprovação, estado e decisão, e usa
`NtCreateFile(FILE_CREATE)` para criar `<raiz-hash>.ntcommit.resolution`
sem substituir um registro existente. O arquivo é relido pelo handle,
com ACL verificada e conteúdo idêntico. Os registros INTENT, STARTED, DONE,
COMPLETE e REVIEW permanecem intocados.

Exemplo (Windows, conta administrativa autorizada, dossiê real já aprovado):

    python packaging\windows\resolve_nt_checkpoint_incident.py --target C:\Alvo --store C:\ProgramData\DeepFreezer\Enroll --record --incident INCIDENT_2026_63 --approval-id APROVADOR_2026_001 --recovery-evidence-sha256 HEX_SHA256_64 --decision restored_from_verified_snapshot --acknowledge-no-retry

Consulta somente leitura:

    python packaging\windows\resolve_nt_checkpoint_incident.py --target C:\Alvo --store C:\ProgramData\DeepFreezer\Enroll --inspect

**IMPORTANTE:** `--record` é declaração administrativa, não restaura
arquivos. A aprovação e as evidências são referências externas e não são
verificadas criptograficamente contra assinatura do responsável. Uma
resolução existe uma única vez, mesmo que os fatos mudem posteriormente;
novas decisões exigem processo de incidente separado, sem reescrita.

## Situação dos ciclos de commit

`inspect_nt_incident_resolution_experimental` retorna
`retry_allowed=false` e `new_epoch_allowed=false` mesmo após RESOLUTION.
O mecanismo original recusa outra execução se INTENT existir. É proibido
remover/renomear INTENT ou reaproveitar uma identidade para forçar novo commit.

Uma eventual versão futura de `epoch` exige desenho e revisão independentes:
IDs imprevisíveis de ciclo vinculados a raiz+overlay+identidade NT; histórico
append-only em storage protegido; exclusividade e controle de concorrência
entre serviço e operador; estado recuperado validado por snapshots; vínculo
com autorização forte e evidências assinadas; coleta de provas em VM Win7 SP1
incluindo reboot, queda de energia e corridas de namespace. **Nada disso é
implementado por este marcador.**

## Critérios de aceite

- Criação recusada sem `REVIEW`, com token sem privilégio, estado `complete`
  ou `absent`, IDs inválidos, hashes inválidos ou progressos alterados.
- Criação `FILE_CREATE` somente uma vez; nova tentativa não sobrescreve
  `RESOLUTION`.
- Inspeção valida bytes canônicos, referência ao `REVIEW` e o
  `intent_sha256`; arquivo adulterado deve falhar fechado.
- Teste Windows com diretório descartável deve demonstrar que criar
  `RESOLUTION` preserva os bytes do `INTENT` e do próprio `RESOLUTION`.
- Evidência real pós-reboot Windows 7 SP1 continua **pendente** até execução
  em VM licenciada e separada desta sessão. Jobs do GitHub Actions que nem
  chegaram a obter runner não representam testes aprovados ou reprovados.

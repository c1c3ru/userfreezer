# Consolidação da v0.2.0 — estado e evidências

**Última revisão: 2026-10-28** · Repositório: `c1c3ru/userfreezer`.
Este documento é o ponto central para acompanhar o fechamento das
issues [#63](https://github.com/c1c3ru/userfreezer/issues/63),
[#49](https://github.com/c1c3ru/userfreezer/issues/49),
[#54](https://github.com/c1c3ru/userfreezer/issues/54) e
[#56](https://github.com/c1c3ru/userfreezer/issues/56). Atualize-o em cada PR
que altere os critérios de aceite, junto com o comentário na issue.

**Versão pública confirmada:** `v0.1.12`. A `v0.2.0` **não foi
publicada**. As quatro issues permanecem abertas até as provas abaixo.

## Estado por issue

| Issue | Implementado e com CI | Critério ainda pendente |
| --- | --- | --- |
| [#63: TOCTOU NT](https://github.com/c1c3ru/userfreezer/issues/63) | PRs #94, #95, #100, #101, #103, #105 e #106: abertura, criação/gravação, mkdir, unlink, rename/replace, rmdir vazio, enumeração e exclusão recursiva experimental, sempre por handles NT relativos. PR #106 integrou **protótipo** de exclusão recursiva por handle com CI aprovado. | Integrar todas as operações ao core sem pathname fallback; raiz confiável, semântica de falha parcial, teste concorrente intensivo com dois processos e evidência Win7 SP1 |
| [#49: OS-level](https://github.com/c1c3ru/userfreezer/issues/49) | PR #88: gravação externa real interceptada por kernel OverlayFS Linux por diretório; PR #93: estado independente no painel; PR #102: unit systemd opcional, desativada no pacote, com guard de conflito; PR #104: exigir alvo e ancestrais root-owned e não graváveis por terceiros | Reboot e rollback real de VM, exclusões, ativação antes de escritores, estratégia de rootfs/initramfs e filtros Windows verificados |
| [#54: VM](https://github.com/c1c3ru/userfreezer/issues/54) | PRs #91, #97, #98 e #99: recusa de falso PASS sem reboot, bloqueio VHDX fora do WinPE, verificação de comandos nativos, teste de exclusão persistente com sentinela e comparação de caminhos | Rodar UWF e EWF/FBWF em versões licenciadas e VHDX/WinPE em VMs descartáveis; anexar provas de boot, recuperação e rollback |
| [#56: UX](https://github.com/c1c3ru/userfreezer/issues/56) | PRs #90 e #96: autostart por usuário, multialvos, overlay customizado, erros ACL, smoke Tk Linux/Xvfb e Windows Python 3.8/3.12, recusa de ações não autorizadas | Sessão GUI Windows 7 SP1, prompt UAC real, fluxos operacionais e capturas/instruções finais na documentação |

## Engenharia de loop: próximos ciclos de aceitação

1. **#63 — fechar funcionalmente o backend:** comprovar exclusão
   recursiva por handles, adicionar teste end-to-end de write/mkdir/
   replace/remove preservando identidades, testar erros e rollback
   sem declarar atomicidade inexistente. Mantê-lo separado do core
   até passar stress/concurrency, NTFS, junction, ACL, UNC e Win7 SP1.
   O `thaw --commit` Windows permanece bloqueado por segurança.
2. **#49 — ativação real no boot:** VM Linux com unit opt-in protegendo
   apenas diretório permitido e testando gravação por processo externo
   antes e depois do reboot. Registrar se montou no momento necessário.
   **Não confundir com proteger `/` ou todo o SO.**
3. **#54 — matriz de VMs Windows:** primeiro snapshot e inspeção
   read-only; em cada edição compatível validar filtragem realmente
   ativa, exclusões persistentes, reboot e disable; para VHDX, também
   entrada e recuperação do boot via WinPE e retorno ao baseline.
   Guardar GUID, logs, hashes, capturas e estado pós-boot.
4. **#56 — validação final da UX:** conta não-admin, conta admin,
   concessão/recusa de UAC, ausência de fallback local, status
   multialvo e overlays customizados numa sessão Windows 7 SP1.
5. **Release v0.2.0:** publicar somente quando o CI, as VMs aplicáveis,
   a matriz de suporte e os artefatos (hashes/proveniência) estiverem
   consistentes com os recursos anunciados.

## Regras de evidência

- **Teste Windows/Python 3.8 no runner Windows moderno não é Windows
  7 SP1.** O mantenedor realizará manualmente esse ensaio com o
  executável publicado, seguindo `docs/WIN7_MANUAL_TEST.md`.
- **Montagem OverlayFS testada após ummount não é teste de reboot.**
- **Teste negativo do VHDX não é recuperação de boot validada.**
- **Protótipos de NT não reativam commit Windows até revisões end-to-end.**
- Não fechar issues por merge de PR com escopo parcial; só após
  evidências suficientes dos itens respectivos.
- O desempenho do core application-level não significa gravações
  externas interceptadas.

## Fontes de referência

- [Roteiro Windows 7 e VM](WIN7_MANUAL_TEST.md)
- [Matriz de validação OS-level](OS_LEVEL_VALIDATION.md)
- [OverlayFS Linux em VM](LINUX_OVERLAYFS_VM.md)
- [Painel administrativo](../ui/README.md)
- [GitHub Actions](https://github.com/c1c3ru/userfreezer/actions)

# Consolidação da v0.2.0 — estado e evidências

**Última revisão: 2026-10-30** · Repositório: `c1c3ru/userfreezer`.
Este documento é o ponto central para acompanhar o fechamento das
issues [#63](https://github.com/c1c3ru/userfreezer/issues/63),
[#49](https://github.com/c1c3ru/userfreezer/issues/49),
[#54](https://github.com/c1c3ru/userfreezer/issues/54) e
[#56](https://github.com/c1c3ru/userfreezer/issues/56). Atualize-o em cada PR
que altere os critérios de aceite, junto com o comentário na issue.

**Versão pública de validação confirmada:** [v0.1.13](https://github.com/c1c3ru/userfreezer/releases/tag/v0.1.13), publicada em 28/10/2026. A tag da release e o workflow de publicação apontam ao commit imutável `b8ac4e85e07f3907a49238d18e6bdf98f5ab3e36`; a branch `main` pode avançar depois da tag com atualizações documentais sem alterar os binários dessa versão. [CI #40753516522](https://github.com/c1c3ru/userfreezer/actions/runs/40753516522) terminou `success` com 7 artefatos (`.deb`, dois `.exe`, dois `.zip`, SHA256SUMS, SPDX). Compare os hashes antes dos testes de VM. A `v0.2.0` **não foi
publicada**. As quatro issues permanecem abertas até as provas abaixo.

## Estado por issue

| Issue | Implementado e com CI | Critério ainda pendente |
| --- | --- | --- |
| [#63: TOCTOU NT](https://github.com/c1c3ru/userfreezer/issues/63) | PRs #94, #95, #100, #101, #103, #105, #106, #108 e #109: abertura, criação/gravação, mkdir, unlink, rename/replace, rmdir vazio, enumeração e exclusão recursiva experimental, sempre por handles NT relativos. PR #106 integrou exclusão recursiva; PR #108 integrou plano NT end-to-end **somente experimental** e PR #109 passou 12 ciclos com dois processos e junction. PRs #113–#123 ampliaram preflight, raiz fixada por handle, identidade/DPAPI, travessia e cadastro NT experimental (PR #123 CI aprovado). | Integrar fluxo nativo ao core com raiz confiável e validação ACL/UNC; expandir testes concorrentes e de falha parcial; evidência Win7 SP1 real |
| [#49: OS-level](https://github.com/c1c3ru/userfreezer/issues/49) | PR #88: gravação externa real interceptada por kernel OverlayFS Linux por diretório; PR #93: estado independente no painel; PR #102: unit systemd opcional, desativada no pacote, com guard de conflito; PR #104: exigir alvo e ancestrais root-owned e não graváveis por terceiros | Reboot e rollback real de VM, exclusões, ativação antes de escritores, estratégia de rootfs/initramfs e filtros Windows verificados |
| [#54: VM](https://github.com/c1c3ru/userfreezer/issues/54) | PRs #91, #97, #98 e #99: recusa de falso PASS sem reboot, bloqueio VHDX fora do WinPE, verificação de comandos nativos, teste de exclusão persistente com sentinela e comparação de caminhos | Rodar UWF e EWF/FBWF em versões licenciadas e VHDX/WinPE em VMs descartáveis; anexar provas de boot, recuperação e rollback |
| [#56: UX](https://github.com/c1c3ru/userfreezer/issues/56) | PRs #90 e #96: autostart por usuário, multialvos, overlay customizado, erros ACL, smoke Tk Linux/Xvfb e Windows Python 3.8/3.12, recusa de ações não autorizadas; exportação de diagnóstico IPC anonimizada, com JSON válido, whitelist e escrita atômica | Sessão GUI Windows 7 SP1, prompt UAC real, fluxos operacionais e capturas/instruções finais na documentação |

## Engenharia de loop: próximos ciclos de aceitação

1. **#63 — fechar funcionalmente o backend:** os protótipos de operações
   relativas, DPAPI, leitura/criação exclusiva de registros e testes de
   troca de raízes já possuem CI. Os PRs #124 a #126 integram a ponte de preflight do journal, a
   leitura protegida dos payloads e a reconciliação por handles. O método
   `DeepFreezer.preview_windows_native_commit()` passa a permitir validar
   essas garantias a partir do core real, mas é estritamente somente leitura.
   O novo `DeepFreezer.inspect_windows_native_commit_safety()` confere
   identidades/ACLs, recusa marcadores de progresso órfãos sem INTENT,
   bloqueia checkpoints pendentes, audita a ausência de mudanças durante
   o preflight e nunca autoriza commit em produção. O executor NT
   experimental também impede novas intenções quando há marcadores órfãos.
   O registro durável experimental de INTENT/STARTED/DONE/COMPLETE registra
   progresso e bloqueia reaplicações automáticas. O teste real com processo
   Windows encerrado entre mutação e DONE, a inspeção forense somente leitura,
   a anotação administrativa imutável e o probe de reboot em VM estão no
   escopo de validação da #63. NÃO há rollback, retomada automática, liberação
   após REVIEW nem durabilidade pós-reboot Windows 7 SP1 comprovada.
   A auditoria por handle NT acrescenta observações limitadas de tamanho e
   hash de arquivos W (sem seguir reparse), correlacionadas a STARTED/DONE;
   isso NUNCA declara um commit recuperado ou retomável.
   O novo módulo experimental de RESOLUTION acrescenta uma declaração
   administrativa única, encadeada a REVIEW e INTENT por SHA-256, com
   decisão externa e aprovação identificadas. Registros históricos permanecem
   intocados e retry/new epoch continuam desabilitados; isso NÃO comprova
   recuperação nem autoriza remover checkpoint. O probe Win7 SP1 foi reforçado
   para verificar versão/build e bytes dos marcadores após reboot, mas a
   execução na VM licenciada permanece pendente. O probe foi corrigido para
   capturar o boot em WMI DMTF independente do idioma e recebeu validador
   offline portátil para conferir a consistência dos arquivos before/after,
   sem declarar autenticidade, reboot físico comprovado ou commit certificado.
   O caminho de mutação oficial permanece fail-closed até haver resolução
   administrativa segura de transações parciais e provas em VM Win7. Ainda faltam
   vincular o serviço ao armazenamento NT seguro, persistir de forma
   confiável a identidade do overlay, retomada administrativa segura de falha parcial, auditoria
   NTFS/ACL/UNC e Win7 SP1
   em VM real. O `thaw --commit` Windows permanece bloqueado por segurança.
2. **#49 — ativação real no boot:** o novo probe Linux em duas fases
   registra boot_id, estado OverlayFS e hashes do baseline/sentinela externa,
   exigindo reboot real na VM e evidência em disco persistente separado.
   Os testes CI verificam negativas, não o reboot real. VM Linux com unit opt-in protegendo
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
   O workflow de publicação passa a exigir o manifesto documental
   `docs/V020_RELEASE_ACCEPTANCE.json` com #63/#49/#54/#56 verificados
   e revisão humana referenciada em comentários das issues. Atualmente
   TODOS estão pending: o gate bloqueia v0.2.0; versões anteriores não
   são afetadas. O gate não autentica evidências nem substitui VMs.

## Release e testes de VM pendentes

A v0.1.13 é a primeira versão que reúne o unit opt-in Linux e os
protótipos nativos NT, mantendo o commit Windows de produção
**bloqueado**. O teste do Windows 7 deve usar
`deepfreezer_service_windows-7-8.exe` desta release e anexar logs
de serviço, IPC, UAC, GUI, hashes e resultados ao GitHub; o build em
runner moderno não comprova compatibilidade real do SP1.

Testes UWF/EWF/VHDX/WinPE, reboot, exclusões, rollback e estado de boot
continuam pendentes para #49/#54. Não publicar v0.2.0 como concluída
sem a evidência dessas plataformas ou redução explícita do escopo.

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
- [Crash NT e revisão administrativa Win7](WIN7_NT_COMMIT_CRASH_RECOVERY.md)
- [Matriz de validação OS-level](OS_LEVEL_VALIDATION.md)
- [OverlayFS Linux em VM](LINUX_OVERLAYFS_VM.md)
- [Painel administrativo](../ui/README.md)
- [Gate de aceite v0.2.0](V020_RELEASE_ACCEPTANCE.md)
- [GitHub Actions](https://github.com/c1c3ru/userfreezer/actions)

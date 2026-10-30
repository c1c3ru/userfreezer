# v0.2.0 — gate de aceite com evidências de VM

**Estado atual:** todos os quatro critérios documentais estão PENDENTES em
`docs/V020_RELEASE_ACCEPTANCE.json`. A release v0.2.0 não está autorizada.
O check automatizado no job de publicação usa
`packaging/release_acceptance_gate.py`; builds e testes de PR continuam
disponíveis e versões anteriores (como v0.1.13) não são afetadas.

## Critérios de aceite por issue

| Issue | Evidência externa obrigatória antes de marcar verified |
| --- | --- |
| #63 | Ensaio pós-reboot em VM licenciada Windows 7 SP1, hashes dos bytes INTENT/STARTED, boot WMI DMTF, recuperação de falha real, ACL/identidade/cadastro NT e autorização do serviço. Desbloqueio de commit requer revisão independente; artefato experimental não basta. |
| #49 | VM Linux com OverlayFS montado no boot, boot_id anterior/posterior e escrita externa descartada, baseline preservado, ordem de ativação, rollback e exclusões. Diferenciar proteção por diretório de rootfs. |
| #54 | VMs licenciadas para UWF (Windows Enterprise), EWF/FBWF (Windows Embedded 7 quando presente) e VHDX/WinPE nas edições realmente suportadas. Provar boot, filtro ativo, sentinela externa, exclusões, desativação e recuperação. Não testar VHDX de projeto em Win7 comum. |
| #56 | Sessão gráfica real Windows 7 SP1: conta comum sem privilégio, UAC negado/aprovado, Named Pipe e autorização por token, multialvos, overlay personalizado, captura da GUI e operação de descarte com baseline intacto. |

Referências: `docs/WIN7_NT_COMMIT_CRASH_RECOVERY.md`,
`docs/LINUX_OVERLAYFS_VM.md`, `docs/OS_LEVEL_VALIDATION.md`,
`docs/WIN7_MANUAL_TEST.md`, `ui/README.md`.

## Encaminhamento das evidências

1. Fazer snapshot, executar os roteiros nas VMs descartáveis e preservar
   outputs originais em meio independente, com SHA-256 do binário, logs,
   OS/edição/build e informações de reboot reais. Não anexar dados pessoais,
   hashes privados de senha, tokens ou caminhos sensíveis.
2. Em cada issue, comentar o resultado e anexar as provas correspondentes.
   O comentário deve ter URL no formato
   `https://github.com/c1c3ru/userfreezer/issues/63#issuecomment-12345`,
   substituindo a issue e ID pelo comentário real.
3. Após revisão técnica **humana e independente**, alterar a issue
   correspondente no JSON de `pending` para `verified` e inserir uma
   lista das URLs dos comentários de evidência dessa mesma issue.
4. Após as quatro verificadas, registrar `review.approved=true`,
   `review.reviewer` com um identificador de conta GitHub e
   `review.approval_url` apontando para o comentário de aprovação.
5. Abrir PR para revisão das mudanças no JSON com checks e branch de
   release protegidos. Não gerar tag antes do aceite e da conferência
   de binários, changelog, hashes, SPDX e permissões da publicação.

O validador checa apenas esquema, vínculos de URLs e campos esperados;
**não acessa nem autentica os anexos, identidades de aprovadores, sistemas
operacionais ou boot de VM**. Somente proteção de branch, revisão humana e
controle de acesso ao repositório mitigam alterações fraudulentas do
manifesto. Sua função é impedir publicação ACIDENTAL enquanto itens seguem
pendentes, não substituir segurança operacional/criptográfica.

Verificar o gate localmente:

    python3 packaging/release_acceptance_gate.py --version 0.2.0 --record docs/V020_RELEASE_ACCEPTANCE.json

Ele deve retornar código 2 com RELEASE BLOCKED até a revisão de todos
os critérios. A execução para `--version 0.1.13` deve retornar código 0.

A execução de VM não está disponível no runner GitHub moderno nem nesta
sessão. **Não** fechar issues nem definir `verified` a partir somente de
CI Python Windows 3.8, mocks ou documentação.

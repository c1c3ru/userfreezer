# Administração local segura — proposta de protocolo v1

Issues: [#53](https://github.com/c1c3ru/userfreezer/issues/53),
[#56](https://github.com/c1c3ru/userfreezer/issues/56).

**Situação:** design para implementação. NÃO existe servidor IPC autenticado
nesta revisão; o acesso direto da UI ao core NÃO satisfaz este contrato.

## Fronteira de confiança

- **Serviço privilegiado:** único processo autorizado a abrir alvos,
  fazer freeze, discard, commit ou modificar configuração.
- **Cliente UI:** processo sem privilégio. Autenticar no serviço não significa
  elevar privilégios; toda autorização é verificada no servidor.
- **Sem chaves em status.json:** relatório é confidencial para admins e
  não transporta segredo nem credenciais.
- **Escopo de proteção:** application-level até um driver/filtro ou mecanismo
  os-level comprovadamente ativo. Nunca inferir proteção do disco inteiro do
  estado Running, healthy ou do ícone da bandeja.

## Transportes

| SO | Transporte | Autenticação e autorização |
| --- | --- | --- |
| Windows 7+ | Named pipe local `\\.\pipe\DeepFreezerAdmin` | DACL explícita SYSTEM/Administrators; token do cliente verificado por impersonação no serviço (Win32 compatível com Win7) |
| Linux | Unix-domain socket em `/run/deepfreezer/admin.sock` | proprietário root e grupo administrador explicitamente criado; verificar credencial do peer (`SO_PEERCRED`) e política/grupo no processo do daemon |

Não abrir listener TCP nem expor comandos em localhost HTTP.
No Windows, criar descritor de segurança antes de publicar o pipe.
No Linux, controlar o socket antes do bind; unit socket-activated ou daemon
residente em vez do oneshot atual. Não conceder acesso a `config.json` ao
usuário da bandeja.

## API proposta (JSON, versão 1)

Envelope: `{"v":1,"id":"<uuid>","action":"status","params":{}}`.
Um pedido por mensagem; limite máximo de 16 KiB e timeout de 5 segundos.
Rejeitar dados JSON duplicados, campos desconhecidos, IDs repetidos em comandos
mutáveis, comandos que contenham caminhos não listados na configuração.

- `status`: lista de targets, modo e estado do último ciclo, com timestamp e
  saúde, sem hash ou senha.
- `freeze`: alvo cadastrado, opcional `verify`, autorização admin.
- `discard`: alvo cadastrado, exige confirmação de operação destrutiva
  vinculada ao id de transação e período de validade.
- `commit`: igual a discard, com segunda confirmação explícita; nunca
  commit por mudança de ícone.
- `set_config`: validação e backup atômico; nunca aceitar paths arbitrários.

Resultado: `{"v":1,"id":"<uuid>","ok":true,"result":{...}}` ou
`{"v":1,"id":"<uuid>","ok":false,"error":{"code":"...","message":"..."}}`.
Log de auditoria para todas as mutações, com UID/SID, alvo, resultado e ID,
sem segredos. Verificar versionamento e rollback de protocolo.

## Threat model mínimo

1. Usuário local não-admin tenta enviar `commit` diretamente ao pipe.
2. Usuário modifica JSON/ícone da UI para pular prompt de senha.
3. Cliente manda `../../Windows`, alvo diferente, JSON gigante,
   `action` inválida e comandos duplicados.
4. Atacante usa o mesmo ID de confirmação duas vezes.
5. Processo privilegiado falha entre commit e envio da resposta.
6. Reinicialização durante manutenção da configuração.
7. ACL do pipe/socket falha — listener DEVE falhar fechado.

## Critérios de liberação (não atendidos por este RFC)

- [ ] Serviço implementa transportes Windows 7 e Linux com ACL/SID/UID
      verificados *no servidor*.
- [ ] Processos sem autorização não conseguem chamar comandos mutáveis,
      mesmo sem UI.
- [ ] UI não lê config protegida nem invoca `DeepFreezer` diretamente.
- [ ] Testes de autorização em processo separado; Windows 7 SP1 em VM,
      usuários padrão, admins e contas de serviço.
- [ ] Timeout, cancelamento, replays, logs auditáveis e compatibilidade
      de cliente/protocolo testados.
- [ ] Validação de mudanças e operações destrutivas com backups e rollback
      documentados.

Sem esses testes, não declarar resolvida a issue #53 nem distribuir painel
com controles privilegiados.

## Endurecimento do socket Unix

O diretório do socket é validado antes do `bind`: deve pertencer ao UID
que inicia o serviço, não pode permitir escrita por grupo/outros e não
pode estar sob ancestral com symlink ou diretório gravável sem sticky bit.
O caso padrão `/run/deepfreezer` deve continuar root-owned; o socket
permite leitura de status, mas mutações exigem `SO_PEERCRED` uid=0.
Na limpeza, apenas o inode efetivamente criado pelo servidor é removido.
Isso reduz ataques à localização do socket, mas não é garantia contra
processos já executando como root. Testar em VM antes de produção.

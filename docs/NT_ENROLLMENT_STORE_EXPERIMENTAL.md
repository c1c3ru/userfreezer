# Leitura experimental do cadastro NT por handles — #63

**Estado:** pesquisa isolada, sem integração ao serviço, API pública, CLI ou
commit Windows de produção. **Não** utilizar como prova de segurança completa,
nem habilitar thaw --commit no Windows.

## Escopo implementado

- nt_enrollment_store_experimental.py calcula um nome de registro fixo
  SHA-256(caminho-canônico).dpapi. O cliente não escolhe o nome do arquivo.
- Abre um diretório de cadastro **já existente**, percorrendo componentes
  por handles NT sem seguir reparse points; não cria diretórios, nem altera ACLs.
- Consulta **o handle aberto** do diretório de cadastro e exige owner
  SYSTEM (S-1-5-18) ou BUILTIN\Administrators (S-1-5-32-544),
  DACL não nula e *somente* ACEs do tipo allow destinadas a esses dois SIDs.
  ACEs desconhecidas são rejeitadas; ACEs deny são permitidas.
- Lê o arquivo relativo ao handle do diretório via NtCreateFile e ReadFile,
  recusa reparse points e diretórios, limita o blob a 16 KiB e valida a DACL
  **do próprio arquivo** antes de retornar bytes.
- A identidade é desselada por DPAPI no contexto da **conta Windows atual**,
  vinculada ao caminho canônico. O plano experimental estrito continua
  conferindo o ID do objeto fixado antes de qualquer mutação.

## O que ainda não foi implementado

- **Provisionamento autorizado:** nenhuma função cria o registro ou prepara
  o diretório com ACLs adequadas. A segurança depende de diretório e arquivo
  preexistentes e geridos pelo administrador/conta de serviço.
- **Armazenamento/regravação atômicos e antirreplay:** um administrador ou
  processo com privilégios equivalentes pode substituir um registro antigo;
  DPAPI autentica o envelope, mas **não** fornece contador monotônico.
- **Resiliência a todos os ataques de namespace/ACL:** o drive letter,
  ancestrais, política de owner e os detalhes das permissões ainda requerem
  auditoria; validar apenas a DACL estática não prova impossibilidade de todas
  as corridas, compartilhamentos, hardlinks ou substituições.
- **Windows 7 SP1 em VM real:** CI Windows moderno com Python 3.8 e 3.12 não
  substitui testes no Windows 7 NTFS com serviço e token real, ACLs
  administrativas, processos concorrentes e falhas de energia.
- **Commit transacional:** plano experimental pode aplicar operações parciais.
  O commit Windows de produção permanece fail-closed.
- **Proteção integral do sistema operacional:** #49 e #54 dependem de filtros
  UWF/EWF/VHDX/OverlayFS validados após reboot e recovery, não de DPAPI.

## Evidências esperadas no próximo ciclo

Executar em VMs descartáveis com snapshot, sob a **mesma conta do serviço**,
testes de provisionamento/consulta e negativas para owner/DACL inseguros,
junctions em ancestrais/arquivo, token de usuário comum, corrupção/replay,
substituição concorrente e leitura de arquivo acima do limite.

Registrar no protocolo de evidências da v0.1.13 a edição/build do Windows,
hash do executável exato, principal de segurança, ACL antes/depois, resultado,
logs e a recuperação observada após reboot. A issue #63 só pode ser fechada
com auditoria final e todos os critérios de aceite demonstrados.

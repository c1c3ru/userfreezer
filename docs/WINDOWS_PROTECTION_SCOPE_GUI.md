# Proteção transparente no Windows: requisitos e estado real

## O teste de arquivo na Área de Trabalho

Na v0.2.0-rc.1, instalar o serviço, criar um arquivo no Desktop e
reiniciar **NÃO** resulta em rollback. O serviço cria por padrão um
`config.json` com `targets: []` e não configura nenhum volume.
Mesmo configurando toda a pasta do usuário como target, a API
`DeepFreezer` não intercepta `CreateFile`/gravações feitas pelo Explorer
ou por outros processos. Portanto, a configuração da pasta **não corrige**
a ausência de proteção do SO. Esse resultado é o comportamento atual,
mas não atende ao objetivo de proteção estilo Deep Freeze.

## Escolha de modo na interface

O painel administrativo possui agora **Escolher modo de proteção**:

- **Sistema/volume Windows:** opção pretendida para descartar alterações
  externas após reboot, disponível somente após validação de um filtro
  ou solução de boot realmente compatível e ativada; a tela mostra o
  resultado de detecção do sistema, mas nunca marca o filtro como ativo.
- **Meu perfil de usuário:** visualização de escopo de pasta para
  operações pela API, **não** proteção real contra Explorer.
- **Pasta específica:** visualização de um diretório escolhido para a
  API; o assistente NÃO cadastra nem passa a proteger essa pasta.

Esta tela é deliberadamente somente leitura: **não se deve dizer
"Configuração aplicada"** enquanto não existir a implementação de
provisionamento do modo escolhido. O serviço não usa caminho do usuário
para decidir qual perfil do Windows proteger automaticamente, porque
poderia selecionar a identidade da conta SYSTEM no boot e porque
reverter `AppData`/`Desktop`/arquivos pessoais sem consentimento expõe
o usuário à perda irreversível de dados.

O executável de serviço passa a aceitar `--ui` e abrir o painel local
ao ser executado fora do SCM. Abrir o painel não instala serviço nem
aumenta privilégios. O CI empacota Tkinter e o assistente para Windows
7/8 (Python 3.8) e 10/11 (Python 3.11); **a compatibilidade real de
Windows 7 SP1 ainda exige teste na VM.**

## Modos que podem oferecer rollback verdadeiro

- **Windows 10/11 com edição UWF compatível:** requer o recurso Unified
  Write Filter instalado, provisionado em volume suportado, ativação
  autorizada, reboot e prova de que o filtro intercepta gravações externas.
  A presença do `uwfmgr.exe` ou edição Enterprise **não prova** ativação.
- **Windows Embedded Standard 7/POSReady com EWF/FBWF presente:**
  requer filtros nativos e imagem licenciada; não presumir que estão
  habilitados.
- **Windows 7 comum (Home/Pro/Ultimate):** não há UWF nem EWF/FBWF
  disponíveis como recurso genérico neste projeto. O provisionador
  VHDX atual não suporta boot de Windows 7 comum. Necessita outro
  backend seguro e validado, não simples seleção de pasta.
- **Windows 10/11 Home/Pro:** o fluxo experimental VHDX não pode ser
  tratado como solução pronta. Exige provisionamento/recovery fora
  da sessão e provas em VM.

Nenhuma dessas estratégias é ativada automaticamente pelo instalador.
Antes de habilitar proteção de volume é obrigatório exigir **escolha
explícita da unidade/partição**, preservação de dados persistentes,
exclusões mínimas, snapshot/backup e possibilidade testada de
desativação e recuperação. Não habilitar sobre um perfil/volume em
máquina real sem revisão.

## Diagnóstico disponível para o teste humano

Na pasta do ZIP de scripts de serviço atualizado, executar no
PowerShell do Windows 7 ou mais recente:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\diagnose_protection.ps1

O script lê estado do serviço, edição Windows, configuração de targets,
status e presença/configuração consultável de UWF sem alterar arquivos,
volumes, BCD, permissões ou serviços. NÃO executa a proteção.

Registrar versão/edição/build, status e filtro em cada VM. Use isso para
atribuir a falha de teste externo corretamente às issues #49/#54 e
para definir qual backend precisa existir antes do próximo aceite.

## Próxima implementação necessária

1. Substituir a prévia de escolha por cadastro autenticado via broker,
   com UAC e confirmação explícita por administrador; sem escrita
   direta do frontend em config de serviço protegido.
2. Provisionar somente o filtro nativo para edições verificadas,
   com backups, exclusões necessárias, dry-run, autorização, reboot,
   inspeção ativa e rollback de configuração testado.
3. Para Windows 7 comum, projetar backend compatível distinto,
   com isolamento real das gravações externas e recuperação.
4. Até todas as provas em VM, exibir sempre **NÃO PROTEGIDO no nível
   do SO** e não encerrar as issues nem publicar a v0.2.0 estável.

# Histórico de mudanças

As versões anteriores à v0.1.6 não têm notas escritas; o que entrou nelas
está nos commits e nos pacotes da página de
[Releases](https://github.com/c1c3ru/userfreezer/releases).

## v0.1.10

**Release corretiva de v0.1.9.** A tag pública `v0.1.9` foi criada
com versão interna 0.1.8 e pacote Debian incorreto. Esta versão é
reconstruída a partir do código testado, **sem apagar nem reescrever
a tag anterior**. Não use `deepfreezer_0.1.8_all.deb` anunciado como v0.1.9.

### Correções e funcionalidades

- **#52:** resolvidos diretórios implícitos do overlay em `exists`,
  `is_dir`, `iterdir` e exclusões/recriação de ancestrais.
- **#51:** relatório de saúde do enforcement por alvo, com data UTC e
  `healthy/degraded/error`, protegido por permissões/ACL. `Running`
  sozinho não comprova proteção ativa.
- **#63:** commit Windows agora usa handles Win32 para fixar diretórios
  ancestrais durante operações, protegendo contra troca por junction;
  a auditoria de concorrência e o teste Win7 SP1 real ainda são necessários.
- **#53:** IPC administrativo local com credenciais do sistema
  operacional: Unix socket/`SO_PEERCRED` no Linux e Named Pipe com ACL
  e impersonation de token Windows. O serviço valida alvos e comandos,
  e `commit/discard` exigem desafios de uso único.
- **#56:** bandeja e painel multialvos integrados ao IPC; consulta de
  estado, problemas por alvo, mudanças pendentes, tamanho do overlay,
  exportação de diagnóstico e confirmações explícitas. A elevação
  ocorre por UAC ou polkit, sem tornar a janela inteira privilegiada.
- **#49/#54:** ferramentas de inspeção e roteiro manual para testar
  writes externos e rollback em VM, verificação de falhas nativas de
  UWF/EWF/FBWF. **Windows 7 comum não recebe suporte VHDX automático**;
  somente edições Embedded com filtro existente podem receber EWF/FBWF.
- **#55:** builds versionados verificam testes Windows/Linux (Python
  3.8/3.12), geração de pacote Debian, executáveis distintos Windows,
  instalação real do serviço no CI, hashes SHA-256, SPDX de nível
  artefato, dependências de build fixadas e proveniência do GitHub
  Actions. A publicação recusa sobrescrever tags existentes.

### Segurança, suporte e limitações

- **Escopo efetivo atualmente: application-level.** Sem UWF/EWF/FBWF
  ou outro mecanismo OS-level demonstravelmente ativo, alterações
  feitas diretamente por Explorer, editores e outras aplicações **não**
  são interceptadas pelo núcleo.
- O executável `deepfreezer_service_windows-7-8.exe` é construído
  com Python 3.8 e toolchain legado; **é preciso validar em uma VM
  Windows 7 SP1 real**. Os testes automatizados Windows executam
  em Windows moderno, mesmo com Python 3.8.
- A proteção completa contra todas as corridas de junction/links em
  Windows permanece sujeita a stress tests e revisão na
  [#63](https://github.com/c1c3ru/userfreezer/issues/63).
- **Ações administrativas**: UAC/polkit e direitos do serviço são
  necessários. Não reduzir ACL de `config.json`, overlay ou arquivos
  de serviço para fazer o painel funcionar.
- **Migração**: os overlays têm lock externo e payloads imutáveis.
  Pare serviços antigos antes de atualizar; não faça downgrade com
  operações pendentes. `thaw(commit=True)` continua sem transação
  multi-arquivo: falhas no meio podem produzir commit parcial.
- O painel gráfico, a operação UAC e o comportamento de boot/rollback
  OS-level precisam de ensaios manuais nas VMs alvo antes de uso em
  produção. Consulte `docs/WIN7_MANUAL_TEST.md` e
  `ui/README.md`.
- **#64:** a v0.1.9 inconsistente permanece publicada para auditoria;
  esta v0.1.10 a substitui na distribuição, sem retagging silencioso.

## v0.1.9

Atualização de segurança e recuperação do congelamento em nível de aplicação.
Os serviços continuam gerenciando apenas operações feitas através da API do
DeepFreezer; **esta versão não intercepta gravações externas de outros processos**.

### Corrigido

- **#50 — Configuração no Windows:** o instalador cria `config.json` em
  UTF-8 sem BOM inclusive no PowerShell antigo, e o serviço continua lendo
  arquivos legados que contêm BOM. Mantido o código compatível com Python 3.8.
- **#45 — Lock após encerramento inesperado:** o lock passa a usar travamento
  pelo sistema operacional (`msvcrt.locking` no Windows,
  `fcntl.flock` no Linux), liberado quando o processo termina.
- **#46 — Integridade de escritas repetidas:** cada operação confirmada usa
  payload próprio; o journal aponta para essa versão, sem permitir que
  uma gravação interrompida altere a última versão confirmada. Leitura
  de journals antigos preservada.
- **#47 — Isolamento do commit:** validação dos caminhos, bloqueio de
  symlinks/junctions/reparse points detectados e operações POSIX via
  `dir_fd`/`O_NOFOLLOW` para reduzir escape da árvore protegida.
- **#48 — Descarte do overlay:** erro de remoção deixa de ser ignorado.
  A trava é externa ao diretório de overlay e o marcador
  `<overlay>.discarding` permite continuar a limpeza após interrupção.
- **CI:** corrigido fixture de recuperação de journal após a evolução
  do formato; a suíte foi executada em Windows e Linux com Python
  3.8 e 3.12.

### Compatibilidade e limitações

- **Windows 7/8:** permanece disponível a variante compilada com Python 3.8
  (`deepfreezer_service_windows-7-8.exe`). A suíte passou no runner
  Windows com Python 3.8, mas **o executável ainda não foi testado
  em Windows 7 real/VM**. Validar antes de uso em produção.
- **Segurança Windows:** a troca concorrente de diretórios por junctions
  ainda exige hardening nativo baseado em handles; acompanhamento na
  [issue #63](https://github.com/c1c3ru/userfreezer/issues/63).
- **Mudança de layout:** a trava do núcleo agora fica em
  `<overlay>.lock`, ao lado do overlay, e pode permanecer após
  `thaw()`. Não apague o arquivo de lock enquanto alguma instância
  estiver ativa; não execute versões antiga e nova simultaneamente.
- **Downgrade:** versões antigas do núcleo não interpretam payloads
  versionados novos. Não fazer downgrade com overlay pendente sem
  primeiro documentar/recuperar seu estado.
- **Escopo:** operações `thaw(commit=True)` não implementam transação
  multi-arquivo; um erro de I/O durante commit pode deixar aplicação
  parcial, mesmo quando o erro é corretamente sinalizado.

### Nota de publicação

A tag v0.1.9 foi criada antes de VERSION e deste changelog serem
atualizados, gerando inicialmente o artefato
`deepfreezer_0.1.8_all.deb`. A correção e a retificação da release
estão acompanhadas na [issue #64](https://github.com/c1c3ru/userfreezer/issues/64);
**não renomeie o .deb antigo como se fosse a versão 0.1.9**.

## v0.1.8

Corrige a falha de inicialização do serviço no Windows. Quem viu o
`Start-Service DeepFreezer` falhar com o evento 7009 deve atualizar o
`.exe` e reinstalar; quem já tem o serviço rodando não precisa fazer
nada.

### Corrigido

- **O serviço não iniciava em algumas máquinas Windows 10**, com o evento
  7009 no Visualizador de Eventos ("Tempo limite (30000 ms) atingido ao
  aguardar a conexão do serviço DeepFreezer"), sem traceback do Python e
  sem nada no `deepfreezer.log`. O programa decidia, antes de se
  apresentar ao Windows, se tinha sido aberto com duplo clique, e nessa
  decisão abria uma janela de aviso. Num serviço essa janela abre numa
  área de trabalho invisível: ninguém pode fechá-la, o processo fica
  parado esperando e o Windows desiste em 30 segundos. A decisão
  dependia da variável `SESSIONNAME`, que o serviço herda quando ela
  existe no ambiente de sistema — por isso a falha acontecia em algumas
  máquinas e não em outras. Agora o programa se apresenta ao Windows
  primeiro e só mostra a janela se descobrir, pelo erro que o próprio
  Windows devolve, que ninguém o iniciou como serviço.

### Adicionado

- **7 testes do despacho do serviço Windows**, que rodam em qualquer
  sistema (os módulos do pywin32 são substituídos por dublês) e checam a
  ordem das chamadas. Um deles é o guarda desta regressão: com
  `SESSIONNAME` presente, nenhuma janela pode abrir. Com os anteriores,
  são 70 testes no total.

## v0.1.7

Versão de embalagem: o programa em si não mudou desde a v0.1.6, só o
nome dos arquivos publicados e o caminho de instalação no Windows. Quem
já tem o serviço instalado e funcionando não precisa fazer nada.

### Alterado

- **O nome de cada `.exe` agora diz para qual Windows ele serve.** Eram
  `deepfreezer_service.exe` e `deepfreezer_service_win7.exe`, e não dava
  para saber pelo nome que o primeiro é o de Windows 10 e 11. Passaram a
  ser `deepfreezer_service_windows-10-11.exe` e
  `deepfreezer_service_windows-7-8.exe`. Toda release passa a trazer, no
  fim das notas, uma tabela dizendo qual arquivo baixar para cada
  sistema.
- **Não é mais preciso renomear o `.exe` no Windows 7.** Antes, quem
  usava o binário de Windows 7 tinha que renomeá-lo para
  `deepfreezer_service.exe` antes de instalar. Agora o instalador aceita
  os dois nomes novos e os dois antigos e, se os dois estiverem na mesma
  pasta, escolhe sozinho o certo para o Windows em que está rodando.
  Avisa também quando o `.exe` de 10/11 foi posto num Windows mais
  antigo, em vez de deixar o serviço falhar sem explicação.

## v0.1.6

Versão de correções e testes. Nada muda na forma de usar: quem está na
v0.1.5 pode atualizar sem mexer em configuração nem no overlay já
existente.

### Corrigido

- **Descongelar deixava o alvo travado no Windows.** O `thaw()` apagava a
  pasta do overlay enquanto ainda segurava o arquivo de trava lá dentro.
  No Linux isso passa batido, mas o Windows não deixa apagar arquivo
  aberto, então a pasta sobrava pela metade e, na próxima vez que o mesmo
  alvo era aberto, o programa reclamava de overlay corrompido e só voltava
  a funcionar apagando a sobra na mão. Agora a trava é solta antes de
  apagar.
- **`write('')` e `write('/')` estouravam um erro confuso.** Escrever num
  caminho vazio ou só com a barra escapava da validação e terminava num
  `NotADirectoryError` vindo de dentro do código, sem explicar nada. Agora
  dá a mesma mensagem clara de caminho inválido que os outros comandos já
  davam.

### Adicionado

- **47 testes do núcleo de congelamento**, cobrindo congelar, escrever no
  overlay com o disco intacto, descongelar, gravar as mudanças de verdade
  e recuperar o journal depois de uma queda. Com os testes já existentes
  da detecção de Windows, são 63 no total, e rodam com `python run_tests.py`.
- **Verificação automática a cada envio de código**, rodando essa suíte em
  Linux e Windows, no Python 3.8 e no 3.12, a cada push e a cada pull
  request na `main`.

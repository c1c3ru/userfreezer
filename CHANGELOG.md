# Histórico de mudanças

As versões anteriores à v0.1.6 não têm notas escritas; o que entrou nelas
está nos commits e nos pacotes da página de
[Releases](https://github.com/c1c3ru/userfreezer/releases).

## Não publicado

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

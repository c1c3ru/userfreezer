# Instalar e testar o DeepFreezer no Windows

Guia único do caminho de Windows: o que baixar, como instalar,
configurar, iniciar, testar e desinstalar o serviço — e o que dá para
conferir sem uma máquina Windows e o que só uma máquina de verdade
responde. Escrito contra a v0.1.7.

O caminho recomendado é baixar o `.exe` da sua versão do Windows e o
`deepfreezer-windows-service-scripts.zip`, colocar tudo na mesma pasta
e dar duplo clique em `install.bat`. É o único caminho que o CI
instala, inicia, confirma e desinstala de verdade num runner Windows a
cada build.

Documentos relacionados: `packaging/windows/README.md` (referência
completa, incluindo a proteção a nível de SO), `packaging/DOWNLOADS.md`
(tabela de qual arquivo baixar) e `STATUS_SERVICO.md` (investigação em
aberto do Evento 7009 no Windows 10).

## O que baixar e qual caminho escolher

Tudo sai da [página de Releases](https://github.com/c1c3ru/userfreezer/releases).
Sem esperar uma tag, os mesmos arquivos ficam como artifacts do run mais
recente do workflow `build-packages`, na aba Actions — esses expiram em
cerca de 90 dias.

| Arquivo | Para que serve | Precisa de Python na máquina |
| --- | --- | --- |
| `deepfreezer_service_windows-10-11.exe` | O serviço para Windows 10 e 11, compilado com Python 3.11. | Não |
| `deepfreezer_service_windows-7-8.exe` | O mesmo serviço para Windows 7, 8 e 8.1, compilado com Python 3.8. | Não |
| `deepfreezer-windows-service-scripts.zip` | `install.bat`, `uninstall.bat`, os três `install_service_*.ps1` e `harden_acl.ps1`. | Não |
| `deepfreezer-windows-os-level.zip` | `os_detect.py` e os scripts de UWF, EWF/FBWF e VHDX diferencial. | Sim, para rodar `os_detect.py` |

**Não é preciso renomear nada.** O `install_service_exe.ps1` aceita os
dois nomes acima e os dois antigos (`deepfreezer_service.exe` e
`deepfreezer_service_win7.exe`, usados até a v0.1.6) e, com os dois na
mesma pasta, escolhe sozinho pelo número de build do Windows em que
está rodando. O binário instalado em `C:\Program Files\DeepFreezer`
sempre se chama `deepfreezer_service.exe`, venha de qual arquivo vier,
então o `-Uninstall` funciona igual nos dois casos.

Há três maneiras de registrar o serviço, e elas não têm o mesmo grau de
confiança:

- **`.exe` mais `install.bat`** — o recomendado. Dispensa Python na
  máquina alvo e é o único caminho que o CI instala, inicia e
  desinstala de verdade num Windows real antes de publicar.
- **`install_service_pywin32.ps1`** — a partir do repositório clonado,
  com Python e `pywin32` instalados. Nunca foi executado numa máquina
  real.
- **`install_service_nssm.ps1`** — a partir do repositório clonado, com
  `nssm.exe` no PATH e sem `pywin32`. Também nunca foi executado numa
  máquina real.

Em qualquer um dos três o serviço se chama `DeepFreezer`, roda como
`LocalSystem` e fica em modo de início automático.

## Instalar pelo `install.bat`

1. Crie uma pasta e coloque nela o `.exe` da sua versão do Windows e
   todo o conteúdo do `deepfreezer-windows-service-scripts.zip`, lado a
   lado, sem subpastas.
2. Dê duplo clique em `install.bat`. Ele pede elevação de administrador
   sozinho e chama `install_service_exe.ps1` com
   `-ExecutionPolicy Bypass`, então não é preciso abrir o PowerShell nem
   mexer em política de execução de script.
3. Espere a mensagem
   `instalado. revise C:\ProgramData\DeepFreezer\config.json e rode: Start-Service DeepFreezer`.

O que o script faz por baixo, na ordem:

- confere que está rodando como Administrador e aborta se não estiver;
- escolhe o `.exe` da pasta e imprime qual usou e qual é o build do
  Windows, avisando quando o binário de 10/11 foi posto num Windows
  mais antigo;
- cria `C:\Program Files\DeepFreezer` e `C:\ProgramData\DeepFreezer`;
- copia o `.exe` para `C:\Program Files\DeepFreezer\deepfreezer_service.exe`;
- cria `C:\ProgramData\DeepFreezer\config.json` com `{"targets": []}` se
  ele ainda não existir, ou seja, um config vazio que o serviço recusa
  até você preencher;
- registra o serviço com `deepfreezer_service.exe install`, espera até
  dez segundos ele aparecer no SCM e só então roda
  `sc.exe config DeepFreezer obj= LocalSystem` e
  `sc.exe config DeepFreezer start= auto`.

O script não inicia o serviço, de propósito: a ideia é que você revise o
`config.json` antes.

Para rodar o `.ps1` à mão, abra o PowerShell **como Administrador**,
entre na pasta com `cd` e chame `.\install_service_exe.ps1` — com o `.\`
na frente. Sem ele o PowerShell responde "não é reconhecido como
cmdlet" mesmo com o arquivo bem ali.

## Configurar o `config.json`

O arquivo fica em `C:\ProgramData\DeepFreezer\config.json` e usa o mesmo
formato do Linux. A variável de ambiente `DEEPFREEZER_CONFIG` sobrepõe
esse caminho, mas ela precisa existir no ambiente em que o serviço roda,
não na sua sessão de usuário.

```json
{
  "targets": [
    {"target": "C:\\lab\\app", "overlay": null, "verify": false}
  ]
}
```

| Campo | O que faz | Padrão |
| --- | --- | --- |
| `target` | A pasta congelada. Caminho absoluto; em JSON as barras invertidas vão dobradas. | obrigatório |
| `overlay` | Onde a camada de mudanças vive. | `null`, que vira `<alvo>.dfreezer` ao lado do alvo |
| `verify` | Registra o sha256 de cada arquivo no manifesto. Congela mais devagar em árvores grandes. | `false` |

Dá para listar quantos alvos quiser; o serviço percorre todos a cada
start e um alvo com erro não impede os outros.

Dois cuidados na hora de preencher:

- O overlay não pode ficar dentro do alvo. O core recusa com
  `overlay nao pode ficar dentro do alvo` e aquele alvo não congela.
- Com `targets` vazio o serviço sobe e fica `Running`, mas registra
  `config sem 'targets'` no log e não protege nada. É exatamente assim
  que o `install.bat` deixa o arquivo, então preencher antes do primeiro
  `Start-Service` é um passo obrigatório, não um ajuste fino.

## Iniciar o serviço e conferir que o congelamento rodou

Num PowerShell elevado:

```powershell
Start-Service DeepFreezer
Get-Service DeepFreezer
```

O serviço deve ficar `Running`, com `StartType` igual a `Automatic`. A
cada start, seja no boot ou manual, ele percorre os alvos do config e
para cada um descarta o overlay da sessão anterior sem commit, recongela
a árvore e restringe a ACL do overlay com `icacls` a Administradores e
SYSTEM, removendo a herança.

Três lugares para confirmar que isso aconteceu de verdade:

- **O log**, em `C:\ProgramData\DeepFreezer\deepfreezer.log`, rotativo em
  1 MB com três backups. A primeira linha do start é
  `iniciado sem argumentos (frozen=True): despachando pro SCM` e cada
  alvo rende uma linha no formato
  `C:\lab\app: congelado (412 caminhos, 0.180s, overlay=C:\lab\app.dfreezer)`.
- **O overlay**, a pasta `<alvo>.dfreezer`. Se ela não existe, o
  congelamento não rodou, por mais que o serviço apareça como `Running`.
- **O Visualizador de Eventos**, log Application, fonte DeepFreezer, que
  recebe as mesmas mensagens. É onde procurar quando o congelamento
  falha durante o boot.

A ACL se confere com `icacls C:\lab\app.dfreezer`, que deve listar
apenas `BUILTIN\Administradores` e `NT AUTHORITY\SYSTEM`. Para reaplicar
isso à mão existe o
`harden_acl.ps1 -OverlayPath "C:\lab\app.dfreezer"`.

### Se o `Start-Service` falhar com Evento 7009

`Tempo limite (30000 ms) atingido ao aguardar a conexão do serviço
DeepFreezer`, sem traceback e sem nada no log, é a falha que o
`STATUS_SERVICO.md` investiga. A causa encontrada e corrigida foi uma
caixa de mensagem modal que abria na sessão 0 antes do handshake com o
SCM quando a variável `SESSIONNAME` existia no ambiente de sistema. A
correção está na v0.1.6 em diante; se ainda acontecer, o dado que decide
o próximo passo é o horário da primeira linha do `deepfreezer.log`
comparado com o do evento 7009 — no instante do `Start-Service` é um
bloqueio no handshake, cerca de 30 s depois é a extração do PyInstaller
`--onefile`. O `STATUS_SERVICO.md` traz os comandos prontos.

### O que "congelado" significa aqui

Vale lembrar, porque muda o que esperar do teste: o DeepFreezer é
*application-level*. Congelar é tirar um manifesto com hash, tamanho e
data da árvore; o serviço nunca move os arquivos reais nem intercepta
gravações do sistema. Só volta atrás o que foi escrito pela API ou pela
CLI do `deepfreezer.py`. Um arquivo criado pelo Explorer grava direto na
árvore e vira parte do novo estado congelado no próximo start.

## Caminhos alternativos: pywin32, NSSM e Windows 7/8

Os dois primeiros partem do repositório clonado e pedem PowerShell
elevado. Nenhum dos dois foi executado numa máquina Windows real até
hoje.

**pywin32**, serviço nativo, exige Python 3 e `pywin32` no PATH do
sistema:

```powershell
.\install_service_pywin32.ps1
.\install_service_pywin32.ps1 -Uninstall
```

Ele copia `deepfreezer.py` e `deepfreezer_service.py` para
`C:\Program Files\DeepFreezer`, cria o `config.json` a partir de
`packaging\config.example.json` e registra o serviço com
`python deepfreezer_service.py install`. Atenção a uma diferença: o
exemplo copiado traz o alvo `/opt/lab-app`, um caminho Linux. Troque por
um caminho do Windows antes de iniciar.

**NSSM**, para quando não dá para instalar `pywin32` na máquina alvo,
exige `nssm.exe` no PATH:

```powershell
.\install_service_nssm.ps1 -PythonExe "C:\Python312\python.exe"
.\install_service_nssm.ps1 -Uninstall
```

Aqui o serviço roda `deepfreezer_service.py --foreground`, que faz o
congelamento uma vez e fica residente enquanto o NSSM mantiver o
processo vivo. Diferente dos outros dois scripts, este inicia o serviço
no fim da instalação, antes de você revisar o config.

**Windows 7, 8 e 8.1** usam o mesmo fluxo do `install.bat`, só com o
`deepfreezer_service_windows-7-8.exe` na pasta. O binário de 10/11 é
compilado com Python 3.11 e o Python deixou de suportar Windows 7 a
partir da versão 3.9, então lá o processo simplesmente não inicia,
qualquer que seja o script. A variante de 7/8 sai do job
`build-exe-win7` com Python 3.8 e nunca foi iniciada num Windows 7
real. Se ela também não subir, o próximo suspeito é o bootloader do
PyInstaller, não mais a versão do Python.

## Roteiro de teste numa máquina Windows real

Use uma VM descartável, nunca uma máquina de produção. Prepare um alvo
pequeno antes de iniciar o serviço:

```powershell
New-Item -ItemType Directory -Force C:\lab\app | Out-Null
"original" | Out-File -Encoding ascii C:\lab\app\f.txt
```

Com `C:\lab\app` no `config.json`, percorra a lista. Os quatro primeiros
itens o CI já cobre e servem como sanidade; do quinto em diante só uma
máquina real responde.

- [ ] `Start-Service DeepFreezer` deixa o serviço `Running` e o log
      registra o congelamento do alvo.
- [ ] A pasta `C:\lab\app.dfreezer` foi criada.
- [ ] `icacls C:\lab\app.dfreezer` mostra apenas Administradores e
      SYSTEM.
- [ ] `uninstall.bat` tira o serviço do SCM sem erro.
- [ ] Duplo clique em `install.bat` como usuário comum sobe o prompt de
      UAC sozinho. O runner do CI já roda elevado, então essa parte
      nunca é exercitada lá.
- [ ] Reiniciar a máquina e confirmar no log que o congelamento rodou no
      boot. O CI só inicia o serviço à mão.
- [ ] O serviço continua `Running` passados os 30 s da janela do SCM.
- [ ] Logado como usuário padrão, abrir `C:\lab\app.dfreezer` é negado.
- [ ] `Stop-Service DeepFreezer` sem privilégio de administrador é
      negado.
- [ ] Uma escrita pela CLI volta atrás no próximo boot:
      `python deepfreezer.py write C:\lab\app f.txt "mudado"`, reiniciar,
      e o `cat` do mesmo arquivo volta a dizer `original`. Isso exige
      Python e uma cópia do `deepfreezer.py` na máquina, porque o `.exe`
      não expõe a CLI.
- [ ] `install_service_pywin32.ps1` instala, inicia e desinstala sem
      erro.
- [ ] `install_service_nssm.ps1` instala, inicia e desinstala sem erro.
- [ ] Num Windows 7 real, o `deepfreezer_service_windows-7-8.exe` de
      fato inicia como serviço.

Um resultado que **não** é falha: criar um arquivo em `C:\lab\app` pelo
Explorer e ver que ele sobrevive ao boot. Isso é o limite do escopo
*application-level*, não um bug.

## Desinstalar

Duplo clique em `uninstall.bat`, que também pede elevação sozinho, ou à
mão num PowerShell elevado:

```powershell
.\install_service_exe.ps1 -Uninstall
```

O script para o serviço se ele estiver rodando, chama `remove` e só
retorna depois de confirmar que ele sumiu do SCM, esperando até dez
segundos. Essa espera existe porque o `DeleteService` do Windows é
assíncrono: o serviço ainda aparece no `Get-Service` por um instante
depois do `remove`. Os equivalentes são
`.\install_service_pywin32.ps1 -Uninstall` e
`.\install_service_nssm.ps1 -Uninstall`.

A desinstalação remove o serviço e mais nada. Ficam em disco:

- `C:\Program Files\DeepFreezer`, com o `.exe` ou os `.py` copiados na
  instalação;
- `C:\ProgramData\DeepFreezer`, com o `config.json` e o
  `deepfreezer.log`;
- os overlays `<alvo>.dfreezer`, intocados.

Se a ideia é devolver as árvores ao estado congelado antes de limpar
tudo, rode `python deepfreezer.py thaw C:\lab\app` sem `--commit` em
cada alvo enquanto ainda tiver a CLI por perto; use `--commit` se quiser
o contrário, aplicar as mudanças da sessão na árvore real. Depois disso
as três pastas acima podem ser apagadas à mão.

## O que dá para verificar sem Windows e o que exige máquina real

Um caminho é testado de ponta a ponta a cada build: o `.exe` de Windows
10/11 instalado por `install_service_exe.ps1`. Todo o resto vai de desk
check até alguém rodar numa máquina de verdade.

| Peça | Status | Como foi verificado, ou o que falta |
| --- | --- | --- |
| `.exe` de 10/11 mais `install_service_exe.ps1` | Testado de verdade | Job `test-windows-service`: baixa o `.exe` e o zip como um usuário faria, instala, confere o `StartType`, inicia, confirma `Running`, confirma o overlay criado a partir de um alvo real, roda `icacls`, para e desinstala. |
| Suíte de testes | Testada em Windows | O workflow `tests.yml` roda os 70 testes a cada push e pull request na `main`, em Linux e Windows, no Python 3.8 e no 3.12. |
| Build dos dois `.exe` | Testado | Jobs `build-exe` e `build-exe-win7` num runner `windows-latest` com pywin32 e PyInstaller; conferem que o binário existe e tem tamanho plausível. |
| Start do serviço depois da correção do 7009 | Verde num Windows real | Job `test-windows-service` num Windows Server 2022: a linha de log nova aparece cerca de 0,5 s depois do `Start-Service`. Não reproduz a falha original, porque lá `SESSIONNAME` não existe no ambiente de sistema. |
| O mesmo start no Windows 10 do usuário | A verificar | É a pendência aberta do `STATUS_SERVICO.md`. |
| `.exe` de Windows 7/8 | Só o build | Compila com Python 3.8. Ninguém confirmou que ele inicia num Windows 7 real. |
| Prompt de UAC do `install.bat` | Não verificado | O runner do CI já roda elevado, então o ramo que pede elevação nunca é exercitado. |
| Congelamento no boot | Não verificado | O CI inicia o serviço com `Start-Service`; nunca reinicia a máquina. |
| `install_service_pywin32.ps1` | Não verificado | Nenhuma execução real. A lógica de congelamento que ele compartilha com o Linux foi exercitada em Linux, sem `icacls`, e falhou de forma controlada como esperado. |
| `install_service_nssm.ps1` | Não verificado | Nenhuma execução real; o sandbox de desenvolvimento é Linux, sem NSSM. |
| `classify()` do `os_detect.py` | Testado | 16 testes que rodam em qualquer SO, dentro da suíte do `run_tests.py`. |
| `get_os_info()` do `os_detect.py` | Não verificado | Lê o registro do Windows. Falta conferir se os `EditionID` reais batem, principalmente nas edições Embedded e POSReady do Windows 7, que variam por OEM. |
| `select_strategy.ps1` | Lógica testada | Leitura do JSON e roteamento por estratégia exercitados de ponta a ponta, chamando `os_detect.py` de verdade. |
| `uwf_setup.ps1` e `ewf_fbwf_setup.ps1` | Só sintaxe e documentação | Sintaxe validada pelo parser do PowerShell; comandos conferidos contra a documentação da Microsoft. Nunca protegeram nada de verdade. |
| `vhdx_diff_setup.ps1` e `vhdx_diff_reset.ps1` | Não verificado, maior risco | Reconfiguram o boot da máquina; um erro pode deixá-la sem bootar. Só em VM descartável. O `reset` ainda depende de alguém rodá-lo de um ambiente de manutenção antes de cada boot normal, o que não foi automatizado. |
| Bandeja do sistema (`ui/`) | Lógica testada com stubs | Renderização do ícone e aparência dos diálogos do Tk só numa sessão gráfica real. |

A proteção a nível de SO é uma decisão à parte, para quando o escopo
*application-level* não basta. `python os_detect.py` na máquina alvo diz
qual estratégia cabe: `uwf` nas edições Enterprise, Education e IoT
Enterprise do Windows 10 e 11; `ewf_fbwf` no Windows 7 Embedded Standard
e POSReady; `vhdx_diff` em Home e Pro de qualquer versão, e em qualquer
edição que o detector não reconheça. Windows 8 e 8.1 caem em
`unsupported`. O detalhamento está em `packaging/windows/README.md`.

Sem Windows por perto dá para revisar o código dos scripts, rodar a
suíte com `python run_tests.py` e validar a sintaxe do PowerShell. Tudo
que depende do SCM, do UAC, do registro, do `icacls` ou de um boot de
verdade só se resolve numa máquina Windows, e o roteiro da seção
anterior é a lista do que rodar quando houver uma.

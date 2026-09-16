# DeepFreezer no Windows

**Duplo clique no `.exe` não faz nada útil por si só.** O
`deepfreezer_service.exe` só protege alguma coisa depois de instalado
e iniciado como serviço do Windows — é o serviço, rodando no boot, que
descarta as mudanças da sessão anterior e recongela. Rodá-lo com duplo
clique direto agora mostra uma caixa de mensagem explicando isso (em
vez de simplesmente não fazer nada, como acontecia antes); ele ainda
não faz o enforcement nesse caso. Siga um dos dois caminhos abaixo.

Duas formas de registrar o servico — escolha uma:

## Proteção a nível de SO (qualquer gravação, de qualquer programa)

O que está descrito no resto deste arquivo é a proteção *application-level*
do core (`deepfreezer.py`): só reverte gravações feitas pela própria
API/CLI, não uma gravação qualquer do Explorer ou de outro programa
(ver "Limite honesto" no README da raiz). Para proteger a máquina
inteira contra qualquer gravação, a estratégia depende da edição do
Windows instalada, porque nem toda edição tem um write filter nativo:

| Versão | Edições com write filter nativo | Estratégia | Edições sem (Home/Pro) |
|---|---|---|---|
| Windows 11 | Enterprise, Education, IoT Enterprise | `uwf` (Unified Write Filter, via `uwfmgr.exe`) | `vhdx_diff` |
| Windows 10 | Enterprise, Education, IoT Enterprise | `uwf` | `vhdx_diff` |
| Windows 7 | Embedded Standard, POSReady | `ewf_fbwf` (Enhanced/File-Based Write Filter) | `vhdx_diff` |

`vhdx_diff` (disco diferencial VHDX no boot) é o único caminho pra
Home/Pro em qualquer versão — funciona em qualquer edição, mas exige
reprovisionar a máquina nesse esquema de boot, bem mais pesado que
instalar um serviço.

`packaging/windows/os_detect.py` identifica automaticamente a versão +
edição da máquina e devolve qual estratégia usar:

```
python os_detect.py
```

```json
{
  "windows_version": "11",
  "edition": "Enterprise",
  "strategy": "uwf",
  "reason": "edicao com Unified Write Filter nativo",
  "product_name": "Windows 11 Enterprise",
  "build": 22631
}
```

Windows 8/8.1 caem em `"strategy": "unsupported"` (fora do escopo
atual — só 7/10/11). Qualquer `EditionID` não reconhecido pelo
detector cai no fallback seguro `vhdx_diff`, nunca assume um write
filter nativo sem confirmar contra uma lista explícita.

A orquestração de cada estratégia mora em `packaging/windows/os_level/`:

- `select_strategy.ps1` — roda `os_detect.py` e aponta pro script certo.
- `uwf_setup.ps1` — instala o feature, protege volume, exclui caminhos,
  ativa/desativa o filtro (Windows 10/11 Enterprise/Education/IoT).
- `ewf_fbwf_setup.ps1` — equivalente pro Windows 7 Embedded/POSReady
  (detecta se a imagem tem `ewfmgr.exe` ou `fbwfmgr.exe` e usa o que
  existir).
- `vhdx_diff_setup.ps1` / `vhdx_diff_reset.ps1` — provisiona o boot por
  disco diferencial VHDX (Home/Pro, qualquer versão) e recria o
  diferencial pra "resetar" a máquina.

**Status — o que foi verificado:**

- A lógica pura de `os_detect.py` (`classify()`) tem 16 testes que
  rodam em qualquer SO, todos passando.
- Os quatro scripts em `os_level/` têm sintaxe validada pelo parser
  real do PowerShell (`[System.Management.Automation.Language.Parser]::ParseFile`,
  via PowerShell 7 instalado no sandbox Linux usado pra desenvolver
  este repo) e a lógica de leitura do JSON + roteamento por estratégia
  em `select_strategy.ps1` foi testada de ponta a ponta (chamando
  `os_detect.py` de verdade e simulando cada valor de `strategy`).
- Os comandos `uwfmgr`/`ewfmgr`/`fbwfmgr`/`diskpart`/`dism`/`bcdboot`
  usados foram conferidos contra a documentação oficial da Microsoft
  (links abaixo), não contra uma execução real.

**Status — o que NÃO foi verificado, porque não há Windows real
disponível pra testar:**

- A leitura de verdade do registro em `get_os_info()` — se os valores
  de `EditionID` batem com o que uma máquina real devolve, principalmente
  nas edições Embedded/POSReady do Windows 7, que variam mais por OEM.
- Se `uwf_setup.ps1`/`ewf_fbwf_setup.ps1` de fato protegem/revertem
  gravações numa máquina real, ponta a ponta.
- `vhdx_diff_setup.ps1`/`vhdx_diff_reset.ps1` inteiros — é a parte mais
  arriscada do projeto (reconfigura o boot; um erro pode deixar a
  máquina sem bootar) e a menos testável sem hardware/VM real. **Nunca
  rode isso numa máquina de produção sem validar antes numa VM
  descartável.**
- `vhdx_diff_reset.ps1` também deixa uma lacuna deliberada: ele recria
  o disco diferencial, mas alguém ainda precisa *rodá-lo* de um
  ambiente de manutenção (WinPE/recuperação) antes de cada boot normal
  — automatizar isso (customizando a imagem do WinRE pra chamar o
  script sozinha) não foi implementado, por ser a etapa de maior risco
  de todo o processo e a menos documentada.

Antes de confiar em qualquer uma dessas estratégias em produção, rode
`python os_detect.py` numa máquina de cada versão/edição alvo pra
conferir o resultado, e teste o script correspondente numa VM
descartável primeiro.

Fontes usadas na implementação:
[UWF feature](https://learn.microsoft.com/en-us/windows/configuration/unified-write-filter/),
[uwfmgr.exe reference](https://learn.microsoft.com/en-us/windows/configuration/unified-write-filter/uwfmgrexe),
[EWF Manager](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ff794092(v=winembedded.60)),
[Deploy Windows with a VHDX (native boot)](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/deploy-windows-on-a-vhd--native-boot),
[Create vdisk (diskpart)](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-server-2012-r2-and-2012/gg252579(v=ws.11)).

## 1. pywin32 (serviço nativo)

Requer `pip install pywin32` na máquina alvo.

```
.\install_service_pywin32.ps1
```

Roda como serviço `DeepFreezer` (classe `win32serviceutil.ServiceFramework`
em `deepfreezer_service.py`), sob a conta `LocalSystem` (`NT AUTHORITY\SYSTEM`).

## 2. NSSM (sem pywin32)

Requer o utilitário [NSSM](https://nssm.cc) (`nssm.exe`) no PATH da máquina alvo.
Não depende de pywin32: o mesmo `deepfreezer_service.py` roda em modo
`--foreground` (só faz o enforcement e fica residente) e o NSSM cuida
do ciclo de vida do processo.

```
.\install_service_nssm.ps1 -PythonExe "C:\Python312\python.exe"
```

Em ambos os casos o serviço, ao iniciar: para cada alvo do config
descarta o overlay da sessão anterior (thaw sem commit), recongela a
árvore e restringe a ACL do overlay (`icacls`) a Administradores e
SYSTEM — ver `harden_acl.ps1` para reaplicar isso manualmente.

**Importante — o que o serviço não faz:** o freezer é *application-level*
(ver "Limite honesto" no README da raiz). "Congelar" aqui é só tirar um
manifesto (hash/tamanho/mtime) da árvore — o serviço nunca move os
arquivos reais nem intercepta gravações do SO. Um arquivo criado direto
pelo Explorer (ou por qualquer outro programa que não passe pela API/CLI
do `deepfreezer.py`) grava direto na árvore real e **não** é descartado
no próximo boot: ele simplesmente vira parte do novo estado "congelado"
no próximo `freeze()`. Só é revertido o que foi escrito através de
`df.write()`/`df.rm()`/`df.mkdirs()` (a API do core). Proteger contra
qualquer gravação, de qualquer processo, exigiria um driver de nível de
kernel (minifilter no Windows, overlayfs no boot no Linux) — fora do
escopo deste core.

## Empacotando com PyInstaller

Para não depender de um Python instalado na máquina alvo, gere um
executável único. **Já automatizado** em
`.github/workflows/build-packages.yml` (job `build-exe`, roda num
runner `windows-latest` de verdade — é como este `.exe` foi de fato
buildado, já que este repositório foi desenvolvido num sandbox Linux):
dispare o workflow manualmente (aba Actions → Run workflow) ou publique
uma tag `vX.Y.Z` pra também anexar o `.exe` em Releases.

Pra gerar manualmente numa máquina Windows (PyInstaller não faz
cross-compile a partir de Linux/macOS, então isso não roda daqui):

```
pyinstaller --onefile --noconsole --name deepfreezer_service ^
    --hidden-import win32timezone ^
    --hidden-import deepfreezer ^
    --paths . ^
    packaging\windows\deepfreezer_service.py
```

Rode a partir da raiz do repo (`--paths .`) -- senao o PyInstaller nao
acha `deepfreezer.py` (fica fora de `packaging\windows\`, importado via
`sys.path.insert` em tempo de execucao) e o `.exe` quebra com
`ModuleNotFoundError: No module named 'deepfreezer'` ao rodar. O
`--hidden-import win32timezone` evita um erro comum do PyInstaller
com pywin32. O `.exe` gerado (`dist\deepfreezer_service.exe`) substitui
`python.exe "...\deepfreezer_service.py"` nos comandos acima — tanto
`install` (modo pywin32) quanto `--foreground` (modo NSSM) funcionam
direto no executável.

## O que foi e o que não foi verificado

O **build** do `.exe` é real: o job `build-exe` do workflow roda num
runner Windows de verdade, instala pywin32 + PyInstaller e confirma
que o binário gerado existe e tem um tamanho plausível (não é só "o
comando não deu erro"). Isso valida que o código compila e empacota
no Windows — não que o serviço funciona como serviço.

O que **não** foi executado: registrar o serviço (pywin32 ou NSSM),
rodar o enforcement de verdade, aplicar `icacls`, ou qualquer
interação com o Gerenciador de Serviços/Task Manager — nada disso
acontece no job de build, e o sandbox usado pra desenvolver é Linux
sem Windows/pywin32/NSSM disponíveis pra testar isso localmente (a
lógica de enforcement compartilhada com o Linux — carregar config,
descartar overlay da sessão anterior, recongelar — foi validada
rodando em Linux, sem `icacls`, e falhou de forma controlada como
esperado). Antes de ir para produção, valide em uma VM Windows:

- Instalar por um dos dois caminhos acima e confirmar `Start-Service`
  (ou `nssm start`) sem erro.
- Reiniciar a máquina e confirmar no log
  (`C:\ProgramData\DeepFreezer\deepfreezer.log`) que o enforcement
  rodou no boot.
- Conferir a ACL do `.dfreezer` com `icacls` (só Administradores e
  SYSTEM) e tentar acessá-lo logado como usuário padrão (deve falhar).
- Tentar `Stop-Service DeepFreezer` como usuário sem privilégio de
  administrador (deve ser negado).

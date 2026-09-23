# STATUS_SERVICO.md — falha de inicialização do serviço no Windows 10

Registro de trabalho da investigação do **Evento 7009** (`Tempo limite
(30000 ms) atingido ao aguardar a conexão do serviço DeepFreezer`) no
`Start-Service DeepFreezer`.

- **Sintoma relatado:** `Start-Service DeepFreezer` falha; o Visualizador
  de Eventos mostra Evento 7009 no log System. Sem traceback do Python e
  sem nada em `C:\ProgramData\DeepFreezer\deepfreezer.log`.
- **Máquina afetada:** Windows 10 do usuário. **Não reproduz no CI**
  (`test-windows-service`, runner `windows-latest` / Windows Server 2022):
  lá o mesmo `.exe` instala, inicia, faz o enforcement e desinstala a cada
  build. Isso é o dado mais informativo que temos: a causa depende de algo
  do ambiente da máquina, não do binário.
- **Critérios de parada (do pedido):** `Get-Service -Name DeepFreezer`
  retornando `Running`; o serviço não sair sozinho depois dos 30 s; o
  `C:\ProgramData\DeepFreezer\config.json` lido sem erro de caminho com as
  credenciais da conta do serviço. Máximo de 5 ciclos de correção.
- **Fora de escopo, por instrução:** alertas DCOM (Evento 10016) são ruído
  do Windows e estão sendo ignorados. Nenhuma alteração de Registro
  (`regedit`) ou de política de grupo foi feita.

---

## Ciclo 1 — MessageBox modal no caminho do SCM

### 1. Diagnóstico interativo (logs e exceções rodando o `.exe` na mão)

**Pendente — precisa da máquina Windows 10.** Esta caixa não roda Windows,
então o ciclo 1 foi diagnosticado por leitura do código e do comportamento
do CI, não por execução. Os dois comandos que faltam rodar, num PowerShell
**como Administrador**, na pasta onde está o `.exe`:

```powershell
# 1) traceback real do serviço, em primeiro plano (modo 'debug' do pywin32:
#    roda SvcDoRun no processo atual, sem SCM, e imprime a exceção)
.\deepfreezer_service_windows-10-11.exe debug

# 2) o que o SCM registrou, imediatamente depois de tentar o start
Start-Service DeepFreezer
Get-Service DeepFreezer
Get-WinEvent -LogName System -MaxEvents 20 |
    Where-Object { $_.ProviderName -like '*Service Control*' } |
    Format-List TimeCreated, Id, Message
Get-Content C:\ProgramData\DeepFreezer\deepfreezer.log -Tail 40
```

Dado decisivo a colher: **o horário da primeira linha do
`deepfreezer.log`** comparado com o horário do Evento 7009. O código
corrigido loga `"iniciado sem argumentos ... despachando pro SCM"` como a
primeira coisa que faz, antes de qualquer chamada ao pywin32:

- linha aparece **no instante** do `Start-Service` e o 7009 vem 30 s
  depois → o processo subiu e travou **dentro** do handshake. É o cenário
  do ciclo 1.
- linha aparece **~30 s depois** do `Start-Service`, ou não aparece →
  o processo levou mais que a janela do SCM só para começar a rodar. É o
  cenário do ciclo 2 (extração do PyInstaller `--onefile`).

Enquanto esse timestamp não existir, os dois candidatos continuam abertos;
o ciclo 1 foi escolhido primeiro porque é um bug real e demonstrável no
código, e a correção é barata.

### 2. Estrutura do executável (serviço nativo vs. app de console)

**Verificado: é um serviço nativo e o handshake com o SCM está correto.**
A hipótese de "app de console que bloqueia a thread principal" foi
descartada por leitura de `packaging/windows/deepfreezer_service.py`:

- `class DeepFreezerService(win32serviceutil.ServiceFramework)` — a classe
  base certa do pywin32.
- o despacho é `servicemanager.Initialize()` →
  `PrepareToHostSingle(DeepFreezerService)` →
  `StartServiceCtrlDispatcher()`, que é o `StartServiceCtrlDispatcher()`
  da API do Windows, não um `while True`.
- `SvcDoRun()` chama `self.ReportServiceStatus(SERVICE_RUNNING)` **antes**
  do trabalho pesado (`enforce_all()`), e só depois fica parado em
  `WaitForSingleObject(stop_event, INFINITE)`. Ou seja: o SCM é avisado de
  que o serviço subiu antes de congelar pasta nenhuma, e o
  `enforce_all()` não pode causar 7009.

**Consequência prática: não é preciso NSSM nem WinSW, e não é preciso
reescrever a base para `ServiceBase`.** Trocar por um wrapper aqui
esconderia o bug em vez de corrigi-lo. (O modo NSSM continua existindo
como caminho alternativo — `--foreground` + `install_service_nssm.ps1` —
mas como escolha do administrador, não como conserto.)

### 3. Abordagem de correção — refatoração do código-fonte

**Causa raiz encontrada, no código anterior ao patch:**

```python
if len(sys.argv) == 1 and _running_interactively():
    _msgbox(...)   # MessageBoxW modal
    return 1
if len(sys.argv) == 1:
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(DeepFreezerService)
    servicemanager.StartServiceCtrlDispatcher()
```

`_running_interactively()` é só `bool(os.environ.get("SESSIONNAME"))`. A
premissa era que a sessão 0 (onde o SCM inicia serviços) nunca tem essa
variável — o que vale quando ela é uma variável **de usuário**, definida
pelo Terminal Services. Se `SESSIONNAME` existir como variável **de
sistema** na máquina, o processo do serviço a herda, o código entra no
primeiro `if`, e abre um `MessageBoxW` **modal na sessão 0**: uma janela
num desktop invisível, sem ninguém para clicar em OK. O processo bloqueia
para sempre, nunca chega ao `StartServiceCtrlDispatcher()`, e o SCM aborta
em 30 s. O resultado é exatamente o sintoma relatado: **Evento 7009, sem
traceback e sem log** — porque nada falhou, o processo só ficou esperando.

Isso também explica por que o CI passa: no runner a variável não está no
ambiente de sistema.

**Correção aplicada** (`packaging/windows/deepfreezer_service.py`, função
nova `_dispatch_or_explain()`):

1. **Despacha para o SCM primeiro e decide pelo resultado**, em vez de
   adivinhar o contexto antes. Nada que possa bloquear acontece no caminho
   do SCM.
2. O duplo clique passa a ser detectado pelo erro que o próprio dispatcher
   devolve — `winerror 1063`, *"the service process could not connect to
   the service controller"* — que é um teste confiável e que nunca
   bloqueia. Só nesse caso, e só se a sessão for interativa, a MessageBox
   aparece. Qualquer outro `winerror` é logado com `log.exception()` e
   re-lançado, em vez de virar silêncio.
3. `servicemanager.Initialize()` passou a ficar dentro de `try/except`:
   registrar a fonte de evento é opcional (é o mesmo cuidado que o resto
   do arquivo já tinha no `LogMsg`), e uma falha aí não pode mais impedir
   o despacho — senão volta a dar timeout sem explicação.
4. Uma linha de log é escrita **antes** de tudo, que é o timestamp pedido
   na seção 1.

**Regressão coberta por teste:**
`packaging/windows/test_deepfreezer_service.py`, 7 testes que rodam em
qualquer SO (os módulos do pywin32 são substituídos por dublês em
`sys.modules`, e o que se verifica é a ordem das chamadas). O teste
`test_sessionname_presente_nao_abre_caixa_no_caminho_do_scm` é o guarda
deste bug: com `SESSIONNAME` setada, o despacho tem que acontecer e
nenhuma caixa pode abrir. Suíte completa: **70 testes, todos passando**
(`python3 run_tests.py`).

### 4. Resultado do teste `Start-Service`

**Pendente — precisa da máquina Windows 10.** Nada aqui pode ser
preenchido de dentro desta caixa Linux: ela não tem SCM, não tem
Visualizador de Eventos e não tem `Get-Service`. O que precisa rodar, com
o `.exe` novo (build da branch, ou da próxima release):

```powershell
Stop-Service DeepFreezer -ErrorAction SilentlyContinue
.\install_service_exe.ps1                 # reinstala com o .exe novo
Start-Service DeepFreezer
Get-Service  DeepFreezer                  # criterio 1: Running
Start-Sleep -Seconds 45
Get-Service  DeepFreezer                  # criterio 2: ainda Running
Get-Content  C:\ProgramData\DeepFreezer\deepfreezer.log -Tail 40
```

> **Atenção ao critério 3 (config lido sem erro).** O instalador cria
> `C:\ProgramData\DeepFreezer\config.json` com `{"targets": []}` se ele
> não existir. Com `targets` vazio o serviço **sobe e fica `Running`**,
> mas grava um erro no log Application: `config sem 'targets'`. Isso é
> comportamento esperado, não a falha investigada aqui — mas conta como
> "novo erro no Visualizador de Eventos". Preencha `targets` **antes** do
> `Start-Service` para que o start saia limpo.

| Critério | Status |
| --- | --- |
| `Get-Service -Name DeepFreezer` = `Running` | a verificar |
| Continua `Running` passados os 30 s | a verificar |
| `config.json` lido pela conta do serviço (LocalSystem) sem erro de caminho | a verificar |
| Nenhum erro novo no Visualizador de Eventos | a verificar |

---

## Ciclo 2 — planejado, ainda não executado

Só entra em ação se o ciclo 1 não resolver **e** o timestamp da seção 1
mostrar que o processo demorou para começar.

**Candidato:** o `.exe` é gerado com PyInstaller `--onefile`. Nesse modo o
bootloader precisa extrair todo o conteúdo para uma pasta temporária antes
de a primeira linha de Python rodar. Numa máquina com disco lento ou com
antivírus inspecionando cada arquivo extraído, isso passa dos **30 s** que
o SCM concede — e o sintoma é, de novo, 7009 sem traceback.

**Mudança correspondente:** passar o build do serviço para `--onedir` em
`.github/workflows/build-packages.yml` (o `.exe` deixa de ser um arquivo
solto e passa a vir numa pasta com as DLLs ao lado; o instalador copia a
pasta inteira). Não há extração, então o processo começa a rodar
imediatamente.

**Não será feito:** aumentar `ServicesPipeTimeout` no Registro. Resolveria
o sintoma, mas é alteração de Registro — fora do escopo definido — e
mascara um start lento em vez de corrigi-lo.

## Histórico de ciclos

| Ciclo | Hipótese | Mudança | Resultado |
| --- | --- | --- | --- |
| 1 | MessageBox modal na sessão 0 bloqueia antes do handshake | `_dispatch_or_explain()`: despacha primeiro, detecta duplo clique pelo erro 1063 | Aguardando validação em Windows 10 |
| 2 | Extração do `--onefile` estoura a janela de 30 s do SCM | `--onedir` no build | Não executado |

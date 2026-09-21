# DeepFreezer no Windows

## Jeito mais simples: `install.bat`

Baixe o zip `deepfreezer-windows` (aba Actions do workflow
`build-packages`, ou Releases numa tag `vX.Y.Z`), extraia, e dê
**duplo clique em `install.bat`**. Ele pede elevação (UAC) sozinho e
instala o serviço `DeepFreezer` (conta `LocalSystem`) usando o
`deepfreezer_service.exe` já empacotado — não precisa de Python nem
de abrir PowerShell manualmente. `uninstall.bat` remove.

Isso existe porque as duas alternativas manuais abaixo têm ciladas
conhecidas do Windows: rodar `install_service_pywin32.ps1` direto
exige lembrar do prefixo `.\` (`install_service_pywin32.ps1` sozinho
dá "não é reconhecido como cmdlet...") *e* geralmente esbarra na
política de execução de script (bloqueada por padrão em várias
instalações); e dar duplo clique direto no `.exe` sem instalar antes
não faz nada útil (ele só age quando registrado como serviço). Os
`.bat` contornam os dois problemas: rodam com
`-ExecutionPolicy Bypass` só para essa chamada, sem mudar política
nenhuma no resto do sistema.

## Alternativas manuais (mesmo resultado, mais controle)

Ambas pedem PowerShell **elevado** (Administrador) e detectam
sozinhas se há um `deepfreezer_service.exe` do lado do script — se
houver (caso do zip baixado), usam ele direto; senão caem para
`python deepfreezer_service.py` (precisa de `pip install pywin32`
antes).

### 1. pywin32 (serviço nativo)

```
.\install_service_pywin32.ps1
.\install_service_pywin32.ps1 -Uninstall
```

Roda como serviço `DeepFreezer` (classe `win32serviceutil.ServiceFramework`
em `deepfreezer_service.py`), sob a conta `LocalSystem` (`NT AUTHORITY\SYSTEM`).

### 2. NSSM (sem pywin32 na máquina alvo)

Requer o utilitário [NSSM](https://nssm.cc) (`nssm.exe`) no PATH da máquina alvo.
O mesmo `deepfreezer_service.py`/`.exe` roda em modo `--foreground`
(só faz o enforcement e fica residente) e o NSSM cuida do ciclo de
vida do processo.

```
.\install_service_nssm.ps1 -PythonExe "C:\Python312\python.exe"
```

Em todos os casos, o serviço ao iniciar: para cada alvo do config
descarta o overlay da sessão anterior (thaw sem commit), recongela a
árvore e restringe a ACL do overlay (`icacls`) a Administradores e
SYSTEM — ver `harden_acl.ps1` para reaplicar isso manualmente.

## Empacotando com PyInstaller

**Já automatizado** em `.github/workflows/build-packages.yml` (job
`build-exe`, roda num runner `windows-latest` de verdade — é como
este `.exe` foi de fato buildado, já que este repositório foi
desenvolvido num sandbox Linux): dispare o workflow manualmente (aba
Actions → Run workflow) ou publique uma tag `vX.Y.Z` pra também
anexar o zip em Releases. O job monta um `deepfreezer-windows.zip`
com o `.exe` + os dois `.bat` + os `.ps1` + `config.example.json` +
este README — é esse zip que vira o artifact/release.

Pra gerar manualmente numa máquina Windows (PyInstaller não faz
cross-compile a partir de Linux/macOS, então isso não roda daqui):

```
pyinstaller --onefile --noconsole --name deepfreezer_service ^
    --hidden-import win32timezone ^
    packaging\windows\deepfreezer_service.py
```

O `--hidden-import win32timezone` evita um erro comum do PyInstaller
com pywin32.

## O que foi e o que não foi verificado

O job `build-exe` do CI, num runner Windows de verdade, agora faz uma
verificação de ponta a ponta, não só o build: confirma que o `.exe`
tem tamanho plausível, **instala o serviço de verdade
(`install_service_pywin32.ps1`), inicia com `Start-Service`, confirma
que ficou `Running`, confirma que o enforcement rodou de fato (overlay
`.dfreezer` criado a partir de um alvo real), confere a ACL com
`icacls`, para o serviço e desinstala** — tudo isso falha o build se
qualquer passo der errado. Ainda não cobre: reiniciar a máquina de
verdade (o job só inicia o serviço manualmente, não reproduz o boot),
`nssm`/o caminho NSSM, e o `install.bat`/UAC em si (o runner do CI já
roda elevado, então o "pedir elevação sozinho" não é exercido ali).

Antes de ir para produção, valide numa máquina Windows de verdade (não
CI): `install.bat` de fato sobe o prompt de UAC como esperado;
reiniciar a máquina e confirmar no log
(`C:\ProgramData\DeepFreezer\deepfreezer.log`) que o enforcement rodou
no boot; tentar acessar o `.dfreezer` logado como usuário padrão (deve
falhar); tentar `Stop-Service DeepFreezer` sem privilégio de
administrador (deve ser negado).

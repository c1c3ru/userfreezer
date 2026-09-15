# DeepFreezer no Windows

Duas formas de registrar o servico — escolha uma:

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
    packaging\windows\deepfreezer_service.py
```

O `--hidden-import win32timezone` evita um erro comum do PyInstaller
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

# userfreezer (DeepFreezer)

Deep Freeze multiplataforma (Windows/Linux) a nível de aplicação:
congela uma árvore de diretórios, desvia todas as mudanças para uma
camada de overlay (journal append-only, crash-safe) e restaura o
estado original a qualquer momento — no próximo boot ou por comando
do administrador.

- **Core** (`deepfreezer.py`): 100% biblioteca padrão do Python,
  compatível com 3.6+. Nenhum módulo de kernel, nenhum driver, nenhuma
  dependência externa.
- **Serviço/daemon** (`packaging/`): encapsula o core como serviço de
  sistema (systemd no Linux, Windows Service no Windows) para rodar no
  boot, ficar fora do controle do usuário comum e reforçar o ciclo
  "muda na sessão, volta ao congelado no próximo boot".
- **Bandeja do sistema** (`ui/`): ícone azul/laranja (congelado/
  descongelado), painel de status e alternância de estado atrás de
  senha de admin. Única parte com dependência externa (`pystray` +
  `Pillow`), já que não existe API de bandeja na stdlib.

## Pacotes prontos (.deb / .exe / ferramental Windows)

O workflow `.github/workflows/build-packages.yml` builda os pacotes a
cada execução e, numa tag `vX.Y.Z`, publica todos em
[Releases](https://github.com/c1c3ru/userfreezer/releases):

- **Linux — `deepfreezer_<versão>_all.deb`**: instala o core +
  daemon em `/opt/deepfreezer`, o `config.json` em `/etc/deepfreezer`
  (`chmod 700`) e a unit do systemd, já com as permissões da Tarefa 2
  aplicadas pelo próprio `postinst`.
  ```
  sudo dpkg -i deepfreezer_0.1.0_all.deb
  sudo systemctl start deepfreezer      # revise /etc/deepfreezer/config.json antes
  sudo apt remove deepfreezer           # remove (preserva config)
  sudo apt purge deepfreezer            # remove tudo
  ```
  Testado de ponta a ponta (install → rodar o daemon → remove →
  purge, com `dpkg` de verdade) tanto neste repositório quanto no
  próprio runner de CI — ver `packaging/linux/build_deb.sh` pra gerar
  localmente.

- **Windows — `deepfreezer_service.exe`**: binário único gerado por
  PyInstaller a partir de `packaging/windows/deepfreezer_service.py`
  num runner `windows-latest` real, com Python 3.11 — **não roda no
  Windows 7** (Python 3.9+ não é mais compatível com ele). Isso é a
  proteção *application-level* do core — ver "Limite honesto" mais
  abaixo pro que ela não cobre.

- **Windows 7 — `deepfreezer_service_win7.exe`**: o mesmo binário,
  compilado à parte com Python 3.8 (a última versão compatível com
  Windows 7). Não foi validado numa máquina Windows 7 real — se ainda
  assim não iniciar, o próximo suspeito é o bootloader do PyInstaller.

- **Windows — `deepfreezer-windows-service-scripts.zip`**:
  `install_service_exe.ps1` (instala o serviço a partir do `.exe`
  baixado, sem precisar de Python na máquina) + `install.bat`/
  `uninstall.bat` (clique duas vezes, pedem elevação sozinhos, chamam
  o `.ps1` acima) + `install_service_pywin32.ps1` /
  `install_service_nssm.ps1` (a partir do código-fonte) +
  `harden_acl.ps1`. O caminho `.exe` + `install_service_exe.ps1` é
  **testado de verdade** no CI (`test-windows-service`: instala,
  inicia, confirma que o enforcement rodou e desinstala, num runner
  Windows real) antes de publicar; os outros caminhos e o prompt de
  UAC do `.bat` continuam sem validar numa máquina real — ver
  `packaging/windows/README.md` pra qual usar e o que falta.

- **Windows — `deepfreezer-windows-os-level.zip`**: `os_detect.py`
  (detecta versão/edição do Windows) + os scripts em
  `packaging/windows/os_level/` que orquestram a proteção a nível de
  SO (UWF, EWF/FBWF, disco diferencial VHDX — qualquer gravação,
  não só as feitas pela API do core). Nenhum desses scripts foi
  validado numa máquina Windows real — ver o status detalhado em
  `packaging/windows/README.md` antes de usar em produção.

Como baixar agora: abra a página de
[Releases](https://github.com/c1c3ru/userfreezer/releases) e pegue a
versão mais recente, ou, sem esperar uma tag, o
[run mais recente](https://github.com/c1c3ru/userfreezer/actions/workflows/build-packages.yml)
na aba Actions pros artifacts `deepfreezer-deb` / `deepfreezer-exe` /
`deepfreezer-exe-win7` / `deepfreezer-windows-service-scripts` /
`deepfreezer-windows-os-level` (esses expiram em ~90 dias; os de
Releases são permanentes).

## Core: uso via CLI

```
python3 deepfreezer.py freeze /caminho/app --verify   # congela (hash opcional)
python3 deepfreezer.py list   /caminho/app [sub/dir]
python3 deepfreezer.py cat    /caminho/app arq
python3 deepfreezer.py write  /caminho/app arq  dados_ou_-|ou_arquivo_fonte
python3 deepfreezer.py rm     /caminho/app arq_ou_dir
python3 deepfreezer.py diff   /caminho/app
python3 deepfreezer.py status /caminho/app
python3 deepfreezer.py thaw   /caminho/app            # volta ao congelado (descarta)
python3 deepfreezer.py thaw   /caminho/app --commit    # aplica as mudanças no alvo
```

## Core: uso como biblioteca

```python
from deepfreezer import DeepFreezer

with DeepFreezer(r"C:\app") as df:   # ou "/opt/app"
    df.freeze()                      # DeepFreezer(..., verify=True) registra sha256
    df.write("config.ini", b"k=v\n")
    dados = df.read("config.ini")
    df.remove("logs/")               # pasta inteira some da view
    df.thaw(commit=False)            # "desligar": volta ao estado congelado
```

**Limite honesto:** o freezer é *application-level* — protege a árvore
contra mudanças feitas por quem passa pela API/CLI. Um `sed -i`
externo direto no arquivo ainda mexe no disco de verdade. Congelar o
SO inteiro (qualquer processo) exige abordagem de kernel: `overlayfs`
no boot (Linux) ou VHDX diferencial sobre a base do `C:\` (Windows) —
fora do escopo deste core; ver observações no final deste arquivo.

## Serviço de sistema (`packaging/`)

Roda o core como serviço a nível de SO: no start (tipicamente no
boot), para cada diretório configurado descarta o overlay da sessão
anterior (thaw sem commit) e recongela — todo o resto é o mesmo core
acima, chamado pelo administrador via CLI quando quiser algo diferente
do ciclo automático (ex.: `thaw --commit` para aplicar mudanças
permanentemente antes do próximo boot).

Configuração (`packaging/config.example.json`, copiado durante a
instalação):

```json
{
  "targets": [
    {"target": "/opt/lab-app", "overlay": null, "verify": false}
  ]
}
```

### Linux (systemd)

Instalação a partir do repo (equivalente ao `.deb` da seção acima,
útil pra rodar direto de uma checkout sem gerar o pacote):

```
sudo packaging/linux/install.sh      # instala + habilita o serviço
sudo systemctl start deepfreezer     # primeira ativação (revise o config antes)
sudo systemctl status deepfreezer
sudo systemctl stop deepfreezer      # exige sudo/root
sudo packaging/linux/uninstall.sh    # remove (preserva config; use --purge p/ apagar tudo)
```

O overlay (`<alvo>.dfreezer`) fica com permissão `700`/dono `root`
depois de cada `freeze` do daemon. Detalhes em
`packaging/linux/deepfreezer.service` e `packaging/linux/deepfreezerd.py`.

### Windows (`install.bat`, ou pywin32/NSSM/Windows 7 manual)

Jeito simples: baixe `deepfreezer_service.exe` (ou
`deepfreezer_service_win7.exe` no Windows 7 — ver seção de pacotes
acima) e `deepfreezer-windows-service-scripts.zip`, extraia tudo numa
mesma pasta e dê duplo clique em `install.bat` (pede elevação sozinho,
sem precisar de PowerShell manual). Ver `packaging/windows/README.md`
pro passo a passo completo, os caminhos manuais
(`install_service_exe.ps1` / `install_service_pywin32.ps1` /
`install_service_nssm.ps1`), o hardening de ACL do overlay
(`harden_acl.ps1`) e o que o CI já valida de verdade vs. o que só dá
pra confirmar numa máquina Windows real.

## Bandeja do sistema (`ui/`)

Ícone na área de notificação — cadeado azul (congelado) ou laranja
(descongelado) — com painel de status e alternância de estado atrás
de senha de admin (hash PBKDF2-HMAC-SHA256 + salt, nunca texto plano):

```
pip install pystray Pillow                                    # única dependência externa do projeto
python3 ui/set_admin_password.py --config /etc/deepfreezer/config.json
python3 ui/tray_app.py --config /etc/deepfreezer/config.json
```

Detalhes, dependências (Tkinter pode exigir `python3-tk` no Linux) e o
que ficou pendente de validação numa sessão gráfica real em
`ui/README.md`.

## Receitas de arquitetura: congelamento de SO completo (nível de kernel)

Fora do escopo implementado aqui, documentado para referência caso a
necessidade evolua para travar o sistema operacional inteiro (e não
só a árvore gerenciada pela API):

- **Linux (OverlayFS no boot):** montar a raiz real como somente-leitura
  (`lowerdir`), usar um `tmpfs`/`ramfs` como `upperdir`+`workdir`, e
  montar `overlay` unificando ambos como nova raiz durante o
  `initramfs`. Qualquer mudança cai na RAM e é vaporizada ao desligar.
- **Windows (VHDX diferencial):** SO base em `Base.vhdx`, disco
  `Diferencial.vhdx` apontando para a base, BCD configurado para dar
  boot no diferencial (Native VHD Boot). Thaw = apagar o
  `Diferencial.vhdx` e criar um novo vazio no próximo boot.

Essas duas abordagens não usam nada deste repositório — são
configuração de boot/kernel do próprio SO.

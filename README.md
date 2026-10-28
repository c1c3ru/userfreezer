# userfreezer (DeepFreezer)

Deep Freeze multiplataforma (Windows/Linux) a nível de aplicação:
congela uma árvore de diretórios, desvia todas as mudanças para uma
camada de overlay (journal append-only, crash-safe) e restaura o
estado original a qualquer momento — no próximo boot ou por comando
do administrador.

- **Core** (`deepfreezer.py`): 100% biblioteca padrão do Python,
  compatível com Python 3.8+. Nenhum módulo de kernel, nenhum driver, nenhuma
  dependência externa.
- **Serviço/daemon** (`packaging/`): encapsula o core como serviço de
  sistema (systemd no Linux, Windows Service no Windows) para rodar no
  boot, ficar fora do controle do usuário comum e reforçar o ciclo
  "muda na sessão, volta ao congelado no próximo boot".
- **Bandeja e painel administrativo** (`ui/`): status de todos os alvos,
  alterações pendentes e comandos via IPC autorizado pelo serviço.
  A interface não lê configuração protegida nem modifica o núcleo
  diretamente. A elevação administrativa é solicitada ao SO (UAC/polkit)
  e validada pelo servidor. A bandeja usa `pystray` e `Pillow`.

> **Nota de versão:** a publicação v0.1.9 contém, por engano,
> um pacote Debian 0.1.8. Utilize **v0.1.12** ou posterior.
> O Windows 7 ainda requer testes manuais de binário e UAC;
> Windows 7 comum **não** tem UWF e não deve executar o provisionador VHDX
> do projeto. O congelamento do núcleo é **application-level**, não
> proteção integral contra modificações externas.

> **Acompanhamento da v0.2.0:** [estado central e próximos passos](docs/STATUS_CONSOLIDACAO_V020.md).
> Os recursos experimentais só serão chamados de concluídos após os
> critérios de aceite e evidências de VM, especialmente Windows 7 SP1.

## Pacotes prontos (.deb / .exe / ferramental Windows)

O workflow `.github/workflows/build-packages.yml` builda os pacotes a
cada execução e, numa tag `vX.Y.Z`, publica todos em
[Releases](https://github.com/c1c3ru/userfreezer/releases):

- **Linux — `deepfreezer_<versão>_all.deb`**: instala o core +
  daemon em `/opt/deepfreezer`, o `config.json` em `/etc/deepfreezer`
  (`chmod 700`) e a unit do systemd, já com as permissões da Tarefa 2
  aplicadas pelo próprio `postinst`.
  ```
  sudo dpkg -i deepfreezer_0.1.12_all.deb
  sudo systemctl start deepfreezer      # revise /etc/deepfreezer/config.json antes
  sudo apt remove deepfreezer           # remove (preserva config)
  sudo apt purge deepfreezer            # remove tudo
  ```
  Testado de ponta a ponta (install → rodar o daemon → remove →
  purge, com `dpkg` de verdade) tanto neste repositório quanto no
  próprio runner de CI — ver `packaging/linux/build_deb.sh` pra gerar
  localmente.

- **Windows — dois `.exe`, um por família de sistema.** O nome do
  arquivo já diz para qual Windows ele serve:

  | Seu sistema | Baixe |
  | --- | --- |
  | Windows 11 | `deepfreezer_service_windows-10-11.exe` |
  | Windows 10 | `deepfreezer_service_windows-10-11.exe` |
  | Windows 8 / 8.1 | `deepfreezer_service_windows-7-8.exe` |
  | Windows 7 | `deepfreezer_service_windows-7-8.exe` |

  São o mesmo programa, gerado por PyInstaller a partir de
  `packaging/windows/deepfreezer_service.py` num runner
  `windows-latest` real. O de 10/11 é compilado com Python 3.11 e
  **não roda no Windows 7**, porque o Python deixou de suportar esse
  sistema a partir da versão 3.9; o de 7/8 é compilado à parte com
  Python 3.8, a última versão compatível. Em Windows 8.1 os dois
  tendem a funcionar, e a tabela manda o de 7/8 por ser o mais
  conservador. **Não é preciso renomear nada**: o instalador aceita os
  dois nomes e, se os dois estiverem na pasta, escolhe sozinho o certo
  para o Windows em que está rodando.

  Isso é a proteção *application-level* do core — ver "Limite honesto"
  mais abaixo pro que ela não cobre. O `.exe` de Windows 7/8 nunca foi
  executado numa máquina Windows 7 de verdade; se não iniciar, o
  próximo suspeito é o bootloader do PyInstaller, não o Python.

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

## Testes

A suíte roda em qualquer SO, sem dependência externa:

```
python3 run_tests.py        # tudo; -v pra listar caso a caso
```

O `run_tests.py` procura todo arquivo `test_*.py` do repositório e roda
o `unittest discover` em cada pasta que tiver um — um teste novo não
precisa ser registrado em lugar nenhum, basta o nome do arquivo seguir
`test_*.py`.

O workflow `.github/workflows/tests.yml` roda essa mesma suíte (mais um
`compileall` de todos os `.py`) a cada push na `main` e em todo pull
request pra `main`, em Linux e Windows, com Python 3.8 (piso, o do alvo
Windows 7) e 3.12. É só verificação: quem publica pacote continua sendo
o `build-packages.yml`, nas tags `vX.Y.Z`.

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
python3 deepfreezer.py thaw   /caminho/app --commit    # Linux: aplica mudancas; Windows: bloqueado por seguranca (#63)
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

**Proteção opcional do kernel no Linux:** o script
`packaging/linux/overlayfs_session.py` pode montar um OverlayFS em
diretórios autorizados com alterações desviadas para tmpfs. **Não é
habilitado automaticamente, não protege a raiz do SO** e deve ser
validado em VM antes do uso. Veja `docs/LINUX_OVERLAYFS_VM.md`.

**Segurança no Windows desde v0.1.12:** `thaw --commit` com
alterações pendentes **é bloqueado por padrão** porque o teste
cross-process do [PR #84](https://github.com/c1c3ru/userfreezer/pull/84)
comprovou renomeação de ancestral apesar dos handles Win32.
O bloqueio falha antes de modificar o disco e preserva o overlay;
`thaw` sem `--commit` continua descartando alterações.
O commit Windows só poderá voltar após um backend seguro e os
testes da [#63](https://github.com/c1c3ru/userfreezer/issues/63).

**Limite honesto:** o freezer é *application-level* — protege a árvore
contra mudanças feitas por quem passa pela API/CLI. Um `sed -i`
externo direto no arquivo ainda mexe no disco de verdade. Congelar o
SO inteiro (qualquer processo) exige abordagem de kernel/filtro:
OverlayFS no boot (Linux), UWF em edições Windows compatíveis,
EWF/FBWF em determinadas imagens Windows 7 Embedded ou uma estratégia
de boot diferencial validada. O provisionador VHDX existente **não
suporta Windows 7 comum**. Ver `docs/OS_LEVEL_VALIDATION.md`.

## Serviço de sistema (`packaging/`)

Roda o core como serviço a nível de SO: no start (tipicamente no
boot), para cada diretório configurado descarta o overlay da sessão
anterior (thaw sem commit) e recongela — todo o resto é o mesmo core
acima, chamado pelo administrador via CLI quando quiser algo diferente
do ciclo automático (no Linux, ex.: `thaw --commit` para aplicar mudanças
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

Jeito simples: baixe o `.exe` da sua versão do Windows
(`deepfreezer_service_windows-10-11.exe` ou
`deepfreezer_service_windows-7-8.exe` — ver a tabela na seção de
pacotes acima) e `deepfreezer-windows-service-scripts.zip`, extraia
tudo numa mesma pasta e dê duplo clique em `install.bat` (pede elevação
sozinho, sem precisar de PowerShell manual). Ver `packaging/windows/README.md`
pro passo a passo completo, os caminhos manuais
(`install_service_exe.ps1` / `install_service_pywin32.ps1` /
`install_service_nssm.ps1`), o hardening de ACL do overlay
(`harden_acl.ps1`) e o que o CI já valida de verdade vs. o que só dá
pra confirmar numa máquina Windows real.

## Painel e bandeja autenticados (`ui/`)

A interface é um **cliente sem privilégios**. O daemon faz a autorização
via `SO_PEERCRED` (Linux) ou token do cliente do Named Pipe (Windows).
Para operações administrativas, a UI solicita elevação ao sistema
operacional via polkit/`pkexec` ou UAC. As operações destrutivas
exigem confirmação explícita e nonce temporário de uso único.

```sh
pip install pystray Pillow  # apenas para ícone na bandeja; Tkinter no painel
python3 ui/tray_app.py
python3 ui/health_panel.py
python3 admin_client.py status
```

O daemon Linux é um serviço residente que oferece o IPC local. O
serviço Windows também oferece Named Pipe; sem ele, ações administrativas
não têm fallback local. O painel requer Python + Tkinter e (no Windows)
pywin32, e precisa ser testado em sessão gráfica real antes de produção.
Detalhes em `ui/README.md` e `docs/WIN7_MANUAL_TEST.md`.

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

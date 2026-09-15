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

### Windows (Serviço via pywin32 ou NSSM)

Ver `packaging/windows/README.md` — inclui os dois caminhos de
instalação (`install_service_pywin32.ps1` / `install_service_nssm.ps1`),
o hardening de ACL do overlay (`harden_acl.ps1`) e as notas de
empacotamento com PyInstaller. **Escrito e revisado, mas não executado
em Windows real** — validar numa VM antes de produção (checklist no
próprio README do diretório).

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

# DeepFreezer — bandeja do sistema (Tarefa 3)

Ícone na área de notificação: cadeado **azul** (congelado) ou
**laranja** (descongelado), painel de status e alternância de estado
protegidos por senha de admin.

Única parte do projeto com dependências externas — o core
(`deepfreezer.py`) e o daemon (`packaging/`) são só stdlib, mas não
existe API stdlib para ícone de bandeja:

```
pip install pystray Pillow
```

Os diálogos (senha, status, confirmação) usam **Tkinter**, que é
stdlib mas em algumas distros Linux vem separado do interpretador
(`sudo apt install python3-tk` / `dnf install python3-tkinter`). No
Windows, os instaladores oficiais do python.org já incluem Tk.

## Configurar a senha de admin

Usa o mesmo `config.json` do daemon (`packaging/config.example.json`).
A senha nunca é gravada em texto plano — só o hash PBKDF2-HMAC-SHA256
(200 000 iterações) e o salt, nas chaves `admin_password_hash` /
`admin_password_salt`:

```
python3 ui/set_admin_password.py --config /etc/deepfreezer/config.json
```

## Rodar a bandeja

```
python3 ui/tray_app.py --config /etc/deepfreezer/config.json
```

Sem `--target`, usa o primeiro alvo listado no config. Menu:

- **Status...** — data do congelamento, arquivos monitorados e uso de
  disco do overlay (saem de `DeepFreezer.status()` do core).
- **Congelar** / **Descongelar...** — alterna o estado; descongelar
  pergunta se é pra aplicar as mudanças da sessão (commit) ou
  descartá-las e voltar ao estado congelado.
- **Sair** — fecha só o ícone da bandeja (não mexe no estado congelado
  nem no serviço de boot).

Qualquer uma dessas ações pede a senha de admin antes de continuar.

## Autostart (sessão do usuário logado)

O ícone de bandeja roda na sessão gráfica do usuário, não como
`root`/`SYSTEM` (isso é papel do serviço de boot em `packaging/`).
Duas formas comuns de iniciar automaticamente ao logar:

- **Linux**: unit de usuário do systemd (`~/.config/systemd/user/`)
  ou entrada em `~/.config/autostart/*.desktop`.
- **Windows**: atalho na pasta Inicializar (`shell:startup`) ou uma
  tarefa agendada "ao fazer logon" pelo Agendador de Tarefas.

Não incluído aqui como script pronto — depende de como o admin já
distribui software nos laboratórios (GPO, Ansible, imagem de disco
etc.), e forçar um caminho específico seria além do que a Tarefa 3
pediu.

## O que não foi verificado aqui

O sandbox usado para escrever isto é Linux headless: sem servidor X
(`pystray` já falha no `import`, antes mesmo de abrir um ícone) e sem
Tkinter disponível para este interpretador. O que **foi** validado de
verdade, sem GUI:

- `admin_auth.py` (hash/verificação de senha, salts distintos por
  chamada, senha ausente/incorreta/correta) — testado diretamente.
- `icons.py` (Pillow): ícones 64×64 RGBA gerados, cor predominante
  azul/laranja conferida por pixel, exportação PNG funcionando.
- **Toda a lógica de `tray_app.py`** (`_require_password`,
  `_toggle` nos três ramos — commit / descarte / cancelar —,
  `_build_menu`, `_status_text`, troca de ícone) — exercida com
  stubs de `tkinter`/`pystray` no lugar dos módulos reais, chamando
  o `DeepFreezer` de verdade por trás. Todos os cenários passaram:
  bloqueio sem senha configurada, senha errada, senha certa, cancelar
  diálogo, congelar/descongelar de verdade com o congelamento
  refletindo no ícone e no texto de status.

O que **não** dá pra confirmar sem uma máquina com desktop real:
renderização do ícone na bandeja de verdade (Windows/GNOME/KDE/etc.),
aparência dos diálogos do Tk, e comportamento do `pystray` em cada
backend (AppIndicator/GTK no Linux, win32 no Windows). Antes de
distribuir: instalar as dependências, rodar `tray_app.py` numa sessão
gráfica normal, e conferir visualmente o ícone e os diálogos nos dois
SOs.

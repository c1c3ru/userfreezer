# DeepFreezer — painel de administração via IPC local

A interface de bandeja e o painel **não importam o núcleo DeepFreezer**
nem têm acesso direto ao `config.json` protegido. As solicitações passam
pelo serviço local, que verifica as credenciais do SISTEMA OPERACIONAL.

## Requisitos

- Python 3.8+ e Tkinter (Linux: `python3-tk`); para bandeja,
  `pip install pystray Pillow`.
- Windows: `pip install pywin32` para o cliente Named Pipe, inclusive
  quando o daemon/serviço está empacotado em EXE.
- Serviço residente com IPC ativo:
  - Linux: `deepfreezer.service` executa `deepfreezerd.py --serve`
    e disponibiliza `/run/deepfreezer/admin.sock`.
  - Windows 7/10/11: serviço DeepFreezer expõe o Named Pipe local
    `\\.\pipe\DeepFreezerAdmin`.

O socket Linux usa `SO_PEERCRED`; no Windows o serviço usa ACL no
Named Pipe e impersonation do token recebido. Nenhuma senha local da
interface ou hash/salt do `config.json` é enviada pelo cliente.

## Consulta (sem acesso root/Administrators)

```bash
python admin_client.py status
python ui/health_panel.py
python ui/tray_app.py
```

O painel lista todos os alvos configurados, inclusive os que usam
`overlay` personalizado, e diferencia **resultado do último enforcement**
de **estado atual do overlay**. `healthy` é apenas *application-level*,
**não significa proteção contra gravação externa ao DeepFreezer**.

## Operações administrativas

A interface inicia sem privilégio e pode mostrar status; usuários comuns
não conseguem executar `freeze`, `discard` ou `commit`.
O broker **autoriza cada ação** pelo SO:

- Linux: UID 0. Para testes de linha de comando, usar `sudo python3
  admin_client.py freeze --target /alvo` ou configurar uma estratégia
  de elevação autorizada fora da interface.
- Windows: token elevado pertencente a Administrators. O usuário deve
  iniciar o cliente com **Executar como administrador**. O serviço
  jamais confia apenas na confirmação da interface.
- Em `discard` e `commit`, a UI pede confirmação escrita e recebe
  do serviço um nonce de **uso único**, válido por 30 segundos e
  vinculado ao peer, alvo e operação. Não reutilizar o token.

**A interface não eleva privilégios automaticamente.** Em ambiente
com usuários comuns, o administrador deve aprovar via procedimento
controlado pelo sistema operacional. Até integração com um agente
de elevação/UAC/polkit, ações de usuários sem token apropriado são
negadas com erro explícito.

## Testes manuais

1. Abrir o painel como usuário comum: status deve aparecer, operações
   administrativas devem ser NEGADAS.
2. Rodar como administrador/root: congelar um alvo de teste, consultar
   estado, descartar; repetir com overlay personalizado.
3. Confirmar que `commit` pede a palavra digitada e backend emite
   token temporário. Tentar repetir um token já usado: negar.
4. Parar serviço: painel deve indicar indisponibilidade sem executar
   operações locais como fallback.
5. Em Windows 7 SP1, validar Python 3.8, atualização KB2533623,
   pywin32 e conexão no Named Pipe; registrar logs de execução.
6. Validar Tk/pystray numa sessão gráfica real Windows e Linux.

Os testes automáticos de protocolo e peer credentials não substituem
os testes de ACL e usabilidade em sessão real. Consulte
`docs/IPC_SECURITY_DESIGN.md` e a issue #53.

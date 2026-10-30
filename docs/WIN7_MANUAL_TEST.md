# Roteiro de validação manual do Win7 e de proteção OS-level

**Atualização para testes v0.2.0:** usar a prévia `v0.2.0-rc.1` (quando
publicada e com hashes conferidos) conforme [roteiro humano da RC](V020_HUMAN_TEST_PLAN.md).
A referência anterior v0.1.13 abaixo é histórica; **não** atribuir à RC
resultados de um binário v0.1.13. A comprovação do Win7 real permanece pendente.

> **Binários válidos para validar:** [v0.1.13](https://github.com/c1c3ru/userfreezer/releases/tag/v0.1.13). A v0.1.9 tem Debian com versão interna 0.1.8 e não deve ser utilizada como prova de integridade da release. Registre o SHA-256 local do EXE Win7 e compare com `SHA256SUMS` da release antes de executar. Os testes só são considerados concluídos com logs e evidências anexadas pelo mantenedor.

**Aplicável ao código da branch que contém as issues #49/#54.**
Não execute scripts que modificam boot ou partições em máquina de produção.
Sem logs e evidências externas, as issues #49/#54 **não podem ser declaradas concluídas**.

> **Bloqueio de commit Windows (#63):** `thaw(commit=True)` com operações
> pendentes agora retorna erro antes de modificar o alvo, pois o teste
> concorrente #84 demonstrou que o handle Win32 nao bloqueia toda troca
> de ancestral. O descarte funciona; nao tente reativar o commit
> com patch local. Registre o resultado esperado como "BLOQUEADO".

**Novo roteiro específico da issue #63:** [encerramento real, evidência pós-reboot e revisão administrativa de checkpoints NT](WIN7_NT_COMMIT_CRASH_RECOVERY.md). O probe exige checkout exato que contém o teste; a release v0.1.13 não inclui este incremento. O fluxo de commit de produção continua bloqueado.

## 1. Preparação comum (antes de modificar qualquer filtro)

1. Crie VM descartável **com imagem licenciada**, snapshot e mídia de recuperação.
2. Documente SO, edition, build, arquitetura, modo UEFI/BIOS, uso de NTFS,
   sistema de arquivos e estado do boot. Faça cópia verificável do estado inicial.
3. Em Windows 7 SP1, confirme atualização KB2533623 antes de testar o
   executável Python 3.8; caso contrário, a inicialização pode falhar.
4. Rode, como Administrador:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\inspect_protection.ps1
   python.exe ..\os_detect.py
   ```

5. **Windows 7 comum**: `os_detect.py` deve retornar `unsupported`;
   VHDX deste projeto não é compatível. Teste o serviço application-level,
   mas **não anuncie proteção integral da unidade**.
6. **Windows Embedded Standard 7 / POSReady**: confirme que EWF/FBWF
   está presente *nesta imagem* e seu status antes de configurar.
7. **Windows 10/11 Enterprise/Education/IoT Enterprise**: confirmar
   UWF instalado e a edição compatível.
8. Separe uma unidade **persistente e não protegida** (`E:\evidencias`
   num segundo disco virtual) ou exclusão do filtro previamente confirmada.
   Não use a mesma unidade sem `-EvidenceIsExcluded`.

## 2. Fluxo de filtro e teste real de escrita externa

Após snapshot e habilitação do filtro apropriado (UWF/EWF/FBWF),
**reinicie** e confirme que o status do filtro está *ativo*, e não só
*pending*. Tenha um diretório `C:\DF-Probe` criado **antes de habilitar**
a proteção para que sua existência seja parte da base protegida.

No PowerShell elevado, depois de bootar com o filtro realmente ativo:

```powershell
.\inspect_protection.ps1
.\vm_probe.ps1 -Prepare -ProbeRoot "C:\DF-Probe" -EvidenceDir "E:\evidencias"
```

**Teste simultâneo da exclusão (recomendado para UWF/EWF/FBWF):**
crie antes do filtro um diretório `C:\DF-Excluido` e registre-o como
exclusão real no mecanismo de proteção. Com o filtro ativo, use:

```powershell
.\vm_probe.ps1 -Prepare -ProbeRoot "C:\DF-Probe" -ExcludedRoot "C:\DF-Excluido" -EvidenceDir "E:\evidencias"
```

O script cria uma sentinela dentro do diretório excluído no mesmo volume.
Depois do reboot, o resultado será PASS somente se a escrita comum
desaparecer **e** a sentinela excluída persistir. Se o diretório
excluído não estiver realmente excluído, o teste marcará
`FAIL_exclusao_nao_persistiu`. A ferramenta não configura o filtro.

**Reinicie a VM manualmente**. Na sessão seguinte:

```powershell
.\inspect_protection.ps1
.\vm_probe.ps1 -VerifyAfterReboot -EvidenceDir "E:\evidencias"
```

O teste dá sucesso somente se `deepfreezer-external-probe-<GUID>.txt`
criado pelo PowerShell comum tiver DESAPARECIDO da unidade protegida.
Se persistir, o teste falha: não declare proteção OS-level.

Em separado, crie uma segunda sentinela numa exclusão persistente
configurada, reinicie e confirme que ela **permanece**. EWF de volume não
oferece exclusões equivalentes a FBWF/UWF; para esse caso documente
restrições em vez de simular exclusão.

## 3. Casos negativos e recuperação

- Tentar operação com volume errado: o script deve falhar sem sucesso.
- Testar `Disable`, reiniciar e confirmar estado efetivamente desativado.
- Testar falta de espaço do overlay só em VM isolada, com monitoramento
  e ponto de recuperação previamente funcional.
- Simular interrupção do ciclo e recuperar snapshot externo.
- Testar proteção de conta sem privilégios e log de comandos nativos.
- **VHDX**: não executar `vhdx_diff_setup.ps1` em Windows 7 nem em
  disco de produção. Provisionar imagem moderna apenas em VM separada e
  comprovar rollback de BCD/partições com mídia externa. O script só
  cobre parte do processo de provisionamento e não implementa reset
  automatizado seguro.

## 4. Matriz de resultados (preencher com evidências reais)

| VM/edição | Estratégia | Estado ativo pós-reboot | Arquivo externo sumiu | Exclusão permaneceu | Disable e recovery | Logs |
| --- | --- | --- | --- | --- | --- | --- |
| Windows 7 SP1 Professional | unsupported | N/A | N/A | N/A | N/A | pendente |
| Windows Embedded Standard 7 | EWF/FBWF se instalado | pendente | pendente | pendente | pendente | pendente |
| Windows 10 Enterprise | UWF | pendente | pendente | pendente | pendente | pendente |
| Windows 11 Enterprise | UWF | pendente | pendente | pendente | pendente | pendente |
| Windows 10 Pro | VHDX experimental | pendente | pendente | N/A | pendente | pendente |

Anexe ao GitHub issue #54 o `deepfreezer-probe-record.txt` e
`deepfreezer-probe-result.txt`, stdout da inspeção e resumo da VM.
Remova/anonimize nomes de pessoas, serial do disco ou dados sensíveis.

**ATENÇÃO:** o CI que roda em `windows-latest` não comprova
suporte ao Windows 7 nem substitui o ensaio do filtro na VM.

## 5. Validação manual da release v0.1.13 em Windows 7 SP1

**Responsável:** mantenedor. Não afirmar sucesso do Windows 7 até anexar
logs e resultados completos à issue. Use Windows 7 SP1 em VM licenciada,
com snapshot ANTES da instalação; preferir um disco virtual independente.

### Binário, serviço e controle por UAC

1. Baixe os artefatos da release v0.1.13, nunca o .deb incorreto
   da v0.1.9. Verifique hashes contra SHA256SUMS publicado.
2. Use deepfreezer_service_windows-7-8.exe e
   deepfreezer-windows-service-scripts.zip no mesmo diretório. Instale
   como Administrador usando install_service_exe.ps1 ou install.bat.
3. Configure dois alvos de teste isolados no
   C:\ProgramData\DeepFreezer\config.json, um com overlay padrão e
   outro com overlay personalizado fora da árvore protegida.
   Inicie serviço e confira Get-Service DeepFreezer e status.json.
   Running não implica enforcement saudável: o JSON deve registrar
   healthy para cada alvo.
4. O serviço deve criar o Named Pipe local DeepFreezerAdmin. Execute
   o EXE instalado em Program Files com --admin-cli status;
   a saída pode ser silenciosa por ser --noconsole, mas o
   código de saída precisa ser zero.
5. Para a UI, instale Python 3.8 + Tkinter e pywin32 compatíveis
   com Win7; use python ui/health_panel.py e python ui/tray_app.py.
   Para bandeja, instalar pystray e Pillow também compatíveis.
   Nunca relaxar ACL de config.json, pipe ou do serviço.
6. Abra o painel como usuário comum: a lista de alvos e o overlay
   personalizado devem aparecer. Tente mutação: UAC deve pedir
   aprovação administrativa. Recuse o prompt e verifique que nada
   mudou no disco.
7. Autorize UAC somente em alvo descartável. Faça freeze, escreva
   uma alteração via API, escolha Descartar e confirme baseline
   intacto. Teste Aplicar/commit separadamente e confirme que o
   sistema **recusa o commit no Windows**, com journal preservado e
   alvo inalterado (bloqueio de segurança da #63).
8. Confirme que nonce expira e não é reutilizado; SID diferente
   não pode executar ação. Cliente de pipe sem elevação recebe
   acesso negado para operações administrativas.
9. Interrompa o cliente, reinicie o serviço, confira saúde e estado
   do overlay; não interpretar erro no meio como rollback automático.
10. Guarde evidências: build, hash do EXE, logs, screenshot do painel,
    UAC negado/aprovado, estado do JSON, ações autorizadas e negadas.

**Windows 7 comum:** este teste comprova apenas application-level.
Não habilite VHDX do projeto nem anuncie proteção de gravações
externas. Em Windows 7 Embedded, o roteiro EWF/FBWF exige filtro
realmente presente na imagem licenciada.

### Registro para anexar às issues

| Caso | Esperado | Resultado |
| --- | --- | --- |
| EXE Win7 SP1 | Serviço e IPC iniciam | PENDENTE |
| Named Pipe e ACL | Usuário comum não executa mutações | PENDENTE |
| UAC negado | Alvo intacto | PENDENTE |
| UAC aprovado | Freeze/descarte autorizados | PENDENTE |
| Commit Windows | Bloqueado; journal preservado | PENDENTE |
| Overlay personalizado | Listado e operável | PENDENTE |
| Crash/erro no descarte | Erro ou recuperação coerente | PENDENTE |
| Reutilização do nonce | Negada | PENDENTE |
| Tk/pystray | Usável no desktop Win7 | PENDENTE |

## Checklist de entrega de resultados pelo mantenedor

Após os ensaios, anexe em cada issue correspondente:

- **#53/#56:** screenshot do painel, resultado dos comandos autorizados e negados, conta utilizada (usuário comum ou admin, sem dados pessoais), teste de UAC e confirmação dos ACLs de Named Pipe.
- **#63:** resultado da tentativa concorrente de troca de junction, falhas de permissão, caminhos UNC e log do commit; registre o comportamento observado sem declarar inexistência absoluta de TOCTOU.
- **#49/#54:** edição real do Windows 7 (comum/Embedded), ferramenta EWF/FBWF efetivamente instalada, estado do filtro antes e depois de reboot, gravação externa e rollback comprovados. Em Windows 7 comum, resultado OS-level do projeto deve permanecer **unsupported**.
- **#55:** nome e hash do EXE/ZIP/.deb baixados da release v0.1.13, sucesso ou falha de instalação/desinstalação e logs sem segredos.

Se o teste não puder ser realizado, anote **não executado** em vez de marcar sucesso. Todos os registros devem referenciar o mesmo SHA do build e a versão do sistema.

## Prova obrigatoria de nova inicializacao (issue #54)

A partir do teste de regressao #54, `vm_probe.ps1 -Prepare` registra o
horario UTC e o `Win32_OperatingSystem.LastBootUpTime` persistentes. O
comando `-VerifyAfterReboot` consulta o boot atual por WMI e **falha**
com `state=FAIL_sem_reboot` se o SO nao tiver reiniciado depois
do preparo, mesmo que o arquivo de prova tenha sido apagado.
Isso impede um falso positivo trivial, mas nao comprova sozinho que um
filtro esta ativo: guardar tambem o output de `inspect_protection.ps1`
antes/depois, a sentinela persistente da exclusao e o snapshot da VM.

# Roteiro de validação manual do Win7 e de proteção OS-level

**Aplicável ao código da branch que contém as issues #49/#54.**
Não execute scripts que modificam boot ou partições em máquina de produção.
Sem logs e evidências externas, as issues #49/#54 **não podem ser declaradas concluídas**.

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

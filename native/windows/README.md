# UserFreezer — protótipo nativo de observação de E/S em Windows

**Ciclo 31/10/2026 · Issues [#49](https://github.com/c1c3ru/userfreezer/issues/49) e [#54](https://github.com/c1c3ru/userfreezer/issues/54)**

**Estado:** código-fonte inicial de minifiltro de sistema de arquivos **somente auditoria**. Não representa um minifiltro compilado/testado e **não oferece proteção ou restauração de arquivos**. A proteção transparentemente equivalente ao Deep Freeze permanece ausente no Windows.

## 1. Arquitetura e limites

```text
Explorer, processos externos e aplicativos
          │  operações normais do Windows
          ▼
Windows Filter Manager (FltMgr)
          │
          ├── UserFreezerAudit (protótipo C)
          │     observa IRP_MJ_CREATE/WRITE/SET_INFORMATION
          │     apenas em volume NTFS explicitamente autorizado
          │     retorna FLT_PREOP_SUCCESS_NO_CALLBACK
          │     NÃO modifica bytes, offsets, status nem destinos
          ▼
Sistema de arquivos NTFS → disco real
```

O **futuro** produto requer uma camada diferente: captura e redirecionamento copy-on-write consistente, leituras vendo dados do overlay, baseline imutável, metadados/rename/delete, paging I/O/memory mapped files, integridade em crash, semântica de flush, suporte a boot crítico, restauração após reboot, exclusões e manutenção. O código deste ciclo **não implementa** nenhum desses recursos.

### Código desta entrega

- `native/windows/uf_audit_minifilter.c`: DriverEntry com `FltRegisterFilter` / `FltStartFiltering`, callbacks de preoperação que **sempre deixam a operação prosseguir**. Contadores globais e mensagens limitadas de depuração (sem dados, paths ou chaves), e unload com `FltUnregisterFilter`.
- O driver **falha ao iniciar** sem `Parameters\\LabAuditEnabled` REG_DWORD exatamente 1 **e** `Parameters\\LabVolumeNtName` REG_SZ de volume nativo NTFS com nome `\\Device\\HarddiskVolume<N>`. O `InstanceSetup` consulta o nome real pelo FltMgr e recusa todos os volumes que não correspondem **exatamente**; não aceita letras de unidade, shadow copies, compartilhamentos ou volume não NTFS.
- `native/windows/audit_probe.py`: consulta `fltmc.exe filters` sem alteração. Quando vê o filtro listado, reporta apenas `observer-listed-not-protection`. **Não declara I/O interceptada, proteção ativa, reboot ou rollback**.
- `test_native_minifilter_audit.py`: testes de contratos estáticos e de parsing, com cenários negativos e simulações; não compila nem carrega driver em runner.

O código fica **fora do build oficial do serviço Windows** e do ZIP distribuído. Nenhum INF, catálogo de assinatura, altitude ou instalador foi inserido. Isso é proposital: uma altitude exclusiva é atribuída pela Microsoft, e não podemos inventar/usar altitude de terceiros. A instalação de minifiltro no Windows também requer empacotamento, assinatura e revisão do driver.

## 2. Gate de build em laboratório

Antes de tentar carregar um .sys, é necessário um trabalho adicional:

1. Criar um projeto *File System Minifilter* no Visual Studio + WDK apropriado com `uf_audit_minifilter.c` e `FltMgr.lib`.
2. Configurar **uma altitude oficialmente atribuída**, INF adequado para a versão de destino, modo de início **manual/demand** e assinatura válida ou configuração de assinatura de teste permitida na VM isolada. Não usar drivers unsigned, desabilitar verificação de assinatura em equipamento físico, nem ativar auto start no boot de produção.
3. Compilar **x86 e x64** com WDK compatível. Para Windows 7 SP1 escolher toolchain que suporte o alvo Windows 7; para Windows 10/11 usar toolchain atual suportada. NENHUMA compatibilidade Win7 é presumida só por compilar x86.
4. Em VM descartável, identificar volume de testes **dedicado, secundário e sem dados reais**, confirmar `\\Device\\HarddiskVolumeN` via ferramenta nativa confiável, configurar os dois valores explícitos acima e revisar sua correspondência. Não usar a unidade C: no primeiro ensaio.
5. Carga e attach manuais somente após gates, instrumentando no WinDbg, preservando snapshots da VM e saída do kernel debugger; comparar os contadores antes/depois de gravações **por processo externo**; colher evidência de um fluxo real, não apenas o nome listado por fltmc.
6. Descarregar o filtro e confirmar que não há instâncias restantes, falhas, bugchecks ou alteração no conteúdo do volume.

**Este PR não inclui comandos de instalação, criação de serviço, modificação do registro nem driver executável.** O compilador WDK e as VMs não estão disponíveis no ambiente de CI, portanto o código-fonte C continua **não compilado / não executado**.

### Consulta somente leitura depois da instalação aprovada em VM

```powershell
python native/windows/audit_probe.py
fltmc.exe filters
```

`fltmc filters` prova somente presença do registro do filtro. Uma prova real de callbacks precisará de log de kernel/observação independente, identidade da VM, volume e evento externo correlacionado.

## 3. Matriz inicial de compatibilidade (objetivo, não aceite)

| Plataforma | Estágio | Gate de avanço |
| --- | --- | --- |
| Win7 SP1 x86 | Código C sem build | WDK/INF/assinatura, VM e callbacks reais |
| Win7 SP1 x64 | Código C sem build | Assinatura, VM, filter manager e callbacks |
| Windows 10 x64 | Código C sem build | Build WDK e callback externo em VM |
| Windows 11 x64 | Código C sem build | Build WDK e callback externo em VM |

Nenhum teste foi realizado em máquina física. Mesmo com callback externo confirmado, **o Desktop continuará não protegido** até existir backend de overlay e rollback efetivos.

## 4. Evolução de engenharia de loop

A primeira validação alvo será: carregar somente em volume de laboratório, observar alteração de arquivo por Explorer e Powershell, provar que a operação efetivamente atravessou o FltMgr, descarregar sem impacto e documentar falhas. Depois implementar contratos independentes de volume/base/overlay, testes de leitura após escrita, rename/delete, flush/mapped I/O, falhas por falta de espaço, reboot, recuperação, exclusões e proteção do volume de boot. Somente após gates completos integrar ao serviço e considerar distribuição.

Não fechar [#49](https://github.com/c1c3ru/userfreezer/issues/49), [#54](https://github.com/c1c3ru/userfreezer/issues/54) ou a release estável v0.2.0 com esta entrega. O objetivo funcional permanece **proteção transparente para Windows 7/10/11** e não apenas API-level.

## Referências

- [Microsoft: registrar preoperações](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/registering-preoperation-and-postoperation-callback-routines)
- [Microsoft: retornar FLT_PREOP_SUCCESS_NO_CALLBACK](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/returning-flt-preop-success-no-callback)
- [Microsoft: atribuição de altitude](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/load-order-groups-and-altitudes-for-minifilter-drivers)
- [Microsoft: INF para minifiltro](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/creating-an-inf-file-for-a-minifilter-driver)
- [Microsoft: WDK para versões anteriores](https://learn.microsoft.com/en-us/windows-hardware/drivers/other-wdk-downloads)

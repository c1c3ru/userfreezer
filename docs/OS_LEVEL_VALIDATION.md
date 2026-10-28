# Proteção OS-level — validação e aceitação para Windows 7+

Issues: [#49](https://github.com/c1c3ru/userfreezer/issues/49) e
[#54](https://github.com/c1c3ru/userfreezer/issues/54).

**Status: NÃO VALIDADO.** O core `deepfreezer.py` é *application-level*: somente
operações feitas pela API passam pelo overlay. Uma escrita externa real não é
interceptada. O estado `healthy` do serviço significa apenas que o último
ciclo de enforcement por alvo concluiu com sucesso.

## Matriz de suporte e estratégias

| Plataforma | Estratégia | Situação |
| --- | --- | --- |
| Windows 11/10 Enterprise, Education, IoT Enterprise quando presente | UWF | Ferramenta de configuração presente no repositório; depende de edição/feature e reboot; não validada no SO real |
| Windows 7 Embedded com EWF/FBWF instalado | EWF/FBWF | Avaliar somente em imagem Embedded licenciada; nunca presumir suporte no Windows 7 comum |
| Windows 7 Professional/Home | VHD/VHDX diferenciado conforme capacidades do boot e versão | Experimental, **não usar o script de particionamento em produção**; provisionamento/boot/recovery ainda sem validação |
| Windows 10/11 Home/Pro | Disco diferencial e BCD | Experimental e de alto risco; reset demanda ambiente externo |
| Linux | OverlayFS via initramfs | Arquitetura proposta; não implementada pelo daemon application-level |

**Nunca instalar em disco real sem snapshot/backup externo e teste de recuperação.**

## Validação inicial não destrutiva

O script `packaging/windows/os_level/inspect_protection.ps1` usa PowerShell 2.0
e consultas read-only a WMI, UWF/EWF/FBWF quando presentes e BCD (enum).
Ele registra os resultados brutos; **não confere proteção ativa nem executa
rollback**. Guardar o output em artefato de teste (sem dados sensíveis).

Nenhum processo de teste pode chamar `diskpart clean`, criar BCD ou
habilitar filtro em estação de usuário. As provas de boot devem ocorrer em
VM descartável com checkpoint anterior.

## Plano de ensaio em VM

1. Preparar imagens licenciadas para Windows 7 SP1 Embedded e 7 Pro
   separadamente; Windows 10/11 Enterprise e Home/Pro; UEFi/BIOS quando
   cabível; capturar identificação da edição e versão da ferramenta.
2. Antes de qualquer mudança, snapshot externo e teste de recuperação.
3. Executar apenas a inspeção read-only; documentar capacidades reais
   de cada edição, volume protegido, exclusões e status pendente/ativo.
4. Instalar/configurar UWF ou EWF/FBWF somente onde disponível, seguindo
   documentação do fornecedor e script revisado. Registrar códigos de saída.
5. Reiniciar VM; criar arquivo **externamente à API**, comparar estado
   do SO após novo boot, confirmar exclusões persistentes e volume restaurado.
6. Testar mudança de configuração, queda forçada, falta de espaço em overlay,
   restauração por modo de manutenção e atualização de SO.
7. Desabilitar e reiniciar; comprovar retorno a boot normal e integridade
   do disco. Anexar logs, hashes, screenshots e passo a passo reproduzível.
8. Somente depois avaliar disco diferencial em VM descartável e WinPE,
   com validação explícita da recuperação do BCD e das partições.

## Evidências necessárias para marcar #49 e #54 como concluídas

- [ ] Matriz Windows 7 Embedded x comum (sem prometer UWF no Win7).
- [ ] Resultado verificável de escrita externa descartada após reboot.
- [ ] Exclusões persistidas e comandos de manutenção idempotentes.
- [ ] Rollback de boot testado de ponta a ponta.
- [ ] Códigos de retorno nativos inspecionados; erro nunca significa sucesso.
- [ ] Telemetria diferencia `unsupported`, `configured`,
      `pending-reboot`, `active` e `failed` com base no SO real.
- [ ] Versão `v0.1.10` de binários Win7 executada em VM SP1 antes de declarar suporte.

O CI corrente em Windows moderno/Python 3.8 não substitui VM Windows 7.


### Compatibilidade crítica: Windows 7 e boot de VHDX

O **Windows 7 comum não recebe estratégia OS-level automaticamente**.
O recurso nativo de boot a partir de VHD do Windows 7 é distinto do
boot VHDX usado pelo provisionador atual e tinha restrições de edição
(Enterprise/Ultimate). Portanto, `os_detect.py` retorna `unsupported`
para Windows 7 não Embedded; não executar `vhdx_diff_setup.ps1` para
instalar Windows 7. O Windows Embedded 7 só pode usar EWF/FBWF se os
filtros estiverem presentes na imagem licenciada e forem comprovados
por teste real.

Fontes: [Microsoft — native VHD boot no Windows 7](https://devblogs.microsoft.com/cesardelatorre/windows-7-natively-booting-from-a-vhd-file-virtual-pc-image/),
[Microsoft — UWF Windows 10/11](https://learn.microsoft.com/en-us/windows/configuration/unified-write-filter/).

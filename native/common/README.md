# Contrato CoW nativo em C — modelo de memória, não driver

**31/10/2026 · [Issue #49](https://github.com/c1c3ru/userfreezer/issues/49)**

O código-fonte native/common/uf_cow_core.h e native/common/uf_cow_core.c implementa uma referência de comportamento copy-on-write de setores em **memória RAM de teste**. O minifiltro Windows nativo de auditoria em native/windows/uf_audit_minifilter.c **não utiliza esse modelo** e continua pass-through.

## Invariantes implementados

- Baseline representado como buffer somente leitura fornecido pelo chamador, sem gravação no baseline.
- Overlay e bitmap de setores alocados externamente, totalmente separados do baseline.
- Primeira gravação em um setor copia os bytes originais para o overlay; gravações seguintes modificam somente o overlay.
- Leitura mescla setores ainda originais e setores modificados.
- Uma escrita que excederia o limite de setores sujos é rejeitada **antes de realizar qualquer modificação** na chamada.
- Validação de bounds, alias, estado interno, potência de dois para tamanho de setor e offsets inválidos.
- Descarte explícito zera o overlay e o bitmap, de forma que leituras voltem ao baseline.

## Restrições fundamentais

**NÃO é proteção funcional do sistema operacional, filtro de disco, driver, filesystem, redirecionamento de gravações de aplicativos, rollback após reboot ou virtualização de boot.** O overlay tem o tamanho total do baseline para facilitar a revisão, não é armazenamento eficiente. A biblioteca não possui sincronização concorrente, journaling durável, recovery, exclusão de setores, rename, ACL, persistência, mapeamento de arquivo, paging I/O ou suporte a NTFS real.

Essas limitações impedem qualquer promessa de equivalência com o Deep Freeze neste estágio.

## Testes reais do modelo C

O harness native/common/test_uf_cow_core.c exercita cópia inicial, leitura após escrita, invariância do baseline, escrita atravessando setores, rejeição atômica de capacidade, offsets fora dos limites, tamanhos inválidos, alias e descarte. O teste test_native_cow_core.py compila o C **quando há compilador disponível** e executa o binário de testes, sem driver, WDK, arquivos externos ou alterações no sistema.

Comandos Linux de laboratório:

    cc -std=c99 -Wall -Wextra -Werror -O1 -o /tmp/uf_cow_test native/common/uf_cow_core.c native/common/test_uf_cow_core.c
    /tmp/uf_cow_test
    python run_tests.py -v

No Windows o teste só compila se algum compilador C estiver no PATH; sem compilador retorna skip explícito. Não confundir a execução desse harness com validação de compatibilidade do kernel.

## Próximos gates prioritários

1. Compilar o minifiltro observador com WDK apropriado para Windows 7 SP1 e versões atuais. Obter altitude atribuída, empacotamento INF/assinatura, instalação manual em volume secundário da VM, logs de callbacks independentes de Explorer e descarregamento. Nada disso está comprovado.
2. Definir mapeamento de arquivo, volume, cache, rename/delete, EOF, metadados NTFS, hardlinks, ACL, paginação/memory-mapped I/O e isolação por processo/volume.
3. Projetar um overlay com persistência e recuperação após falhas, sem recursão de operações FltMgr, com proteção da base e limites de capacidade.
4. Validar em VMs Windows 7 SP1 x86/x64, Windows 10 e Windows 11, inclusive escrita externa e descarte após reboot; somente então conectar ao UserFreezer e construir instalação offline.

Referências: [minifiltro SwapBuffers Microsoft](https://github.com/microsoft/Windows-driver-samples/tree/main/filesys/miniFilter/swapBuffers) e [WDK para versões anteriores](https://learn.microsoft.com/en-us/windows-hardware/drivers/other-wdk-downloads).

**Issues #49/#54 abertas; release estável 0.2.0 bloqueada.**

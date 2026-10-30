# UserFreezer v0.2.0-rc.1 — roteiro de teste humano

> **Pré-lançamento, não certificado.** Uso somente em VMs descartáveis
> com snapshot, backup e mídia de recuperação. O `thaw --commit` com
> operações pendentes no Windows permanece BLOQUEADO por segurança.
> O serviço continua application-level sem filtro de kernel universal.
> A v0.2.0 final não está aprovada.

## Baixar os artefatos da prévia

- Página de pré-lançamento (após sucesso do job GitHub Actions):
  https://github.com/c1c3ru/userfreezer/releases/tag/v0.2.0-rc.1
- Arquivos esperados na mesma release:
  - `deepfreezer_service_windows-7-8.exe` (build Python 3.8: teste em Windows 7 SP1/8/8.1)
  - `deepfreezer_service_windows-10-11.exe` (Windows 10/11)
  - `deepfreezer-windows-service-scripts.zip` (install.bat, uninstall.bat e scripts)
  - `deepfreezer-windows-os-level.zip` (ferramentas/inspeções de VM, NÃO para instalação em disco real)
  - `deepfreezer_0.2.0~rc1_all.deb` (Linux; pacote candidato anterior a 0.2.0 estável)
  - `SHA256SUMS` e `release.spdx.json`

Se a página de prévia não existir ou algum arquivo estiver ausente, NÃO
substitua pelos artefatos antigos nem declare a versão disponível. Confirme
que o job de publicação do GitHub Actions está marcado como success.

## Verificação antes da instalação

Registre o commit associado à release e preserve um snapshot da VM.
Confirme as somas SHA-256 usando `SHA256SUMS`:

Windows 7 (PowerShell 2.0, prompt CMD):

    certutil -hashfile deepfreezer_service_windows-7-8.exe SHA256
    certutil -hashfile deepfreezer-windows-service-scripts.zip SHA256

Windows 10/11 (PowerShell):

    Get-FileHash .\deepfreezer_service_windows-10-11.exe -Algorithm SHA256

Linux:

    sha256sum -c SHA256SUMS

O arquivo `SHA256SUMS` cobre os cinco pacotes principais. Mantenha
o resultado, a versão/edição do SO, arquitetura, build e hash do commit
no relatório da VM (omita dados pessoais e tokens).

## Windows 7 SP1 — validação real #56 e #63

1. Usar VM licenciada Windows 7 SP1, snapshot inicial, disco secundário
   persistente e, quando aplicável, KB2533623.
2. Baixar `deepfreezer_service_windows-7-8.exe` e descompactar o zip
   de scripts de serviço na mesma pasta. Confirmar hashes antes de executar.
3. Instalar somente como administrador no laboratório, com o script
   `install.bat` ou `install_service_exe.ps1`; verificar SCM, ACL,
   logs, estado IPC e configuração de dois alvos descartáveis.
4. Para o painel Tk e a bandeja, usar Python 3.8/Tkinter/pywin32 com
   dependências apropriadas ao Win7 e seguir
   `docs/WIN7_MANUAL_TEST.md`. O EXE fornecido é principalmente serviço,
   não um instalador gráfico completo.
5. Testar conta sem privilégios: status deve respeitar ACL/IPC;
   mutação negada no UAC não pode alterar alvo. Com aprovação, testar
   freeze e descarte via API mantendo baseline.
6. Tentar `thaw(commit=True)` com mutações pendentes no Windows de
   laboratório; **o comportamento esperado é RECUSA, preservando
   journal e alvo**. NÃO aplicar patches locais para remover o bloqueio.
7. Executar ensaio #63 `prepare → reboot manual → verify` pelo
   checkout *exato* associado à RC, conforme
   `docs/WIN7_NT_COMMIT_CRASH_RECOVERY.md`.
8. Capturar screenshot (com informações sensíveis mascaradas),
   código de saída, logs, hashes, registros do serviço e evidência do boot.

O protótipo de commit NT checkpointado permanece experimental: não
executar esse backend em diretórios de trabalho reais.

## Windows OS-level #54 e Linux #49

Windows 7 comum: NÃO testar UWF ou VHDX do projeto como se suportados.
UWF é ensaiado em VM Windows Enterprise compatível; EWF/FBWF apenas em
imagens Windows Embedded licenciadas com filtros realmente presentes;
VHDX/WinPE somente nas edições aplicáveis. Seguir
`docs/OS_LEVEL_VALIDATION.md` e `docs/WIN7_MANUAL_TEST.md` com snapshot
e recuperação independente. Não configurar BCD/discos físicos em produção.

No Linux, instalar o .deb apenas em VM descartável:

    sudo dpkg -i 'deepfreezer_0.2.0~rc1_all.deb'

O serviço application-level não habilita o OverlayFS automaticamente.
Para teste do kernel por diretório, seguir
`docs/LINUX_OVERLAYFS_VM.md`, exigindo mountpoint real, disco secundário
persistente, sentinela externa e novo boot_id após reboot. Não anunciar
proteção de rootfs; não habilitar unit opt-in fora da VM.

## Como registrar o resultado humano

Criar um comentário em cada issue com status PASS/FAIL/UNTESTED e anexar
somente evidências desidentificadas, incluindo SO, versão/edição, SHA-256
dos binários, build e commit, IDs de boot, logs relevantes, screenshots e
resultado do snapshot/rollback:

- #63: https://github.com/c1c3ru/userfreezer/issues/63
- #49: https://github.com/c1c3ru/userfreezer/issues/49
- #54: https://github.com/c1c3ru/userfreezer/issues/54
- #56: https://github.com/c1c3ru/userfreezer/issues/56

O simples download, instalação ou CI verde não encerram a issue.
O manifesto `docs/V020_RELEASE_ACCEPTANCE.json` permanece em
`pending` e protege a publicação **estável** da v0.2.0 até o aceite
técnico e revisão humana independente.

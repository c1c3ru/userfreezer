# Linux — modo OS-level opcional para diretorios (OverlayFS)

O nucleo do DeepFreezer e application-level. Esta ferramenta ADICIONAL
monta o OverlayFS do kernel sobre um unico diretorio; assim, gravacoes
feitas por qualquer processo nesse diretorio sao redirecionadas para
upperdir em tmpfs, e desaparecem apos reinicializacao do SO.

**LIMITACAO:** isso NAO congela o SO inteiro. O script nao substitui
initramfs/OverlayFS da raiz e nao protege diretorios fora da montagem.
A ativacao e explicita e NAO e feita pelo instalador nem pelo servico
application-level. Sem teste real de reboot em VM nao declarar validacao.

## Areas permitidas e seguranca

- Suporta somente diretorios existentes sob /srv, /opt, /mnt, /media e
  /tmp, exceto /opt/deepfreezer. Bloqueia symlinks de ancestrais,
  caminhos com delimitadores de options e alvos ja montados.
- Exige UID root, limite tmpfs 16 a 4096 MiB e flag
  --i-accept-volatile-protection. Sem a flag, nao modifica mounts.
- Monta tmpfs em /run/deepfreezer-overlayfs/<hash>/upper e work;
  usa mount -t overlay no target, mantendo baseline inferior intacto.
- Durante o uso, dados escritos no overlay consomem RAM. Pode acabar
  a memoria e falhar em E/S: monitorar uso e testar com cuidado.
- A desativacao normal deve ser feita durante shutdown/reboot da VM,
  nao com desmontagens forcadas em processos que usam o diretorio.

## Teste reproduzivel em VM Linux descartavel

Prepare snapshot, backup e um diretorio de exemplo vazio:

    sudo mkdir -p /srv/deepfreezer-vm-test
    sudo python3 /opt/deepfreezer/overlayfs_session.py --target /srv/deepfreezer-vm-test --enable --dry-run

Apos revisar o plano, habilite apenas no ambiente isolado:

    sudo python3 /opt/deepfreezer/overlayfs_session.py --target /srv/deepfreezer-vm-test --enable --size-mb 128 --i-accept-volatile-protection
    findmnt --mountpoint /srv/deepfreezer-vm-test
    echo "escrita externa" | sudo tee /srv/deepfreezer-vm-test/sentinela.txt

Reinicie a VM. A montagem NAO e recriada automaticamente por este
script. Apos reboot, o arquivo de prova deve ter desaparecido, enquanto
os arquivos baseline anteriores permanecem. Para usar em boot de forma
automatica e segura, uma unit dedicada deve ser validada em VM antes
de habilitar em estacoes. O daemon application-level pode coexistir,
mas NAO deve usar o mesmo target montado sem plano de integracao.

## Aceite pendente para #49

- Testar escritas com processo externo (sem API), inclusive rename e delete.
- Comprovar descarte apos reboot em kernel/filesystem alvo; comparar baseline.
- Comprovar que dados excluidos da montagem persistem conforme politica.
- Testar sem root, diretorio symlink, falta de espaco e erro de mount.
- Decidir estrategia separada para congelar raiz inteira via initramfs.
- Testar conflitos de servicos e documentar desinstalacao/rollback.

O teste da unidade de kernel nao roda no GitHub Actions: CI executa
somente verificacoes unitarias e mock de comandos mount.

### Estados sem falso positivo

A consulta `--status` devolve `active` apenas se o Linux informar uma
montagem `overlay` nesse ponto. Um diretório normal que apenas existe
agora é `inactive`, e não `configured`; um alvo inexistente é `error`.
Mesmo `active` não comprova reinicialização, descarte de dados ou
persistência de exclusões: esses testes continuam obrigatórios na VM.

## Ensaio automatizado adicional de kernel (sem reboot)

O workflow `.github/workflows/tests.yml` inclui o job
`linux-kernel-overlayfs`, executando
`packaging/linux/test_overlayfs_kernel_ci.sh` em runner Linux isolado.
Este ensaio monta o OverlayFS real **somente** num diretório efêmero em
`/srv/deepfreezer-ci-oslevel-*`, escreve nele por `tee` (fora da API),
desmonta a camada de kernel e comprova que o arquivo externo desapareceu
e o baseline ficou intacto. O cleanup verifica caminhos e tenta desmontar
ambas as montagens mesmo em caso de falha.

**Importante:** descarte após `umount` não prova recuperação após
reinicialização, ativação no boot, exclusões persistentes nem rollback
do sistema operacional. Esses itens continuam sob a #49 e #54.


## Unidade systemd opcional de boot (EXPERIMENTAL, em VM)

O pacote instala `deepfreezer-overlayfs@.service` **sem habilitar**.
A ativação exige ação explícita do administrador e montagem por diretório
dentro da allowlist, nunca na raiz `/`. O serviço recusa alvos que
coincidam ou se sobreponham aos do `/etc/deepfreezer/config.json`
application-level. Com erro de configuração falha antes da montagem.

```bash
TARGET=/srv/deepfreezer-vm-test
INSTANCE=$(systemd-escape --path "$TARGET")
sudo systemctl enable "deepfreezer-overlayfs@${INSTANCE}.service"
# Na VM descartavel, reinicie e confirme o mount verdadeiro:
sudo systemctl status "deepfreezer-overlayfs@${INSTANCE}.service"
findmnt --mountpoint "$TARGET"
```

A unidade roda **depois de local-fs.target, antes de multi-user.target**,
não no initramfs. Portanto ela não impede gravações anteriores ao
início da unidade, nem protege o restante da raiz. Desabilitar com
`systemctl disable` impede novos boots, mas não desmonta o overlay
desta sessão; **não confunda stop/disable com desmontagem**. Para encerrar
com segurança, volte a uma VM de manutenção e reinicie. Não habilitar
em produção até validar reboot, exclusões, rollback e conflito de ordem
de serviços. A #49 permanece aberta.

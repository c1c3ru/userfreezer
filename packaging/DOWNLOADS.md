## Qual arquivo baixar

| Seu sistema | Baixe |
| --- | --- |
| Windows 11 | `deepfreezer_service_windows-10-11.exe` |
| Windows 10 | `deepfreezer_service_windows-10-11.exe` |
| Windows 8 / 8.1 | `deepfreezer_service_windows-7-8.exe` |
| Windows 7 | `deepfreezer_service_windows-7-8.exe` |
| Linux (Debian/Ubuntu) | `deepfreezer_<versão>_all.deb` |

Nos dois casos de Windows, baixe também
`deepfreezer-windows-service-scripts.zip`, extraia na **mesma pasta** do
`.exe` e dê duplo clique em `install.bat`. Não é preciso renomear nada: o
instalador reconhece os dois nomes e, se os dois estiverem na pasta,
escolhe sozinho o certo para a versão do Windows em que está rodando.

Por que dois `.exe`: o de Windows 10/11 é compilado com Python 3.11 e
**não inicia no Windows 7**, porque o Python deixou de suportar esse
sistema a partir da versão 3.9. O de Windows 7/8 é o mesmo programa
compilado com Python 3.8, a última versão compatível. Em Windows 8.1 os
dois tendem a funcionar; a tabela manda o 7/8 por ser o mais
conservador.

O `deepfreezer-windows-os-level.zip` é separado e opcional: são os
scripts de proteção a nível de sistema operacional (UWF, EWF/FBWF, disco
diferencial VHDX), não o serviço.

**Validação:** o caminho de Windows 10/11 (`.exe` +
`install_service_exe.ps1`) é testado a cada build num runner Windows
real — instala, inicia, confirma o congelamento e desinstala. O `.exe` de
Windows 7/8 é compilado e conferido no CI, mas **nunca foi executado numa
máquina Windows 7 de verdade**; se ele não iniciar, o suspeito é o
bootloader do PyInstaller, não o Python.

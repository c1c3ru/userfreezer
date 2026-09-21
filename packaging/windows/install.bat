@echo off
setlocal

:: Instala o DeepFreezer como servico Windows (conta LocalSystem) a
:: partir do deepfreezer_service.exe desta mesma pasta -- nao precisa
:: de Python instalado. So' precisa clicar duas vezes: pede elevacao
:: (UAC) sozinho e roda o instalador sem precisar abrir PowerShell
:: manualmente nem lidar com politica de execucao de script.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Pedindo elevacao de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_service_exe.ps1"

echo.
echo Pressione qualquer tecla para fechar...
pause >nul

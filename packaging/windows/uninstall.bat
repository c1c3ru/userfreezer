@echo off
setlocal

:: Remove o servico DeepFreezer instalado por install.bat. Preserva a
:: config em C:\ProgramData\DeepFreezer.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Pedindo elevacao de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_service_pywin32.ps1" -Uninstall

echo.
echo Pressione qualquer tecla para fechar...
pause >nul

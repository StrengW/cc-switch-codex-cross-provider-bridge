@echo off
setlocal
set "UNINSTALLER=%LOCALAPPDATA%\CodexProviderBridge\app\UninstallCodexBridge.ps1"
if exist "%UNINSTALLER%" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%UNINSTALLER%"
  exit /b %ERRORLEVEL%
)
set "FALLBACK=%~dp0scripts\windows\UninstallCodexBridge.ps1"
if exist "%FALLBACK%" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%FALLBACK%"
  exit /b %ERRORLEVEL%
)
echo CodexBridge is not installed, or the uninstaller could not be found.
pause
exit /b 1

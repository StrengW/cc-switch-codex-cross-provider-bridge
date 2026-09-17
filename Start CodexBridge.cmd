@echo off
setlocal
rem Portable source quick-start: no GitHub Release or fixed install path is required.
rem pushd also supports paths on mapped/network shares better than cd /d.
pushd "%~dp0" >nul 2>&1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\StartCodexBridge.ps1"
set "CPB_EXIT=%ERRORLEVEL%"
popd >nul 2>&1
if not "%CPB_EXIT%"=="0" (
  echo.
  echo CodexBridge could not initialize automatically.
  echo Check your internet connection on the first run and see README.md.
  pause
  exit /b %CPB_EXIT%
)
exit /b 0

@echo off
rem Runs the Makefile on Windows without a separate GNU make setup step:
rem   make up          (cmd.exe finds this file in the current folder)
rem   .\make up        (PowerShell only looks in the current folder with .\)
rem Uses make.exe when it is installed; otherwise offers to install it with
rem winget (ezwinports.make) and runs it straight away, no new terminal needed.
setlocal
cd /d "%~dp0"

where make.exe >nul 2>nul
if not errorlevel 1 (
  make.exe %*
  exit /b %errorlevel%
)

set "MAKE_EXE=%LOCALAPPDATA%\Microsoft\WinGet\Links\make.exe"
if exist "%MAKE_EXE%" goto run

where winget.exe >nul 2>nul
if errorlevel 1 (
  echo GNU make is not installed and winget is not available.
  echo Install make, e.g. from https://sourceforge.net/projects/ezwinports/files/ , and try again.
  exit /b 1
)
echo GNU make is not installed.
choice /c yn /m "Install it now with winget (ezwinports.make)"
if errorlevel 2 exit /b 1
winget install --id ezwinports.make --exact --accept-source-agreements --accept-package-agreements
if not exist "%MAKE_EXE%" (
  echo make.exe was not found after installing it - open a new terminal and run: make %*
  exit /b 1
)

:run
"%MAKE_EXE%" %*
exit /b %errorlevel%

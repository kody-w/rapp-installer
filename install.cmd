@echo off
REM RAPP Installer for Windows CMD
REM This wrapper launches the PowerShell installer
REM
REM Usage: install.cmd
REM Or: curl -o install.cmd https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.cmd && install.cmd

echo.
echo RAPP Installer
echo ==============
echo.
echo Launching PowerShell installer...
echo.

REM Run the PowerShell installer
powershell -ExecutionPolicy Bypass -Command "& { irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex }"

if %ERRORLEVEL% neq 0 (
    echo.
    echo Installation failed. Please try running install.ps1 directly in PowerShell.
    echo.
    pause
    exit /b 1
)

echo.
echo Installation complete! Open a new terminal and run: rapp
echo.
pause

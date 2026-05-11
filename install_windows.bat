@echo off
title AI Studio CLI v6.1 - Installer/Updater
setlocal

set "VERSION=6.1"
set "INSTALL_DIR=%USERPROFILE%\AppData\Local\aistudio"
set "SRC=%~dp0aistudio.py"

:: Quick update: install_windows.bat -u / update / --update
if /i "%1"=="update"   goto :UPDATE
if /i "%1"=="-u"       goto :UPDATE
if /i "%1"=="--update" goto :UPDATE

:: Full install
echo.
echo   +==================================================+
echo   ^|                                                  ^|
echo   ^|   AI Studio CLI  v%VERSION%  -  Windows Installer   ^|
echo   ^|   Multi-model  *  Agents  *  Full Filesystem    ^|
echo   ^|   Ghost Studio / Catara  *  Plan System         ^|
echo   ^|                                                  ^|
echo   +==================================================+
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python not found!
    echo   Download from: https://python.org/downloads
    echo   Make sure to check "Add Python to PATH" during install.
    echo.
    pause & exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo   [OK] %%V detected

:: Check pip
pip --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] pip not found. Run: python -m ensurepip
    pause & exit /b 1
)

:: Install dependencies
echo.
echo   Installing dependencies (rich, prompt_toolkit)...
pip install rich prompt_toolkit --quiet --upgrade
if errorlevel 1 (
    echo   [ERROR] pip install failed.
    echo   Try: pip install rich prompt_toolkit
    pause & exit /b 1
)
echo   [OK] Dependencies ready

:UPDATE
:: Ensure install dir exists
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

:: Check source file exists
if not exist "%SRC%" (
    echo.
    echo   [ERROR] aistudio.py not found next to this bat file.
    echo   Make sure install_windows.bat and aistudio.py are in the same folder.
    pause & exit /b 1
)

:: Deploy
copy /Y "%SRC%" "%INSTALL_DIR%\aistudio.py" >nul
echo   [OK] Deployed aistudio.py to %INSTALL_DIR%

:: Write launchers
echo @python "%INSTALL_DIR%\aistudio.py" %%* > "%INSTALL_DIR%\studio.bat"
echo @python "%INSTALL_DIR%\aistudio.py" %%* > "%INSTALL_DIR%\aistudio.bat"
echo   [OK] Launchers: studio.bat  aistudio.bat

if /i "%1"=="update"   goto :UPDATE_DONE
if /i "%1"=="-u"       goto :UPDATE_DONE
if /i "%1"=="--update" goto :UPDATE_DONE

:: Add to PATH (no admin required)
set "CURRENT_PATH="
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "CURRENT_PATH=%%B"

echo %CURRENT_PATH% | find /i "%INSTALL_DIR%" >nul
if errorlevel 1 (
    if "%CURRENT_PATH%"=="" (
        reg add "HKCU\Environment" /v PATH /t REG_EXPAND_SZ /d "%INSTALL_DIR%" /f >nul
    ) else (
        reg add "HKCU\Environment" /v PATH /t REG_EXPAND_SZ /d "%CURRENT_PATH%;%INSTALL_DIR%" /f >nul
    )
    echo   [OK] Added %INSTALL_DIR% to user PATH
) else (
    echo   [OK] Already in PATH
)

:: Notify Windows of PATH change (no restart needed)
powershell -Command "[System.Environment]::SetEnvironmentVariable('PATH',[System.Environment]::GetEnvironmentVariable('PATH','User'),'User')" >nul 2>&1

echo.
echo   +==================================================+
echo   ^|                                                  ^|
echo   ^|   INSTALLATION COMPLETE!                        ^|
echo   ^|                                                  ^|
echo   ^|   Open a NEW terminal window and run:           ^|
echo   ^|                                                  ^|
echo   ^|     studio             (start / first setup)    ^|
echo   ^|     studio --enter .   (load current project)   ^|
echo   ^|     studio --agent berry                        ^|
echo   ^|                                                  ^|
echo   ^|   Update later:  install_windows.bat -u         ^|
echo   ^|                                                  ^|
echo   +==================================================+
echo.
pause
exit /b 0

:UPDATE_DONE
echo.
echo   [OK] AI Studio CLI v%VERSION% updated successfully.
echo   [OK] Run: studio
echo.
exit /b 0

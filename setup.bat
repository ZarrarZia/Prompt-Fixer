@echo off
rem ==========================================================================
rem  Prompt Fixer - one-click setup
rem  Installs Python packages, Ollama and the AI models, then creates shortcuts.
rem
rem    setup.bat        interactive (asks which English/Email model to download)
rem    setup.bat /yes   unattended: everything, default models, no questions
rem ==========================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Prompt Fixer - Setup

set "PROMPT_MODEL=qwen2.5-coder:1.5b"
set "TEXT_MODEL=gemma4:e4b"
set "LIGHT_TEXT_MODEL=qwen2.5:3b"
set "UNATTENDED=0"
if /i "%~1"=="/yes" set "UNATTENDED=1"

echo.
echo  ==============================================
echo    Prompt Fixer - Setup
echo  ==============================================
echo.

rem ---------------------------------------------------------------- 1. Python
echo [1/5] Checking Python 3.10 or newer ...
call :find_python
if not defined PY (
    echo       Python not found. Installing Python 3.12 with winget ...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :no_python
    echo.
    echo       Python is installed. Close this window and run setup.bat again
    echo       so Windows picks up the new PATH.
    goto :end
)
echo       Found !PYVER!

rem ------------------------------------------------------- 2. Python packages
echo [2/5] Installing Python packages ...
!PY! -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo       pip install failed. Check your internet connection and try again.
    goto :end
)
echo       Done.

rem ---------------------------------------------------------------- 3. Ollama
echo [3/5] Checking Ollama ...
call :find_ollama
if not defined OLLAMA (
    echo       Ollama not found. Installing with winget ...
    winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
    call :find_ollama
)
if not defined OLLAMA goto :no_ollama
call :ensure_server
if errorlevel 1 goto :no_server
echo       Ollama is running.

rem ---------------------------------------------------------------- 4. Models
echo [4/5] Downloading AI models ...
echo.
echo       Standard + Loop prompt modes: %PROMPT_MODEL%  - about 1 GB
"!OLLAMA!" pull %PROMPT_MODEL%
if errorlevel 1 goto :pull_failed

set "TEXT_CHOICE=1"
if "%UNATTENDED%"=="0" (
    echo.
    echo   English + Email modes need a stronger language model:
    echo     1 = %TEXT_MODEL%   most accurate, about 9.6 GB download, needs ~10 GB RAM
    echo     2 = %LIGHT_TEXT_MODEL%   lighter, about 2 GB, less accurate on Roman Urdu
    echo     3 = skip            only use the two prompt modes
    echo.
    choice /c 123 /n /m "  Choose 1, 2 or 3: "
    set "TEXT_CHOICE=!errorlevel!"
)
if "!TEXT_CHOICE!"=="1" (
    "!OLLAMA!" pull %TEXT_MODEL%
    if errorlevel 1 goto :pull_failed
    reg delete HKCU\Environment /v PROMPT_FIXER_TEXT_MODEL /f >nul 2>&1
)
if "!TEXT_CHOICE!"=="2" (
    "!OLLAMA!" pull %LIGHT_TEXT_MODEL%
    if errorlevel 1 goto :pull_failed
    setx PROMPT_FIXER_TEXT_MODEL %LIGHT_TEXT_MODEL% >nul
    echo       English + Email modes will use %LIGHT_TEXT_MODEL% by default.
)
if "!TEXT_CHOICE!"=="3" echo       Skipped. English + Email modes will ask you to download a model.

rem ------------------------------------------------------------- 5. Shortcuts
echo.
echo [5/5] Creating shortcuts ...
call :shortcut Desktop
echo       Desktop shortcut "Prompt Fixer" created.

if "%UNATTENDED%"=="0" (
    choice /c YN /m "      Start Prompt Fixer automatically with Windows"
    if !errorlevel!==1 (
        call :shortcut Startup
        echo       Added to Windows startup.
    )
)

echo.
echo  ==============================================
echo    Setup complete.
echo    Start it from the "Prompt Fixer" desktop shortcut.
echo  ==============================================
echo.
if "%UNATTENDED%"=="0" (
    choice /c YN /m "  Launch Prompt Fixer now"
    if !errorlevel!==1 start "" "!PYW!" "%CD%\app.py"
)
goto :end


rem ======================================================== helper routines
:find_python
set "PY="
set "PYVER="
set "PYW="
for %%C in (py python) do (
    if not defined PY (
        %%C -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=%%C"
    )
)
if not defined PY exit /b 0
for /f "usebackq delims=" %%V in (`!PY! --version 2^>^&1`) do set "PYVER=%%V"
for /f "usebackq delims=" %%P in (`!PY! -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"`) do set "PYW=%%P"
exit /b 0

:find_ollama
set "OLLAMA="
for /f "delims=" %%O in ('where ollama 2^>nul') do if not defined OLLAMA set "OLLAMA=%%O"
if not defined OLLAMA if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
exit /b 0

:ensure_server
"!OLLAMA!" list >nul 2>&1 && exit /b 0
echo       Starting Ollama ...
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
) else (
    start "Ollama" /min "!OLLAMA!" serve
)
for /l %%i in (1,1,30) do (
    timeout /t 2 /nobreak >nul
    "!OLLAMA!" list >nul 2>&1 && exit /b 0
)
exit /b 1

:shortcut
rem %1 = special folder name (Desktop or Startup). Paths go through env vars to avoid quoting issues.
set "PF_FOLDER=%~1"
set "PF_PYW=!PYW!"
set "PF_DIR=%CD%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w = New-Object -ComObject WScript.Shell; $s = $w.CreateShortcut((Join-Path ([Environment]::GetFolderPath($env:PF_FOLDER)) 'Prompt Fixer.lnk')); $s.TargetPath = $env:PF_PYW; $s.Arguments = [char]34 + (Join-Path $env:PF_DIR 'app.py') + [char]34; $s.WorkingDirectory = $env:PF_DIR; $s.Description = 'Prompt Fixer'; $s.Save()"
exit /b 0


rem ========================================================== error exits
:no_python
echo.
echo   Could not install Python automatically.
echo   Install it from https://www.python.org/downloads/ - tick "Add Python to PATH" -
echo   then run setup.bat again.
goto :end

:no_ollama
echo.
echo   Could not install Ollama automatically.
echo   Install it from https://ollama.com/download, then run setup.bat again.
goto :end

:no_server
echo.
echo   Ollama is installed but did not start.
echo   Open "Ollama" from the Start menu, then run setup.bat again.
goto :end

:pull_failed
echo.
echo   Model download failed. Check your internet connection and run setup.bat again.
echo   Already-downloaded parts are kept, so it will resume where it stopped.
goto :end

:end
echo.
if "%UNATTENDED%"=="0" pause
endlocal
exit /b 0

@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW=%LocalAppData%\Microsoft\WindowsApps\pythonw.exe"
set "PYTHON=%LocalAppData%\Microsoft\WindowsApps\python.exe"

if exist "%PYTHONW%" (
    start "" "%PYTHONW%" "%~dp0antenna_toolkit_studio.py"
    exit /b 0
)

if exist "%PYTHON%" (
    start "" "%PYTHON%" "%~dp0antenna_toolkit_studio.py"
    exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0antenna_toolkit_studio.py"
    exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
    start "" python "%~dp0antenna_toolkit_studio.py"
    exit /b 0
)

echo Could not find Python or pythonw on PATH.
echo Install Python 3 and PySide6, then try again.
pause

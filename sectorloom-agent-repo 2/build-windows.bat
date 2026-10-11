@echo off
REM ============================================================
REM  Builds SectorLoomAgent.exe — run this ON the Windows machine.
REM  Needs Python 3.10 or newer from python.org (tick "Add
REM  python.exe to PATH" during install).
REM
REM  You do not normally need this. GitHub Actions builds both the
REM  program and the SectorLoomSetup.exe installer on every push —
REM  see BUILDING.md. This is here for a build without pushing.
REM ============================================================
cd /d "%~dp0"

echo.
echo [1/3] Installing what the agent needs...
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto failed

echo.
echo [2/3] Building the executable...
py -3 -m PyInstaller --noconfirm --onefile --noconsole ^
  --name SectorLoomAgent ^
  --icon installer/sectorloom.ico ^
  --collect-all duckdb ^
  --collect-all numpy ^
  --hidden-import pystray._win32 ^
  --hidden-import PIL._tkinter_finder ^
  run_agent.py
if errorlevel 1 goto failed

echo.
echo [3/3] Done.
echo Your program is here:  %cd%\dist\SectorLoomAgent.exe
echo Copy that one file anywhere you like.
echo.
echo To wrap it in the installer as well, with NSIS installed:
echo   makensis /DVERSION=1.0.0 /DAGENT_EXE=..\dist\SectorLoomAgent.exe ^^
echo            /DOUTFILE=..\dist\SectorLoomSetup.exe installer\sectorloom.nsi
echo.
pause
exit /b 0

:failed
echo.
echo Something went wrong above. The most common cause is Python
echo not being on PATH - reinstall it and tick "Add python.exe to PATH".
echo.
pause
exit /b 1

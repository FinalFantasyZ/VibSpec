@echo off
chcp 936 >nul
cd /d "%~dp0"

rem ---- Select a Python interpreter that has all required packages ----
rem Several interpreters may exist on one machine, and the first one on PATH
rem is not necessarily the one with PyQt5 / scipy / matplotlib installed.
rem Each candidate is therefore probed, and the first working one is used.

set "PY="

python -c "import PyQt5, scipy, matplotlib, numpy" >nul 2>nul
if not errorlevel 1 set "PY=python"

if not defined PY for %%P in (
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do (
    if not defined PY if exist %%P (
        %%P -c "import PyQt5, scipy, matplotlib, numpy" >nul 2>nul
        if not errorlevel 1 set "PY=%%~P"
    )
)

if not defined PY (
    echo [ERROR] No Python interpreter with PyQt5/scipy/matplotlib/numpy found.
    echo Install the packages into one interpreter first:
    echo     python -m pip install PyQt5 scipy matplotlib numpy
    echo Or set PY manually in this file.
    pause
    exit /b 1
)

if not exist "%~dp0app.py" (
    echo [ERROR] app.py not found next to this launcher.
    pause
    exit /b 1
)

"%PY%" "%~dp0app.py"
if errorlevel 1 pause

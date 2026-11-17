@echo off
rem SPDX-License-Identifier: GPL-3.0-only
cd /d "%~dp0"
if exist "%~dp0dist\bin\ShutterScope.exe" (
    start "" "%~dp0dist\bin\ShutterScope.exe"
    exit /b 0
)
if exist "%~dp0ShutterScope.exe" (
    start "" "%~dp0ShutterScope.exe"
    exit /b 0
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b 0
)
echo See README.md for build and installation instructions.
pause

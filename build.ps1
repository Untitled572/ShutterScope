# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572
param([string]$PythonExecutable = '', [string]$OutputName = 'ShutterScope')
$ErrorActionPreference = 'Stop'
$shutterOriginalPath = $env:PATH
Push-Location -LiteralPath $PSScriptRoot
try {
    if ($PythonExecutable) {
        $pythonExe = $PythonExecutable
    } else {
        $pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $pythonExe)) {
            python -m venv .venv
            if ($LASTEXITCODE -ne 0) { throw 'Failed to create virtual environment' }
        }
    }
    & $pythonExe -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    & $pythonExe tools/run_tests.py
    if ($LASTEXITCODE -ne 0) { throw 'Regression tests failed or were skipped' }
    & $pythonExe tests/gui_smoke.py
    if ($LASTEXITCODE -ne 0) { throw 'GUI integration checks failed' }
    & $pythonExe tools/package_release.py --licenses
    if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
    $basePrefix = (& $pythonExe -c 'import sys; print(sys.base_prefix)').Trim()
    $condaDllPath = Join-Path $basePrefix 'Library\bin'
    if (Test-Path -LiteralPath $condaDllPath) { $env:PATH = $condaDllPath + ';' + $env:PATH }
    $iconPath = Join-Path $PSScriptRoot 'assets\shutter.ico'
    $iconData = $iconPath + ';assets'
    $versionPath = Join-Path $PSScriptRoot 'packaging\windows-version.txt'
    $hooksPath = Join-Path $PSScriptRoot 'packaging\hooks'
    $licenseData = (Join-Path $PSScriptRoot 'LICENSE') + ';.'
    $thirdPartyData = (Join-Path $PSScriptRoot 'THIRD_PARTY_NOTICES.md') + ';.'
    $noticesData = (Join-Path $PSScriptRoot 'build\release-licenses') + ';licenses'
    & $pythonExe -m PyInstaller --noconfirm --clean --onefile --windowed --name $OutputName --distpath dist/bin --workpath build/pyinstaller --specpath build --icon $iconPath --version-file $versionPath --additional-hooks-dir $hooksPath --add-data $iconData --add-data $licenseData --add-data $thirdPartyData --add-data $noticesData --hidden-import _cffi_backend main.py
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    $exePath = Join-Path $PSScriptRoot ('dist\bin\' + $OutputName + '.exe')
    & $pythonExe tools/package_release.py --exe $exePath
    if ($LASTEXITCODE -ne 0) { throw 'Portable archive creation failed' }
} finally {
    $env:PATH = $shutterOriginalPath
    Pop-Location
}

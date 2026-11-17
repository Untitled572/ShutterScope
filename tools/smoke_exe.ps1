# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572
param([string]$ExePath = 'dist/bin/ShutterScope.exe')
$ErrorActionPreference = 'Stop'
$rootPath = Split-Path -Parent $PSScriptRoot
$absoluteExe = (Resolve-Path -LiteralPath (Join-Path $rootPath $ExePath)).Path
$reportPath = Join-Path $rootPath 'build\exe-smoke-report.json'
if (Test-Path -LiteralPath $reportPath) { Remove-Item -LiteralPath $reportPath }
$originalPath = $env:PATH
$startedAt = Get-Date
$processName = [IO.Path]::GetFileNameWithoutExtension($absoluteExe)
try {
    $env:PATH = $env:SystemRoot + '\System32;' + $env:SystemRoot
    $process = Start-Process -FilePath $absoluteExe -WorkingDirectory $rootPath -ArgumentList @('--self-test', ('"' + $reportPath + '"')) -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) { throw 'Frozen executable self-test timed out' }
    if ($process.ExitCode -ne 0) { throw ('Frozen executable failed: ' + $process.ExitCode) }
    if (-not (Test-Path -LiteralPath $reportPath)) { throw 'Frozen executable did not write its report' }
    $report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
    if (-not $report.ok -or $report.version -ne '0.1' -or $report.audio_driver -ne 'libportaudio64bit.dll') { throw 'Frozen executable report was invalid' }
    $report | ConvertTo-Json
} finally {
    $env:PATH = $originalPath
    Get-Process -Name $processName -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $absoluteExe -and $_.StartTime -ge $startedAt } |
        Stop-Process -ErrorAction SilentlyContinue
}

# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572
"""Verify archive contents, build metadata and published checksums."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from version import __version__

parser=argparse.ArgumentParser()
parser.add_argument('--require-source',action='store_true')
args=parser.parse_args()
folder=ROOT/'dist'/'release'
prefix=f'ShutterScope-{__version__}/'
windows=folder/f'ShutterScope-{__version__}-windows-x64.zip'
with zipfile.ZipFile(windows) as archive:
    names=set(archive.namelist())
    for name in ('ShutterScope.exe','README.md','LICENSE','THIRD_PARTY_NOTICES.md','BUILD-INFO.json','licenses/PortAudio.txt','licenses/Python.txt','licenses/Tcl.txt','licenses/Tk.txt','licenses/numpy/LICENSE.txt'):
        if prefix+name not in names:raise RuntimeError(f'Missing portable file: {name}')
    info=json.loads(archive.read(prefix+'BUILD-INFO.json'))
    if info['version']!=__version__ or info['license']!='GPL-3.0-only':raise RuntimeError('Invalid build metadata')
    if b'GNU GENERAL PUBLIC LICENSE' not in archive.read(prefix+'LICENSE'):raise RuntimeError('GPL text missing')
    if any('asio' in name.lower() for name in names):raise RuntimeError('ASIO file in portable archive')
source=folder/f'ShutterScope-{__version__}-source.zip'
if args.require_source and not source.is_file():raise RuntimeError('Corresponding source archive missing')
if source.is_file():
    with zipfile.ZipFile(source) as archive:
        names=archive.namelist()
        required=('main.py','core.py','transitions.py','version.py','LICENSE','build.ps1','tests/fixtures/bulb_44k.wav','.github/workflows/windows.yml')
        if any(prefix+name not in names for name in required):raise RuntimeError('Source archive is incomplete')
        for full in names:
            relative=full.removeprefix(prefix)
            if relative.startswith(('.git/','.venv/','backups/','diagnostics/','build/','dist/')) or relative.lower().endswith(('.exe','.log','.npy')):
                raise RuntimeError(f'Local/generated file in source archive: {relative}')
manifest={}
manifest_bytes=(folder/'SHA256SUMS.txt').read_bytes()
if b'\r' in manifest_bytes or not manifest_bytes.endswith(b'\n'):
    raise RuntimeError('Checksum manifest must use LF line endings for cross-platform verification')
for line in (folder/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
    checksum,name=line.split('  ',1)
    if Path(name).name!=name:raise RuntimeError('Invalid checksum filename')
    path=folder/name
    if hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:raise RuntimeError(f'Checksum mismatch: {name}')
    manifest[name]=checksum
if windows.name not in manifest or (args.require_source and source.name not in manifest):raise RuntimeError('Incomplete checksum manifest')
print(json.dumps({'ok':True,'version':__version__,'archives':manifest},indent=2))

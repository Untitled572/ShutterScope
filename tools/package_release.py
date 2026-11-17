# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572
"""Collect notices and build portable/source archives from this checkout."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import __version__


def copy_distribution_licenses(name, destination):
    distribution = metadata.distribution(name)
    count = 0
    for relative in distribution.files or ():
        parts = relative.parts
        if '/licenses/' not in str(relative).lower().replace('\\', '/'):
            continue
        source = Path(distribution.locate_file(relative))
        if not source.is_file():
            continue
        index = next(i for i, part in enumerate(parts) if part.lower() == 'licenses')
        target = destination / name / Path(*parts[index+1:])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        count += 1
    if not count:
        raise RuntimeError(f'No installed license text found for {name}')
    return distribution.version


def prepare_licenses():
    target = ROOT / 'build' / 'release-licenses'
    target.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name in ('numpy', 'sounddevice', 'cffi', 'pycparser', 'pyinstaller'):
        versions[name] = copy_distribution_licenses(name, target)
    for source in (ROOT / 'licenses').glob('*.txt'):
        shutil.copy2(source, target / source.name)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file() and 'PYTHON SOFTWARE FOUNDATION' in python_license.read_text(encoding='utf-8', errors='replace').upper():
        shutil.copy2(python_license, target / 'Python.txt')
    import tkinter
    tcl = Path(tkinter.Tcl().eval('info library'))
    for folder, name in ((tcl, 'Tcl.txt'), (tcl.parent / f'tk{tkinter.TkVersion}', 'Tk.txt')):
        license_file = folder / 'license.terms'
        if license_file.is_file():
            shutil.copy2(license_file, target / name)
    return target, versions


def commit_id():
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else 'working-tree'


def checksums(folder):
    rows = []
    for path in sorted(folder.glob('*.zip')):
        rows.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}')
    (folder / 'SHA256SUMS.txt').write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='\n')


def portable(exe):
    license_dir, versions = prepare_licenses()
    output = ROOT / 'dist' / 'release'
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f'ShutterScope-{__version__}-windows-x64.zip'
    prefix = f'ShutterScope-{__version__}'
    info = {'version': __version__, 'source_commit': commit_id(), 'python': platform.python_version(),
            'platform': platform.platform(), 'dependencies': versions,
            'audio_driver': 'PortAudio standard Windows x64 (non-ASIO)',
            'source': 'https://github.com/Untitled572/ShutterScope', 'license': 'GPL-3.0-only'}
    info_path = ROOT / 'build' / 'BUILD-INFO.json'
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(exe, f'{prefix}/ShutterScope.exe')
        for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
            archive.write(ROOT / name, f'{prefix}/{name}')
        archive.write(info_path, f'{prefix}/BUILD-INFO.json')
        for folder, inside in ((ROOT / 'docs', 'docs'), (license_dir, 'licenses')):
            for file in sorted(folder.rglob('*')):
                if file.is_file():
                    archive.write(file, f'{prefix}/{inside}/{file.relative_to(folder).as_posix()}')
    checksums(output)
    print(destination)


def source_archive():
    output = ROOT / 'dist' / 'release'
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'ShutterScope-{__version__}-source.zip'
    subprocess.run(['git', 'archive', '--format=zip', f'--prefix=ShutterScope-{__version__}/',
                    f'--output={target}', 'HEAD'], cwd=ROOT, check=True)
    checksums(output)
    print(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--licenses', action='store_true')
    group.add_argument('--exe', type=Path)
    group.add_argument('--source', action='store_true')
    args = parser.parse_args()
    if args.licenses:
        print(prepare_licenses()[0])
    elif args.source:
        source_archive()
    else:
        portable(args.exe.resolve(strict=True))

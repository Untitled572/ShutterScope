# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572
from importlib.util import find_spec
from pathlib import Path

module = Path(find_spec("sounddevice").origin).parent
driver = module / "_sounddevice_data" / "portaudio-binaries" / "libportaudio64bit.dll"
if not driver.is_file():
    raise RuntimeError("The standard Windows x64 PortAudio driver is missing")
binaries = [(str(driver), "_sounddevice_data/portaudio-binaries")]
hiddenimports = ["_cffi_backend", "_sounddevice_data"]

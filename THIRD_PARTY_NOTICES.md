# 第三方组件声明

ShutterScope 自有代码采用 GPL-3.0-only。第三方组件保留各自的许可，不因本项目选择 GPL 而失去原有版权声明。

| 组件 | 许可 | 上游与源码 |
| --- | --- | --- |
| CPython | PSF 及其附带声明 | https://www.python.org/downloads/source/ |
| Tcl / Tk | Tcl/Tk 许可 | https://github.com/tcltk/tcl · https://github.com/tcltk/tk |
| NumPy，含其分发包内的 OpenBLAS/LAPACK 等组件 | BSD 及包内其他许可 | https://pypi.org/project/numpy/#files |
| python-sounddevice | MIT | https://pypi.org/project/sounddevice/#files |
| PortAudio 标准 Windows 驱动 | MIT | https://github.com/PortAudio/portaudio |
| CFFI / libffi | MIT | https://pypi.org/project/cffi/#files · https://github.com/libffi/libffi |
| pycparser | BSD | https://pypi.org/project/pycparser/#files |
| PyInstaller bootloader | GPL，附运行时分发例外 | https://pyinstaller.org/en/stable/license.html |
| OpenSSL（运行库依赖） | Apache 2.0 | https://github.com/openssl/openssl |
| libmpdec（运行库依赖） | BSD | https://www.bytereef.org/mpdecimal/ |

Windows 包的 `licenses/` 包含许可原文，包括 NumPy 分发包内的完整第三方声明。构建时从安装的分发包和运行库收集这些文件；`BUILD-INFO.json` 记录本次使用的 Python 和依赖版本，具体版本的源码可从上述上游下载页获取。

本包仅包含 `libportaudio64bit.dll` 标准驱动，未打包 ASIO 驱动、其他架构或其他操作系统的 PortAudio 库。源码发行包包含本项目的构建与打包脚本；第三方源码仍按其各自的许可提供。

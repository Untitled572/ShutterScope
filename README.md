# ShutterScope

[![Windows build](https://github.com/Untitled572/ShutterScope/actions/workflows/windows.yml/badge.svg)](https://github.com/Untitled572/ShutterScope/actions/workflows/windows.yml)
[下载 0.1](https://github.com/Untitled572/ShutterScope/releases/tag/v0.1) · [使用说明](docs/usage.md) · [测试记录](docs/validation.md) · [GPLv3](LICENSE)

ShutterScope 是一个 Windows 光电快门测速工具。它读取麦克风输入口上光电二极管产生的信号，识别快门开启和关闭时的光变，估计二极管所在位置的曝光时长。

程序使用 Python、Tkinter 和 PortAudio，界面采用白色 WinUI 风格。实时音频在本机内存中处理，不上传录音，不更改系统音频设置。

## 功能

- 实时波形、输入峰值和噪声校准。
- 快门与 B 门检测，默认最长等待 30 秒。曝光中电压衰减回零时，继续等待真正的关闭沿。
- 支持半高宽、固定电平和 AC 配对模式，便于核对不同波形。
- 波形缩放、冻结、双游标测时，显示时长和接近的参考档位。
- 导入整数 PCM WAV，导出测量 CSV 和单声道 WAV。
- 保留本次会话的测量记录，以及最近 10 条原始波形。

## 下载与运行

在 [Releases](https://github.com/Untitled572/ShutterScope/releases) 下载 `ShutterScope-0.1-windows-x64.zip`，解压后运行 `ShutterScope.exe`。便携包无需安装 Python，适用于 Windows x64。仓库为私有时，下载需要相应的 GitHub 访问权限。

发行包提供 `LICENSE`、第三方许可、构建信息；Release 另附对应源码和 `SHA256SUMS.txt`。Windows 版本未做代码签名，使用标准 PortAudio 驱动，不包含 ASIO。

## 开始测量

1. 使用稳定常亮光源照射快门，把光电二极管放在快门后方待测位置，减少漏光。
2. 选择二极管实际连接的输入设备和声道，打开预览。改变光照时应能看到波形变化。
3. 遮住二极管，等待至少半秒，再点击“遮光校准噪声”。
4. 恢复光路，使用默认的“快慢门 · 光变沿配对”；未知快门速度时，将“预计档位”保留为“不限”。
5. 开始测量，等待 0.3 秒预热后触发快门。金色竖线标出用于计时的开启和关闭位置。
6. 核对波形，关闭程序前导出需要的记录。空格键可切换开始/停止，冻结显示不会停止后台采集。

建议关闭声卡的降噪、自动增益和回声消除，保持输入增益固定。不同光路、二极管和声卡可能需要调整阈值及极性，详见[使用说明](docs/usage.md)。

## 测量范围与限制

结果来自音频采样时钟和局部光变沿的位置，不能把界面小数位当作整套仪器的精度保证。二极管响应、声卡滤波、光源和快门遮挡方式都会影响结果；单只二极管也不能判断全画幅曝光是否均匀。

项目已有真实短快门、B 门和手电信号的回放测试，以及跨块处理、噪声、过冲和 12 秒合成曝光测试。样本没有标准计时仪校准值，也不把相机标称档位当作正确答案。测试方法和结果见[测试记录](docs/validation.md)。

## 从源码运行

开发和自动构建使用 Python 3.13。

```powershell
git clone https://github.com/Untitled572/ShutterScope.git
cd ShutterScope
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## 测试与构建

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/run_tests.py
.\.venv\Scripts\python.exe tests/gui_smoke.py
.\build.ps1
```

构建输出位于 `dist/bin/`，便携包和校验值位于 `dist/release/`。打包脚本收集第三方许可，冻结后的程序也有独立自检。

GitHub Actions 在 Windows 上运行回归测试、GUI 检查、打包和 EXE 自检。推送带 `v` 前缀、与 `version.py` 对应的版本标签（例如 `v0.1`）后，工作流会创建 Release，并上传 Windows 包、对应源码和校验值。

## 参与开发

问题反馈请附软件版本、检测模式、采样率、阈值、预期行为与实际结果；如需提供 WAV，先确认其中没有不希望分享的录音。修改代码的步骤见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

Copyright (C) 2026 Untitled572。

本项目按 **GNU GPL version 3 only（GPL-3.0-only）** 发布，完整条款见 [LICENSE](LICENSE)。允许修改、再分发和商业使用；分发受 GPL 覆盖的衍生版本时，应遵守对应源码及相同许可的要求。本程序不提供担保。

第三方组件保留各自的许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

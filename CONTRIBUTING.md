# 参与开发

先阅读 README 和使用说明，了解检测模式的适用波形与测量限制。

1. 使用 Python 3.13 创建虚拟环境，安装 `requirements-dev.txt`。
2. 修改检测逻辑时，为原问题增加能复现的回归用例；样本应只包含可分享的光电信号。
3. 运行 `python tools/run_tests.py` 和 `python tests/gui_smoke.py`。修改打包后还需运行 `build.ps1` 与 `tools/smoke_exe.ps1`。
4. 提交前检查差异，避免包含录音导出、日志、个人路径、虚拟环境和生成的 EXE。

版本号位于 `version.py`。发布时同时更新 Windows 版本资源、变更记录和对应发布说明，推送带 `v` 前缀的版本标签，例如 `v0.1`。

提交的项目代码按 GPL-3.0-only 提供；第三方代码需保留来源和原许可。问题报告应包含版本、参数、复现步骤及实际结果。

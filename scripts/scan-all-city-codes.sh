#!/usr/bin/env bash
# **一次扫出所有**智联城市码 —— 比「一城一城扫」快一个数量级。
#
# 用法：bash scripts/scan-all-city-codes.sh
#
# ## 和 find_city_code.sh 的区别
#
# | | find_city_code.sh | scan-all-city-codes.sh |
# | --- | --- | --- |
# | 目标 | 找**一座**城市的码 | 扫出**全部**城市的码 |
# | 扫几遍 | N 座城市 = N 遍 | **只扫 1 遍** |
# | 用时 | 每城约 1 分钟 | **约 8 分钟**（150 个码 × 2.5 秒） |
#
# 找单座城市用 `find_city_code.sh`；**一次性补全码表用这个**。
#
# ## 为什么 bash 路径要显式传
#
# Python 的 subprocess 调 `bash` 时，Windows 的 PATH 会先命中
# **WSL 的 bash**（报 `execvpe(/bin/bash) failed`），
# 而 Git Bash 在 `/usr/bin/bash.exe`（MSYS 路径，Python 认不了），
# 所以要用 cygpath 转成 Windows 绝对路径再传给 Python。
set -uo pipefail

export HERMES_HOME="${HERMES_HOME:-$LOCALAPPDATA/hermes}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BASH_WIN="$(cygpath -w /usr/bin/bash.exe 2>/dev/null || echo bash)"
BB_WIN="$(cygpath -w "$HERMES_HOME/tools/bb-browser/bb.sh" 2>/dev/null || echo "")"

# **用相对路径调 Python** ——
# cygpath 对含中文的路径会转出错的 Windows 路径（找不到文件）。
cd "$REPO" || exit 1
python scripts/scan_all_city_codes.py "$BASH_WIN" "$BB_WIN" "."

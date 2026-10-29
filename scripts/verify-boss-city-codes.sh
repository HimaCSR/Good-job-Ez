#!/usr/bin/env bash
# 验证 boss_city_codes.py 里的码表 —— **每个码都要实测**。
#
# 码表里的码如果是猜的，抓取时会**静默抓到别的城市**。
# 所以这里逐个跑一次真实抓取，看返回的城市名对不对。
#
# 用法：bash scripts/verify-boss-city-codes.sh
#
# ## 为什么 bash 路径要显式传
#
# Python 的 subprocess 调 `bash` 时，Windows 的 PATH 会先命中
# **WSL 的 bash**（报 `execvpe(/bin/bash) failed`），
# 而 Git Bash 在 `/usr/bin/bash.exe`（MSYS 路径，Python 认不了），
# 所以要用 cygpath 转成 Windows 绝对路径再传给 Python。
#
# ## 前提
#
# 浏览器（9222）里要有一个**已登录**的 BOSS 页面 ——
# BOSS 的 API 必须在页面上下文里发（要 anti-content token）。
# 脚本会自动 open 一个，但**登录态**得你事先在浏览器里弄好。
set -uo pipefail

export HERMES_HOME="${HERMES_HOME:-$LOCALAPPDATA/hermes}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BASH_WIN="$(cygpath -w /usr/bin/bash.exe 2>/dev/null || echo bash)"
BB_WIN="$(cygpath -w "$HERMES_HOME/tools/bb-browser/bb.sh" 2>/dev/null || echo "")"

# **用相对路径调 Python** ——
# cygpath 对含中文的路径会转出错的 Windows 路径（找不到文件）。
cd "$REPO" || exit 1
python scripts/verify_boss_city_codes.py "$BASH_WIN" "$BB_WIN" "."

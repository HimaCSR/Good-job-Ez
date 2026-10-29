#!/usr/bin/env bash
# 新用户端到端验证 —— 装完插件能不能真的用起来。
#
# **全程用临时目录**，不碰用户真实数据。
# **真打招聘网站**（这才是真验证 —— mock 只能证明代码没崩）。
#
# 走一遍：
#   1. 空画像（模拟刚装完）
#   2. 填画像（含主攻方向）→ 读回确认存住
#   3. 抓取（真网站，2 个城市 × 1 个关键词）
#   4. 打分 → 确认主攻方向排前面
#   5. 简历优化 → 确认工作经历章节有公司名
#   6. 日报 → 确认生成 Markdown
#   7. 结构化经历新增 → 确认不挤掉旧的
#
# 用法：bash scripts/verify_new_user.sh
set -uo pipefail

export HERMES_HOME="${HERMES_HOME:-$LOCALAPPDATA/hermes}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

python scripts/verify_new_user.py

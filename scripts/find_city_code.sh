#!/usr/bin/env bash
# 找出某个城市的智联城市码 —— **不用改任何文件**。
#
# ## 为什么需要
#
# `city_codes.py` 里只有 36 个**实测通过**的城市。
# 想加新城市（成都、西安、武汉…）就得先找到它的码。
#
# ## 怎么找
#
# 实测发现的规律：
# - **3000 段 = 地级市**，每 5 个码一个城市
#   （3002 宁波、3020 济宁、3030 淄博、3040 常州、3050 徐州、
#     3060 镇江、3065 扬州、3070 泰州、3075 盐城、3080 淮安、
#     3090 连云港、3095 泉州、3105 绍兴、3110 温州、3115 金华、
#     3125 台州、3135 丽水、3145 海口、3150 南宁、3160 柳州、
#     3165 桂林、3170 北海、3180 珠海、3210 江门、3220 东莞）
# - **500 段 = 直辖市/省会**（530 北京、538 上海、539 南京、
#   540 杭州、551 重庆、763 广州、765 深圳）
#
# 所以扫 3000 段 + 常见 5xx 段就行。
#
# ## 用法
#
#     bash scripts/find_city_code.sh 成都
#     bash scripts/find_city_code.sh 西安 3
#       ↑ 第二个参数 = 关键词（默认「运营」）
#
# 找到之后**不用改代码** —— 把城市名和码加进
# `src/job_radar/city_codes.py` 的 `CITY_CODES`，
# 再跑 `bash scripts/verify-city-codes.sh` 确认。

set -uo pipefail

export HERMES_HOME="${HERMES_HOME:-$LOCALAPPDATA/hermes}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BASH_WIN="$(cygpath -w /usr/bin/bash.exe 2>/dev/null || echo bash)"
BB_WIN="$(cygpath -w "$HERMES_HOME/tools/bb-browser/bb.sh" 2>/dev/null || echo "")"
REPO_WIN="$(cygpath -w "$REPO" 2>/dev/null || echo "$REPO")"

cd "$REPO" || exit 1
python scripts/find_city_code.py "$BASH_WIN" "$BB_WIN" "$REPO_WIN" "$@"

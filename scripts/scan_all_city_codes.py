"""一次扫出**所有**智联城市码 —— 比「一城一城扫」快一个数量级。

## 为什么不用 find_city_code.py

`find_city_code.py` 是**给一个城市找码**：扫一遍候选码，找到匹配就停。
**5 个城市 = 扫 5 遍**，同一个码被重复请求 N 次 —— 既慢又容易触发风控。

**这个脚本反过来**：扫一遍候选码，**记录每个码返回的城市名**，
一次性得到**完整映射表**。

## 用法

    python scripts/scan_all_city_codes.py <bash> <bb.sh> <repo>

（外层 `scripts/scan-all-city-codes.sh` 负责算路径）

## 码段规律（实测总结）

- **5xx 段 = 直辖市 / 省会**
  530 北京、538 上海、539 南京、540 杭州、**551 重庆**、**552 成都**、
  763 广州、765 深圳
  → **这个段基本连续**，要扫就**整个扫**（530~620），别跳着扫
- **3000 段 = 地级市**，每 5 个码一个城市
  3002 宁波、3040 常州、3150 南宁、3165 桂林、3180 珠海、3220 东莞
- **码不能靠记忆** —— 按记忆填的 60 个里 28 个是错的

## 限速

每个码之间 sleep（默认 2.5 秒）—— 智联对高频请求会限流，
一旦被限流后面全白扫。

## 输出

`docs/智联城市码表.md` 的表格 + 一份 JSON，方便直接写进
`src/job_radar/city_codes.py`。
"""

import json
import os
import subprocess
import sys
import time
from collections import Counter

# 5xx 段：直辖市/省会（**连续，要整个扫**）
CODES_5XX = list(range(530, 621))

# 3000 段：地级市（每 5 个一个城市）
CODES_3XXX = list(range(3000, 3301, 5))

# 一些 4xx/6xx 段的零散城市（实测过的）
CODES_MISC = [412, 413, 414, 415, 416, 417, 418, 419, 420,
               600, 601, 602, 603, 604, 605, 606, 607, 608, 609, 610,
               611, 612, 613, 614, 615, 616, 617, 618, 620,
               766, 767, 768, 769, 770, 771, 772, 773, 774, 775]


def all_codes():
    seen, out = set(), []
    for c in CODES_5XX + CODES_3XXX + CODES_MISC:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def probe(bash, bb, code, kw="运营"):
    """跑一次真实抓取，返回 (主城市名, 岗位数)。失败返回 (None, 0)。"""
    try:
        p = subprocess.run(
            [bash, bb, "site", "zhaopin/search", kw,
             "--city", str(code), "--json"],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
    except Exception:
        return None, 0
    out = (p.stdout or "").strip()
    if not out:
        return None, 0
    try:
        d = json.loads(out)
    except json.JSONDecodeError:
        return None, 0
    r = d.get("result", d)
    if not isinstance(r, dict) or "error" in r:
        return None, 0
    jobs = r.get("jobs") or []
    if not jobs:
        return None, 0
    # 城市名：取最常见的那个（少数岗位会跨城）
    c = Counter([(j.get("area") or "?").split()[0] for j in jobs])
    return (c.most_common(1)[0][0], r.get("count", 0))


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    bash, bb, repo = sys.argv[1], sys.argv[2], sys.argv[3]
    os.chdir(repo)

    codes = all_codes()
    print("要扫 %d 个候选码，每个间隔 2.5 秒 → 约 %d 分钟"
          % (len(codes), len(codes) * 2.5 // 60 + 1))
    print()

    mapping = {}       # 码 → 城市名
    city_codes = {}    # 城市名 → 码
    skipped = 0

    for i, code in enumerate(codes, 1):
        name, n = probe(bash, bb, code)
        if name and name != "?":
            mapping[code] = name
            # 同一个城市多个码 → 保留第一个（较小的）
            if name not in city_codes:
                city_codes[name] = code
        else:
            skipped += 1
        if i % 10 == 0 or i == len(codes):
            print("  [%d/%d] 已找到 %d 个城市（跳过 %d 个无效码）"
                  % (i, len(codes), len(city_codes), skipped))
        time.sleep(2.5)

    print()
    print("=== 结果：%d 个城市 ===" % len(city_codes))
    for name in sorted(city_codes):
        print("  %-10s %s" % (name, city_codes[name]))

    out_json = os.path.join(repo, "docs", "智联城市码实测.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump({"by_name": city_codes, "by_code": mapping},
                  fh, ensure_ascii=False, indent=1)
    print()
    print("已写入 %s" % out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""扫出某个城市的智联城市码 —— **只读，不改任何文件**。

## 用法

    python scripts/find_city_code.py <bash> <bb.sh> <repo> 成都 [关键词]

（外层 `scripts/find_city_code.sh` 会把路径转换好再调这里）

## 怎么扫

实测发现的规律：

- **3000 段 = 地级市**，每 5 个码一个城市
  （3002 宁波、3020 济宁、3030 淄博、3040 常州、3050 徐州、
  3060 镇江、3065 扬州、3070 泰州、3075 盐城、3080 淮安、
  3090 连云港、3095 泉州、3105 绍兴、3110 温州、3115 金华、
  3125 台州、3135 丽水、3145 海口、3150 南宁、3160 柳州、
  3165 桂林、3170 北海、3180 珠海、3210 江门、3220 东莞）
- **500 段 = 直辖市/省会**（530 北京、538 上海、539 南京、
  540 杭州、551 重庆、763 广州、765 深圳）

所以扫 **3000~3300** + 常见 5xx 段。

## 为什么必须实测

**城市码不能靠记忆** —— 本机按记忆填了 60 个码，
实测 **28 个是错的**（成都 599 实际是沈阳、西安 566 实际是唐山…）。

错码**不报错、不警告**，只是静默抓到别的城市。

## 找到之后

把城市名和码加进 `src/job_radar/city_codes.py` 的 `CITY_CODES`，
然后跑 `bash scripts/verify-city-codes.sh` 确认。
"""

import json
import os
import subprocess
import sys
from collections import Counter

# 3000 段（地级市）+ 常见 5xx 段（省会/直辖市）
CANDIDATE_CODES = (
    [str(c) for c in range(3000, 3301, 5)]
    + ["530", "538", "539", "540", "551", "552", "558", "560",
       "565", "566", "573", "591", "592", "599", "619",
       "763", "765"]
)


def probe(bash, bb, code, kw):
    """跑一次真实抓取，返回主要城市名（None = 失败）。"""
    try:
        p = subprocess.run(
            [bash, bb, "site", "zhaopin/search", kw,
             "--city", str(code), "--json"],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
    except Exception:
        return None, 0
    if not (p.stdout or "").strip():
        return None, 0
    try:
        d = json.loads(p.stdout.strip())
    except json.JSONDecodeError:
        return None, 0
    r = d.get("result", d)
    if not isinstance(r, dict) or "error" in r:
        return None, 0
    jobs = r.get("jobs") or []
    c = Counter([(j.get("area") or "?").split()[0] for j in jobs])
    return (c.most_common(1)[0][0] if c else None), r.get("count", 0)


def main():
    bash = sys.argv[1] if len(sys.argv) > 1 else "bash"
    bb = sys.argv[2] if len(sys.argv) > 2 else ""
    repo = sys.argv[3] if len(sys.argv) > 3 else os.getcwd()
    if len(sys.argv) < 5:
        print("用法：python scripts/find_city_code.py <bash> <bb.sh> <repo> 城市名 [关键词]")
        return 2
    target = sys.argv[4].strip()
    kw = sys.argv[5] if len(sys.argv) > 5 else "运营"

    sys.path.insert(0, os.path.join(repo, "src"))
    try:
        from job_radar.city_codes import CITY_CODES
    except ImportError:
        from city_codes import CITY_CODES

    known = {v: k for k, v in CITY_CODES.items()}

    print("找「%s」的智联城市码（关键词「%s」）…" % (target, kw))
    print("扫 %d 个候选码，约 %d 秒" %
          (len(CANDIDATE_CODES), len(CANDIDATE_CODES) * 6))
    print()

    hits = []
    for i, code in enumerate(CANDIDATE_CODES, 1):
        city, cnt = probe(bash, bb, code, kw)
        if city and (target in city or city in target):
            hits.append((code, city, cnt))
            print("  ✔ city=%-5s -> %s（%d 条）  ★ 命中「%s」" %
                  (code, city, cnt, target), flush=True)
        elif city and cnt:
            print("    city=%-5s -> %s（%d 条）" % (code, city, cnt), flush=True)
        else:
            print("    city=%-5s -> (空)" % code, flush=True)

    print()
    if hits:
        print("找到 %d 个匹配：" % len(hits))
        for code, city, cnt in hits:
            print("  %s = %s   （抓到的岗位城市名是「%s」）" %
                  (code, known.get(code, "?"), city))
        print()
        print("下一步：把城市名和码加进 src/job_radar/city_codes.py 的 CITY_CODES，")
        print("        然后跑 bash scripts/verify-city-codes.sh 确认。")
    else:
        print("没找到「%s」。" % target)
        print("可能：")
        print("  · 该城市在智联没有「%s」相关的岗位 —— 换个关键词再试" % kw)
        print("  · 该城市的码不在扫的段里 —— 试试扩大 CANDIDATE_CODES")
        print("  · 该城市确实没有招聘数据（有些小城市智联没站点）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

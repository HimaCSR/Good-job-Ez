"""验证智联城市码表 —— **每个码都实测**。

## 为什么必须实测

码表里的码如果是猜的，抓取时会**静默抓到别的城市** ——
不报错、不警告，只是推的岗位全是杭州的。

所以每次改 `city_codes.py` 都要跑一遍这个。

## 怎么判定

对每个「城市名 → 码」跑一次真实抓取（关键词「运营」），
看返回岗位的 `area` 城市名：

- 等于城市名 → ✔ 对
- 不等 → ✘ **错**（码要改）
- 0 条 → 该城市该关键词没岗位，码**可能**对（不算错）

## 为什么 bash 路径是参数

Python 的 subprocess 调 `bash` 时，Windows 的 PATH 会先命中
**WSL 的 bash**（`execvpe(/bin/bash) failed`），
Git Bash 在 `/usr/bin/bash.exe`（MSYS 路径，Python 认不了）。
所以外层 shell 用 cygpath 转成 Windows 路径再传进来。
"""

import json
import os
import subprocess
import sys
from collections import Counter

BASH = sys.argv[1] if len(sys.argv) > 1 else "bash"
BB = sys.argv[2] if len(sys.argv) > 2 else ""
REPO = sys.argv[3] if len(sys.argv) > 3 else os.getcwd()

sys.path.insert(0, os.path.join(REPO, "src"))
try:
    from job_radar.city_codes import CITY_CODES
except ImportError:
    from city_codes import CITY_CODES

# **别名** —— 有些城市跟主城市共用一个码（区级划分），
# 抓回来显示的是主城市名，这是**对的**，不算错。
ALIASES = {
    "佛山": "广州", "惠州": "广州",
    "苏州": "常州", "无锡": "常州",
}


def probe(code, kw="运营"):
    """跑一次真实抓取，返回 (条数, 主要城市名)。失败返回 (None, None)。"""
    try:
        p = subprocess.run(
            [BASH, BB, "site", "zhaopin/search", kw,
             "--city", str(code), "--json"],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
    except Exception as exc:
        print("    subprocess 失败: %s" % str(exc)[:120])
        return None, None
    if not (p.stdout or "").strip():
        print("    无输出 stderr=%s" % (p.stderr or "")[:160])
        return None, None
    try:
        d = json.loads(p.stdout.strip())
    except json.JSONDecodeError:
        print("    输出不是 JSON: %s" % (p.stdout or "")[:160])
        return None, None
    r = d.get("result", d)
    if isinstance(r, dict) and "error" in r:
        print("    adapter 错误: %s" % str(r["error"])[:120])
        return None, None
    jobs = r.get("jobs") or []
    c = Counter([(j.get("area") or "?").split()[0] for j in jobs])
    return r.get("count", 0), (c.most_common(1)[0][0] if c else None)


def main():
    print("验证 %d 个城市码（每条约 6 秒）…" % len(CITY_CODES))
    bad, ok, empty = [], [], []
    for name, code in sorted(CITY_CODES.items()):
        cnt, top = probe(code)
        if cnt is None:
            bad.append((name, code, "ERR"))
            print("  ERR %-8s %-6s" % (name, code), flush=True)
            continue
        if cnt == 0:
            empty.append((name, code))
            print("  --  %-8s %-6s (0 条，码可能对)" % (name, code), flush=True)
            continue
        expected = ALIASES.get(name, name)
        mark = "OK" if top == expected else "XX"
        if top == expected:
            ok.append((name, code))
        else:
            bad.append((name, code, top))
        print("  %s  %-8s %-6s -> %s (%d 条)" % (mark, name, code, top, cnt),
              flush=True)

    print()
    print("对: %d  错: %d  空: %d" % (len(ok), len(bad), len(empty)))
    if bad:
        print("错的（码要改）:")
        for b in bad:
            print("  ", b)
    if empty:
        print("空的（该城市该关键词没岗位）:")
        for e in empty:
            print("  ", e)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

"""验证 boss_city_codes.py 里的码表 —— **每个码都要实测**。

码表里的码如果是猜的，抓取时会**静默抓到别的城市**。
所以这里逐个跑一次真实抓取，看返回的城市名对不对。

用法：
    python scripts/verify_boss_city_codes.py <bash路径> <bb.sh路径> <仓库根>

（外层 `scripts/verify-boss-city-codes.sh` 负责算路径）

## 为什么必须有这个脚本

**实测教训（2026-10-29）**：我一开始按「省份段 + 城市序号」的规律
**猜**了 60 个码，结果 **6 个是错的**：

| 城市 | 我猜的 | 实际 |
| --- | --- | --- |
| 东莞 | 101281200 | **101281600** |
| 宜昌 | 101200500 | **101200900** |
| 株洲 | 101250400 | **101250300** |
| 洛阳 | 101180700 | **101180900** |
| 衡阳 | 101250300 | **101250400** |
| 襄阳 | 101200600 | **101200200** |

全是**同省城市序号记错**。**猜的码不可信** —— 必须实测。

## 官方码表接口

    GET https://www.zhipin.com/wapi/zpgeek/common/data/city/site.json

在 zhipin 页面上下文里 fetch（**必须**，否则拿不到 anti-content token）。
返回 400 个城市码。这个脚本**顺带**用官方接口交叉核对。

## 实测抓取怎么验

跑一次 `boss/search --city <码>`，看返回岗位的 `city` 是不是目标城市。
"""

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from job_radar import boss_city_codes  # noqa: E402


def run_site(bash_path, bb_path, query, city_code, timeout=150) -> dict:
    """跑一次 boss/search，返回 {"jobs": [...]} 或 {"error": ...}。"""
    cmd = [bash_path, bb_path, "site", "boss/search", query,
           "--city", str(city_code), "--json"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"error": "超时"}
    out = (p.stdout or "").strip()
    if not out:
        return {"error": (p.stderr or "无输出")[:120]}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"error": "不是 JSON: %s" % out[:100]}
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err, ensure_ascii=False)
        return {"error": str(err)}
    return data if isinstance(data, dict) else {}


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    bash_path, bb_path, repo = sys.argv[1], sys.argv[2], sys.argv[3]
    os.chdir(repo)

    # ── ① 先确保有 BOSS 页面上下文 ──
    print("=== 准备 BOSS 页面上下文 ===")
    try:
        from job_radar import bbclient
        ready = bbclient.ensure_boss_context()
    except Exception as exc:
        print("  准备失败：%s" % exc)
        ready = {"ok": False, "detail": str(exc)}
    if not ready.get("ok"):
        print("  ✘ 没能打开 BOSS 页面：%s" % ready.get("detail"))
        print("  先在浏览器里打开一次 BOSS 搜索页并登录，再重跑。")
        return 2
    print("  ✔ %s（tab=%s）" % (ready.get("detail"), ready.get("tab")))

    # ── ② 官方码表交叉核对 ──
    print()
    print("=== 官方接口交叉核对 ===")
    official = fetch_official(bash_path, bb_path)
    if official:
        bad = []
        for name, code in boss_city_codes.CITY_CODES.items():
            real = official.get(name)
            if real is None:
                bad.append((name, code, "官方表里没有这个城市名"))
            elif str(real) != str(code):
                bad.append((name, code, "官方是 %s" % real))
        print("  码表 %d 个，官方表 %d 个" %
              (len(boss_city_codes.CITY_CODES), len(official)))
        if bad:
            print("  ✘ %d 个对不上：" % len(bad))
            for n, c, why in bad:
                print("     %-8s 码表=%-10s %s" % (n, c, why))
        else:
            print("  ✔ 全部对得上")
    else:
        print("  （拿不到官方接口，跳过交叉核对）")

    # ── ③ 逐个实测抓取 ──
    print()
    print("=== 逐个实测抓取（验证真的抓到那个城市）===")
    ok = 0
    fail = 0
    # **只验几个城市** —— 全跑 63 个要十几分钟，还容易把 BOSS 打出风控。
    # 用法：python scripts/verify_boss_city_codes.py <bash> <bb.sh> <repo> 重庆 成都
    only = sys.argv[4:]
    targets = []
    for name, code in sorted(boss_city_codes.CITY_CODES.items()):
        if only and name not in only:
            continue
        targets.append((name, code))
    if only:
        print("（只验：%s）" % "、".join(only))
    print()
    for name, code in targets:
        data = run_site(bash_path, bb_path, "运营", code)
        if "error" in data:
            print("  %-8s %-10s ✘ %s" % (name, code, str(data["error"])[:60]))
            fail += 1
            continue
        jobs = data.get("jobs") or []
        cities = set()
        for j in jobs:
            c = j.get("city") or (j.get("area") or "").split("·")[0]
            if c:
                cities.add(c)
        if not jobs:
            print("  %-8s %-10s ○ 没有岗位（可能该城市无结果）" % (name, code))
        elif cities == {name}:
            print("  %-8s %-10s ✔ %d 条，全是 %s" % (name, code, len(jobs), name))
            ok += 1
        else:
            print("  %-8s %-10s ✘ 返回了 %s（不是 %s）"
                  % (name, code, sorted(cities), name))
            fail += 1
        time.sleep(2)     # 限速，别把 BOSS 打出风控

    print()
    print("=== 结果：对 %d，错 %d ===" % (ok, fail))
    return 0 if fail == 0 else 1


def fetch_official(bash_path, bb_path):
    """从 BOSS 官方接口拿城市全表（返回 {城市名: 码}）。"""
    # **不能用 `bb-browser eval "<长代码>"`** ——
    # 它走命令行，**Windows 命令行有 8191 字符上限**，长代码会被截断。
    # 所以改用 CDP 直连（Runtime.evaluate 没有长度限制）。
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fetch_boss_cities.mjs")
    if not os.path.exists(script):
        return {}
    node = find_node()
    if not node:
        return {}
    out_file = os.path.join(os.environ.get("TEMP", "."), "boss_cities.json")
    cmd = [node, script, out_file]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return {}
    if not os.path.exists(out_file):
        return {}
    try:
        with open(out_file, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def find_node():
    """找 node —— **不硬编码本机路径**。

    ## 为什么要 glob 而不是 which

    本机 PATH 里的 `node` 是 **node 14**（没有 fetch，脚本跑不了）。
    Hermes 自带的是 node 26.7.0，在 `$LOCALAPPDATA/hermes/tools/node-*/node.exe`。

    所以顺序是：**先试 Hermes 自带的（版本对）**，再用 PATH 的。
    """
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        import glob
        cands = sorted(glob.glob(os.path.join(local, "hermes", "tools",
                                             "node-*", "node.exe")))
        for cand in cands:
            # **验一下版本** —— node 14 没有 fetch
            try:
                p = subprocess.run([cand, "-e",
                                    "console.log(process.versions.node)"],
                                   capture_output=True, text=True, timeout=15)
                ver = (p.stdout or "").strip()
                major = ver.split(".")[0] if ver else "0"
                if major.isdigit() and int(major) >= 18:
                    return cand
            except Exception:
                continue
    from shutil import which
    return which("node")


if __name__ == "__main__":
    sys.exit(main())

"""bb-browser CLI 封装。所有外部进程调用集中在这里，便于限速与排查。"""

import json
import os
import random
import subprocess
import time

BB_SH = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "tools",
                     "bb-browser", "bb.sh")
BASE_GAP = 12          # 秒，基准间隔
GAP_JITTER = (8, 20)   # 随机抖动区间 → 实际间隔 12~32 秒


# Windows 上 subprocess 不能直接执行 .sh，必须走 bash。
# 注意：PATH 里的 `bash` 可能是 WSL 的（在本机不可用），
# 所以优先找 Git for Windows 自带的 bash。
BASH_CANDIDATES = [
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
]


def _find_bash():
    for cand in BASH_CANDIDATES:
        if os.path.exists(cand):
            return cand
    # 退化：找 PATH 里的 bash，但要能真的跑起来
    for cand in ("bash",):
        try:
            p = subprocess.run([cand, "-c", "echo ok"], capture_output=True,
                               text=True, timeout=10)
            if p.returncode == 0 and "ok" in (p.stdout or ""):
                return cand
        except Exception:
            continue
    raise OSError("找不到可用的 bash（Git for Windows），无法执行 bb.sh")


def _cmd(*parts):
    """组装成 [bash, bb.sh, ...] 命令行。"""
    return [_find_bash(), BB_SH, *parts]


def run_site(site, *args, timeout=120):
    """跑一个 adapter，返回解析后的 JSON。失败返回 {"error": ...}。"""
    cmd = _cmd("site", site, *args, "--json")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"error": "bb-browser 超时(%ss)" % timeout}
    except FileNotFoundError:
        return {"error": "找不到 bash 或 bb.sh: %s" % BB_SH}
    except OSError as e:
        return {"error": "启动 bb-browser 失败: %s" % e}
    out = (p.stdout or "").strip()
    if not out:
        return {"error": "无输出", "stderr": (p.stderr or "")[:400]}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"error": "输出不是 JSON", "raw": out[:300]}
    # bb-browser 把 adapter 结果包在 {"result": {...}} 里
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        if isinstance(err, dict):
            return {"error": err.get("message") or json.dumps(err, ensure_ascii=False),
                    "hint": data.get("reportHint")}
        return {"error": str(err)}
    return data if isinstance(data, dict) else {"items": data}


def polite_pause(base=BASE_GAP):
    """模拟人手：基准间隔 + 随机抖动。base 不可为 0。"""
    gap = max(1, base) + random.uniform(*GAP_JITTER)
    time.sleep(gap)
    return gap


def daemon_status():
    """daemon 是否在跑。"""
    try:
        p = subprocess.run(_cmd("status"), capture_output=True, text=True,
                           timeout=20, encoding="utf-8", errors="replace")
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return "daemon status 失败: %s" % e

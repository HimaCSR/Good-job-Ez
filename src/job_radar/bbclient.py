"""bb-browser CLI 封装。所有外部进程调用集中在这里，便于限速与排查。"""

import time

try:
    from .logging_setup import get_logger
except ImportError:          # 脱离包单独导入时（单测）
    from logging_setup import get_logger

log = get_logger()

import json
import os
import random
import subprocess
import time

try:
    from . import browser_session
except ImportError:          # 脱离包单独导入时（单测）
    import browser_session

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


def _run_bb(*args, timeout=120):
    """跑一条 bb-browser 命令。返回 (returncode, stdout, stderr)。"""
    cmd = _cmd(*args)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "", "bb-browser 超时(%ss)" % timeout
    except OSError as exc:
        return -1, "", str(exc)


def run_site(site, *args, timeout=120):
    """跑一个 adapter，返回解析后的 JSON。失败返回 {"error": ...}。

    每次调用都记一条日志：站点、参数、耗时、返回大小、错误类型。
    凭证和 cookie 不进日志（logging_setup 会再打码一层）。

    **先确保浏览器在跑** —— 9222 上没浏览器时，bb-browser 会自己起一个
    （profile 持久化，登录态存磁盘）。不确保的话，用户第一次抓取会看到
    「环境异常」或薪资打码，却不知道是浏览器没起。
    """
    ready = browser_session.ensure_browser()
    if not ready.get("ok"):
        log.warning("浏览器没起来，adapter 可能失败: %s", ready.get("detail"))
        return {"error": "招聘站浏览器没起来：%s" % ready.get("detail")}

    cmd = _cmd("site", site, *args, "--json")
    started = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        log.warning("adapter 超时 site=%s args=%s timeout=%ss", site, list(args), timeout)
        return {"error": "bb-browser 超时(%ss)" % timeout}
    except FileNotFoundError:
        log.error("找不到 bash 或 bb.sh: %s", BB_SH)
        return {"error": "找不到 bash 或 bb.sh: %s" % BB_SH}
    except OSError as e:
        log.error("启动 bb-browser 失败: %s", e)
        return {"error": "启动 bb-browser 失败: %s" % e}
    out = (p.stdout or "").strip()
    elapsed = time.time() - started
    if not out:
        log.warning("adapter 无输出 site=%s elapsed=%.1fs stderr=%s",
                    site, elapsed, (p.stderr or "")[:200])
        return {"error": "无输出", "stderr": (p.stderr or "")[:400]}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        log.warning("adapter 输出不是 JSON site=%s elapsed=%.1fs raw=%s",
                    site, elapsed, out[:200])
        return {"error": "输出不是 JSON", "raw": out[:300]}
    # bb-browser 把 adapter 结果包在 {"result": {...}} 里
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        if isinstance(err, dict):
            msg = err.get("message") or json.dumps(err, ensure_ascii=False)
        else:
            msg = str(err)
        log.warning("adapter 返回错误 site=%s elapsed=%.1fs err=%s",
                    site, elapsed, msg[:200])
        return {"error": msg, "hint": data.get("reportHint")}
    count = len(data.get("jobs") or []) if isinstance(data, dict) else 0
    log.info("adapter 成功 site=%s elapsed=%.1fs jobs=%d bytes=%d",
             site, elapsed, count, len(out))
    return data if isinstance(data, dict) else {"items": data}


# BOSS 的搜索页 —— adapter 必须在**这个页面的上下文里**跑
# （BOSS 的 joblist API 要靠页面里的 anti-content token 才不被风控）
BOSS_SEARCH_URL = "https://www.zhipin.com/web/geek/jobs"


def ensure_boss_context(city_code="101040100", timeout=120):
    """确保浏览器里有一个 BOSS 搜索页，并且已加载完。

    返回 {'ok': bool, 'tab': str, 'detail': str}

    ## 为什么需要这一步

    BOSS 的 `joblist.json` API **必须在 zhipin 页面上下文里**发出去 ——
    它要靠页面里的 anti-content token。社区版 adapter 直接 fetch 会
    `Daemon request timed out`。

    实测（2026-10-29）：
    - 没有 BOSS 页面 → `site boss/search` **超时**
    - 先 `open` 一个 BOSS 搜索页 → **同一个命令立刻正常**，返回 300 个岗位

    所以流程是：**先 open 一次，之后 site 命令会复用那个 tab**。

    ## 为什么不用 `site` 命令自己开 tab

    `bb-browser site` 没有 `--tab` 选项，它自己开的 tab **不是 zhipin 域名** →
    拿不到 token → 超时。所以必须我们自己 open。

    ## 幂等

    已经有 zhipin tab 就直接复用，不重复开（避免开一堆 tab）。
    """
    ready = browser_session.ensure_browser()
    if not ready.get("ok"):
        return {"ok": False, "detail": ready.get("detail")}

    # ① 先看有没有现成的 zhipin tab
    tabs = _run_bb_json("tab", "list")

    existing = ""
    for t in (tabs.get("tabs") or []):
        url = t.get("url") or ""
        if "zhipin.com" in url:
            existing = t.get("tab") or ""
            break
    if existing:
        log.info("复用已有 BOSS tab=%s", existing)
        return {"ok": True, "tab": existing, "detail": "复用已有 BOSS 页面"}

    # ② 没有就 open 一个
    url = "%s?city=%s" % (BOSS_SEARCH_URL, city_code)
    code, out, err = _run_bb("open", url, timeout=timeout)
    text = (out or "").strip()
    if code != 0:
        return {"ok": False,
                "detail": (err or text or "打开 BOSS 页面失败").strip()[:200]}
    tab = ""
    for line in text.splitlines():
        if line.lower().startswith("tab:"):
            tab = line.split(":", 1)[1].strip()
            break

    # ③ 等页面加载完 —— 太快就 open 的话，adapter 跑的时候页面还没 ready
    time.sleep(4)
    log.info("已打开 BOSS 页面 tab=%s url=%s", tab, url)
    return {"ok": True, "tab": tab, "detail": "已打开 BOSS 页面"}


def _run_bb_json(*args, timeout=60):
    """跑 bb-browser 并解析 JSON 输出（失败返回 {}）。"""
    code, out, err = _run_bb(*args, timeout=timeout)
    text = (out or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    return data if isinstance(data, dict) else {}


def polite_pause(base=BASE_GAP):
    """模拟人手：基准间隔 + 随机抖动。base 不可为 0。"""
    gap = max(1, base) + random.uniform(*GAP_JITTER)
    log.debug("限速停顿 %.1fs", gap)
    time.sleep(gap)
    return gap


def daemon_status():
    """daemon 是否在跑。"""
    try:
        p = subprocess.run(_cmd("status"), capture_output=True, text=True,
                           timeout=20, encoding="utf-8", errors="replace")
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        log.warning("daemon status 失败: %s", e)
        return "daemon status 失败: %s" % e


def fetch_detail(site, job_id, timeout=90):
    """抓一个岗位的详情页（拿到完整 JD）。

    列表页不返回 JD —— 描述、要求都在详情页里。
    简历匹配优化需要 JD，所以按需抓一次。

    返回统一词表的一份岗位；失败返回 {"error": ...}。
    """
    if site == "zhaopin":
        data = run_site("zhaopin/detail", job_id, timeout=timeout)
    elif site == "boss":
        data = run_site("boss/detail", job_id, timeout=timeout)
    else:
        return {"error": "未知站点: %s" % site}
    if "error" in data:
        return data
    # detail adapter 返回的就是一份岗位
    if data.get("description") or data.get("title"):
        log.info("抓到详情 site=%s job=%s JD=%d字",
                 site, job_id, len(data.get("description") or ""))
        return data
    return {"error": "详情页没返回内容"}

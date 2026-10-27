"""招聘站浏览器与登录态管理。

## 为什么单独一个模块

招聘站的登录态（智联 `at`/`rt`、BOSS `zp_at`）**只在浏览器里**。
插件要读岗位详情、要投递，都得通过一个「已登录的浏览器」。

问题是：**插件不能替用户登录**（不碰密码、不碰验证码），
所以必须给用户一个「登录一下」的地方 —— 而这个浏览器得是**持久**的，
否则每次都要重登。

## 用哪个浏览器

**用 bb-browser 自己起的那个浏览器**，profile 在
`~/.bb-browser/browser/user-data`（Windows: `%USERPROFILE%\\.bb-browser\\browser\\user-data`）。

它满足三个条件（都实测过）：

1. **会自己起** —— 9222 不通就起一个带 `--remote-debugging-port` 的 Chrome
2. **有可见窗口** —— 用户能手动在里面登录（不是 headless）
3. **持久化** —— cookie 存在磁盘上，浏览器完全重启后一个不少

**不用用户日常那个 Chrome**：
- 日常 Chrome 默认不开调试端口，开了 Chrome 会弹「远程调试」警告
- 接管用户的日常浏览器太重（用户在看别的 tab）
- 登录态各存各的反而清楚

## 所以流程是

    用户点设置页的「打开招聘网站登录」
      → 调 bb.sh open <招聘网站>
      → 弹出一个专用 Chrome（可见窗口）
      → 用户在里面正常登录
      → cookie 持久化到该 profile
      → 之后抓取、投递都复用它

插件侧只需要：
- **确保浏览器在跑**（抓取前探测 9222，不通就触发 bb-browser 起）
- **检查登录态**（读 cookie，有 `zp_at`/`at`/`rt` 就算登录了）
- **告诉用户该怎么登录**（给出可点击的链接）

## 通用性

**不硬编码任何本机路径**：
- Chrome 可执行文件：从候选列表找，找不到就用 bb-browser 自己那套
- profile 目录：bb-browser 管的，插件不碰
- 端口：默认 9222，可用环境变量 `JOB_RADAR_CDP_PORT` 覆盖
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

try:
    from .logging_setup import get_logger
except ImportError:          # 脱离包单独导入时（单测）
    from logging_setup import get_logger

log = get_logger()

# CDP 端口 —— 和 bb-browser 的 BB_BROWSER_CDP_URL 一致
CDP_PORT = int(os.environ.get("JOB_RADAR_CDP_PORT", "9222"))
CDP_HOST = "127.0.0.1"

# 各招聘站的登录入口 —— 设置页拿去做「打开登录」
LOGIN_URLS = {
    "zhaopin": "https://www.zhaopin.com/",
    "boss": "https://www.zhipin.com/web/geek/job",
    "huibo": "https://www.jobcn.com/",
}

# 各站判定「已登录」的关键 cookie
SITE_COOKIE_MARKERS = {
    "zhaopin": ("at", "rt"),
    "boss": ("zp_at",),
}

BB_SH = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "tools",
                     "bb-browser", "bb.sh")

# 起浏览器后等多久
START_TIMEOUT = 25.0
POLL_INTERVAL = 0.5


# ── CDP 探测 ────────────────────────────────────────────────────────────────

def cdp_url():
    return "http://%s:%d" % (CDP_HOST, CDP_PORT)


def cdp_alive(timeout=2.0):
    """9222 上的 CDP 是否活着。"""
    try:
        req = urllib.request.Request(cdp_url() + "/json/version",
                                     headers={"User-Agent": "job-radar"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _bash():
    """找可用的 bash（Windows 上 .sh 要走 bash）。"""
    for cand in (r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files\Git\usr\bin\bash.exe",
                 r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.exists(cand):
            return cand
    return "bash"


def _run_bb(*args, timeout=120):
    """跑一条 bb-browser 命令。返回 (returncode, stdout, stderr)。"""
    cmd = [_bash(), BB_SH, *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "", "bb-browser 超时(%ss)" % timeout
    except OSError as exc:
        return -1, "", str(exc)


def ensure_browser():
    """确保 9222 上有个浏览器在跑。

    **不自己指定 profile** —— bb-browser 有一套自己的默认逻辑：
    9222 不通就起一个带调试端口的 Chrome，profile 用它自己管的
    （持久化，cookie 存磁盘）。我们只要保证它起来。

    **用 `open` 触发，不用 `status`** —— `status` 只查询状态，
    不会触发启动（实测：daemon 在跑但 Chrome 没了时，
    `bb.sh status` 只报「Chrome 未连接」，什么都不做）。
    `open` 才会走端口发现 → 起浏览器。

    返回 {'ok': bool, 'action': str, 'detail': str}
    """
    if cdp_alive():
        log.debug("9222 已有浏览器在跑")
        return {"ok": True, "action": "none", "detail": "浏览器已在跑"}

    log.info("9222 没浏览器，触发 bb-browser 启动")
    code, out, err = _run_bb("open", "about:blank", timeout=120)
    if cdp_alive():
        log.info("浏览器已就绪 port=%d", CDP_PORT)
        return {"ok": True, "action": "started", "detail": "已拉起浏览器"}

    # 起来得慢一点 —— 再等等
    if wait_for_cdp(timeout=8):
        return {"ok": True, "action": "started", "detail": "已拉起浏览器"}

    detail = (err or out or "拉起浏览器失败").strip()
    return {"ok": False, "action": "failed",
            "detail": detail.splitlines()[-1][:200] if detail else "拉起浏览器失败"}


def wait_for_cdp(timeout=START_TIMEOUT):
    """等 9222 上的 CDP 活过来。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cdp_alive(timeout=1.5):
            return True
        time.sleep(POLL_INTERVAL)
    return False


# ── 打开登录页 ──────────────────────────────────────────────────────────────

def open_login(site):
    """在插件专用的浏览器里打开某招聘站的登录页。

    返回 {'ok': bool, 'tab': str, 'detail': str}

    **浏览器必须有可见窗口** —— 用户要手动登录。
    bb-browser 起的 Chrome 是有界面的（不是 headless），
    所以用户能直接在里面点。
    """
    url = LOGIN_URLS.get(site)
    if not url:
        return {"ok": False, "detail": "未知站点: %s" % site}

    # 先确保浏览器在跑
    ready = ensure_browser()
    if not ready["ok"]:
        return {"ok": False, "detail": ready["detail"]}

    code, out, err = _run_bb("open", url, timeout=120)
    text = (out or "").strip()
    if code != 0:
        return {"ok": False,
                "detail": (err or text or "打开失败").strip()[:200]}
    tab = ""
    for line in text.splitlines():
        if line.lower().startswith("tab:"):
            tab = line.split(":", 1)[1].strip()
            break
    log.info("已打开登录页 site=%s tab=%s", site, tab)
    return {"ok": True, "tab": tab, "url": url,
            "detail": "已打开 %s，在弹出的浏览器里登录即可" % url}


# ── 登录态检查 ──────────────────────────────────────────────────────────────

def read_cookies(cdp_port=None, timeout=30):
    """读 9222 上那个浏览器的 cookie。

    返回 [{name, domain, expires}]。**只在内存里，不落盘。**
    """
    port = cdp_port or CDP_PORT
    url = "http://%s:%d/json/version" % (CDP_HOST, port)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "job-radar"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            info = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("读 CDP 版本失败: %s", exc)
        return []

    ws_url = info.get("webSocketDebuggerUrl")
    if not ws_url:
        return []

    # 用浏览器级 API：Network.getAllCookies 在 browser target 上返回空，
    # 必须用 Storage.getCookies
    return _cookies_via_websocket(ws_url, timeout)


def _cookies_via_websocket(ws_url, timeout=30):
    """连 CDP WebSocket，用 Storage.getCookies 拿全部 cookie。

    **用 Node 跑**（Hermes 自带的 node 有 WebSocket；
    PATH 里的 node 可能是 14，没有）。
    脚本用完即删，不落盘。
    """
    node = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "tools",
                        "node-26.7.0-win32-x64", "node.exe")
    if not os.path.exists(node):
        log.warning("找不到 node，读不了 cookie")
        return []

    script = r"""
const ws = new WebSocket(process.argv[2]);
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise(r => ws.onopen = r);
const send = (method, params) => new Promise(res => {
  const i = ++id; pending.set(i, res);
  ws.send(JSON.stringify({id: i, method, params: params || {}})); });
const r = await send('Storage.getCookies', {});
const cookies = ((r.result && r.result.cookies) || []).map(c => ({
  name: c.name, domain: c.domain, expires: c.expires || 0 }));
console.log(JSON.stringify(cookies));
ws.close();
"""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".mjs")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        p = subprocess.run([node, path, ws_url], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        out = (p.stdout or "").strip()
        if not out:
            return []
        return json.loads(out)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        log.warning("读 cookie 失败: %s", exc)
        return []
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def login_status():
    """各站登录态体检。

    返回 {'sites': [{site, label, logged_in, detail}], 'cookie_count': int}
    """
    from . import login_check

    cookies = read_cookies()
    result = login_check.check_from_cookies(cookies)
    return {
        "sites": result["sites"],
        "summary": result["summary"],
        "cookie_count": len(cookies),
        "cdp_alive": cdp_alive(),
    }


def status():
    """整体状态 —— 设置页「平台接入」显示用。"""
    alive = cdp_alive()
    out = {
        "cdp_port": CDP_PORT,
        "cdp_alive": alive,
        "login_urls": LOGIN_URLS,
    }
    if alive:
        cookies = read_cookies()
        out["cookie_count"] = len(cookies)
        names = {c.get("name") for c in cookies}
        out["logged_in"] = {
            site: any(marker in names for marker in markers)
            for site, markers in SITE_COOKIE_MARKERS.items()
        }
    else:
        out["cookie_count"] = 0
        out["logged_in"] = {}
    return out

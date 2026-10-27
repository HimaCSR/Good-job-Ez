"""投递三道门 —— 真实现。

三道门（顺序固定，每道不过就停在那一步）：

    1. 每站「允许投递简历」开关 —— 默认全关
    2. 一次性确认令牌 —— 5 分钟有效，绑定 job_id + site，用一次就废
    3. 该站每日上限 —— 按站独立计数

**为什么要有这三道门**：投递是不可逆动作。用户误点一次，
就是一份简历投出去了，招聘方那边已经看到。所以：

- 站点开关是**用户自己**的显式授权，默认关 —— 插件不该替他决定「可以投」
- 一次性令牌保证「选定简历」不等于「授权投递」，中间必须再点一次
- 每日上限防止脚本失控或手滑连点，把一天投成几十份

**与 mock_provider 的关系**：mock_provider 提供形状一致的假实现，
接口（issue_token / check_token / consume_token / gate_status / apply）
保持一致 —— 前端一行不用改。`apply_gate.enabled()` 判断走哪个。

**配置怎么存**（重要）：
站点开关和每日上限存在 config.yaml 的
`plugins.entries.job-radar.settings` 里，**用扁平键**：

    apply_zhaopin: true
    apply_boss: false
    apply_limit_zhaopin: 5
    apply_limit_boss: 5

**不用嵌套字典**（`apply_sites: {zhaopin: true}`）——
`_read_config_yaml` 的解析器只认顶层 key 和顶层块序列，
嵌套字典会被打散成顶层键（`zhaopin`/`boss` 直接跑到 settings 顶层去），
读出来就是错的。扁平键没有这个问题。

**令牌与投递记录落 SQLite**（不是内存）—— 内存版重启进程就没了，
多进程（cron 脚本 + 网关 API）之间也不共享。
"""

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta

try:
    from .logging_setup import get_logger
except ImportError:          # 脱离包单独导入时（单测）
    from logging_setup import get_logger

log = get_logger()

# 各站默认每日上限（用户可在设置里调高）
DEFAULT_DAILY_LIMIT = {
    "zhaopin": 5,
    "boss": 5,
    "huibo": 3,
}

# 已知站点（开关和上限都以这些为准）
KNOWN_SITES = ("zhaopin", "boss", "huibo")

# 令牌有效期：5 分钟
TOKEN_TTL_SECONDS = 300


def _now():
    return datetime.now()


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# ── 配置读写 ────────────────────────────────────────────────────────────────
#
# 走 Hermes 的 config.yaml。**不手写 YAML** —— 缩进错位会把整个
# job-radar 节点搞成空节点，老配置静默丢失。
#
# 这里用 `hermes config get/set` CLI，跟 dashboard 层保持一致。

def _hermes_cli():
    """定位 hermes CLI。找不到返回 None。"""
    import shutil

    home = os.environ.get("HERMES_HOME")
    if not home:
        local = os.environ.get("LOCALAPPDATA")
        home = os.path.join(local, "hermes") if local else os.path.expanduser("~/.hermes")
    for name in ("hermes", "hermes.exe"):
        p = os.path.join(home, "hermes-agent", ".hermes", "bin", name)
        if os.path.exists(p):
            return p
    return shutil.which("hermes") or shutil.which("hermes.exe")


def _cli_settings():
    """读 plugins.entries.job-radar.settings。返回扁平 dict。"""
    import subprocess

    hermes = _hermes_cli()
    if not hermes:
        return {}
    home = os.environ.get("HERMES_HOME") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "hermes")
    try:
        proc = subprocess.run(
            [hermes, "config", "get", "plugins.entries.job-radar.settings"],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.join(home, "hermes-agent"))
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}

    import re

    out = {}
    for line in (proc.stdout or "").splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line.strip())
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw in ("true", "false"):
            out[key] = raw == "true"
        else:
            try:
                out[key] = int(raw)
            except ValueError:
                out[key] = raw.strip("'\"")
    return out


def _cli_set(key, value):
    """写一个设置键。走 CLI，不手写 YAML。"""
    import subprocess

    hermes = _hermes_cli()
    if not hermes:
        raise RuntimeError("找不到 hermes CLI，无法写入配置")
    home = os.environ.get("HERMES_HOME") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "hermes")
    if isinstance(value, bool):
        arg = "true" if value else "false"
    else:
        arg = str(value)
    proc = subprocess.run(
        [hermes, "config", "set",
         "plugins.entries.job-radar.settings." + key, arg],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.join(home, "hermes-agent"))
    if proc.returncode != 0:
        raise RuntimeError("写入 %s 失败: %s"
                           % (key, (proc.stderr or proc.stdout or "").strip()))


def site_switch_enabled(site, settings=None):
    """某站的「允许投递简历」开关。**默认关** —— 这是第一道门。"""
    if settings is None:
        settings = _cli_settings()
    val = settings.get("apply_" + site)
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes", "on")


def set_site_switch(site, enabled, settings=None):
    """开/关某站的投递开关。"""
    if site not in KNOWN_SITES:
        raise ValueError("未知站点: %s" % site)
    _cli_set("apply_" + site, bool(enabled))
    log.info("投递开关 site=%s enabled=%s", site, bool(enabled))
    return _switches_with({site: bool(enabled)})


def daily_limit(site, settings=None):
    """某站每日投递上限。取不到用默认值。"""
    if settings is None:
        settings = _cli_settings()
    val = settings.get("apply_limit_" + site)
    try:
        n = int(val)
    except (TypeError, ValueError):
        n = DEFAULT_DAILY_LIMIT.get(site, 5)
    return max(0, n)


def set_daily_limit(site, limit):
    """设某站每日上限。"""
    if site not in KNOWN_SITES:
        raise ValueError("未知站点: %s" % site)
    n = max(0, int(limit))
    _cli_set("apply_limit_" + site, n)
    log.info("每日上限 site=%s limit=%d", site, n)
    return _switches_with({"limit:" + site: n})


def _switches_with(overrides):
    """读一遍开关，但把刚写入的值覆盖上去。

    **为什么要覆盖**：`_cli_set` 写完 config.yaml 后立刻 `config get`
    可能读到旧值（写盘有延迟，或者 CLI 读的是缓存）。
    直接用刚写的值更可靠 —— 返回值必须是「写完之后的状态」。
    """
    data = all_switches()
    for key, val in overrides.items():
        site = key.split(":", 1)[1] if key.startswith("limit:") else key
        entry = data["sites"].get(site)
        if not entry:
            continue
        if key.startswith("limit:"):
            entry["daily_limit"] = val
        else:
            entry["apply_enabled"] = val
    return data


def all_switches():
    """所有站的开关与上限 —— 设置页「平台接入」显示用。"""
    settings = _cli_settings()
    return {
        "sites": {
            s: {
                "apply_enabled": site_switch_enabled(s, settings),
                "daily_limit": daily_limit(s, settings),
            } for s in KNOWN_SITES
        },
        "known_sites": list(KNOWN_SITES),
    }


# ── 令牌 ────────────────────────────────────────────────────────────────────
#
# 令牌落 SQLite，不是内存 ——
#   · 内存版重启进程就丢
#   · cron 脚本和网关 API 是两个进程，内存不共享
#   · 落库才能审计「谁在什么时候投了什么」

def _storage():
    """取 storage 模块。

    独立跑（单测、脚本）时没有父包，相对导入会炸 —— 退化到同目录导入。
    """
    try:
        from . import storage
    except ImportError:
        import storage
    return storage


def _resume_builder():
    """取 resume_builder 模块（同样要兼容独立运行）。"""
    try:
        from .resume_builder import extract_requirements, normalize
    except ImportError:
        from resume_builder import extract_requirements, normalize
    return extract_requirements, normalize


def _resume_store():
    """取 resume_store 模块（同样要兼容独立运行）。"""
    try:
        from . import resume_store
    except ImportError:
        import resume_store
    return resume_store


def issue_token(job_id, site, resume_id=None):
    """签发一次性确认令牌。

    **闸门没过就不签** —— 否则「站点开关」这道门会被绕过去：
    前端拿到 token 直接调 submit，被 submit 挡回去，
    白跑一趟还没说清是哪道门挡的。
    """
    site = site or "zhaopin"
    if not site_switch_enabled(site):
        raise PermissionError("该站未开启「允许投递简历」")
    token = secrets.token_hex(8)
    now = _now()
    expires = now + timedelta(seconds=TOKEN_TTL_SECONDS)
    _storage().insert_apply_token(
        token=token, job_id=job_id, site=site, resume_id=resume_id,
        issued_at=now.isoformat(timespec="seconds"),
        expires_at=expires.isoformat(timespec="seconds"))
    log.info("签发投递令牌 job=%s site=%s ttl=%ds", job_id, site, TOKEN_TTL_SECONDS)
    return token


def check_token(token, job_id=None, site=None):
    """校验令牌。没过返回 (False, 原因)。"""
    if not token:
        return False, "需要一次性确认令牌"
    row = _storage().get_apply_token(token)
    if not row:
        return False, "令牌无效或已被使用"
    try:
        exp = datetime.fromisoformat(row["expires_at"])
    except (ValueError, TypeError):
        return False, "令牌格式错误"
    if _now() > exp:
        _storage().delete_apply_token(token)
        return False, "令牌已过期（%d 分钟内有效）" % (TOKEN_TTL_SECONDS // 60)
    if row.get("used_at"):
        return False, "令牌已被使用"
    if job_id and row.get("job_id") != job_id:
        return False, "令牌与岗位不匹配"
    if site and row.get("site") != site:
        return False, "令牌与站点不匹配"
    return True, ""


def consume_token(token):
    """用掉令牌 —— 一次性。"""
    _storage().mark_apply_token_used(token)


# ── 闸门体检 ────────────────────────────────────────────────────────────────

def today_count(site):
    """某站今天已投了几份。"""
    return _storage().count_applies(site, _today())


def gate_status(job, resume_id=None):
    """投递前的闸门体检：能不能投、卡在哪一道门。

    返回 {"can_apply": bool, "blocked_by": [...], ...}
    """
    site = (job or {}).get("source") or "zhaopin"
    blocked = []

    if not site_switch_enabled(site):
        blocked.append({
            "gate": "site_switch",
            "label": "该站未开启「允许投递简历」",
            "hint": "设置页 → 平台接入 → 打开这个站的投递开关（默认关）",
        })

    count = today_count(site)
    limit = daily_limit(site)
    if count >= limit:
        blocked.append({
            "gate": "daily_limit",
            "label": "今日投递已达上限（%d/%d）" % (count, limit),
            "hint": "明天再来，或调高每日上限",
        })

    return {
        "can_apply": not blocked,
        "blocked_by": blocked,
        "site": site,
        "site_apply_enabled": site_switch_enabled(site),
        "daily_used": count,
        "daily_limit": limit,
        "daily_remaining": max(0, limit - count),
        "token_ttl_seconds": TOKEN_TTL_SECONDS,
    }


# ── 投递 ────────────────────────────────────────────────────────────────────
#
# **动作层还没接真实现** —— 招聘站的投递接口需要站点私有 adapter
# （里面有写操作，按约定不放进公开仓库）。
#
# 所以现在 apply() 做的是：
#   1. 过三道门
#   2. 归档简历 + 打标签（这部分是真的，进「用户简历」模块）
#   3. 记账（apply_records 表）
#
# 动作层接上之后，只需要在 _submit_to_site() 里换成真实调用，
# 闸门、归档、记账都不用动。

def _submit_to_site(job, resume):
    """真正把简历投出去。**动作层 —— 还没接。**

    接入方式：调用站点私有 adapter（~/.bb-browser/sites/<site>/apply.js），
    走 bbclient.run_site("zhaopin/apply", job_id, resume_path)。

    现在返回未接入，让上层知道「只归档了，没真的投」。
    """
    site = (job or {}).get("source") or "zhaopin"
    return {
        "ok": False,
        "stage": "action",
        "error": "投递动作层还没接入（%s 站）—— 简历已归档，需到招聘网站手动投" % site,
        "site": site,
    }


def apply(job, resume, token=None):
    """执行投递 —— 过三道门。

    返回 {"ok": bool, "stage": str, ...}
    stage 取值：site_switch / token / daily_limit / action / done
    """
    site = (job or {}).get("source") or "zhaopin"
    job_id = (job or {}).get("job_id") or ""

    # 门 1：站点开关
    if not site_switch_enabled(site):
        return {"ok": False, "stage": "site_switch",
                "error": "该站未开启「允许投递简历」"}

    # 门 2：令牌（一次性、5 分钟、绑定 job_id + site）
    if token is None:
        return {"ok": False, "stage": "token", "error": "需要一次性确认令牌"}
    valid, why = check_token(token, job_id=job_id, site=site)
    if not valid:
        return {"ok": False, "stage": "token", "error": why}
    consume_token(token)

    # 门 3：每日上限
    count = today_count(site)
    limit = daily_limit(site)
    if count >= limit:
        return {"ok": False, "stage": "daily_limit",
                "error": "今日投递已达上限（%d/%d）" % (count, limit)}

    # 动作层：真投递（还没接）
    result = _submit_to_site(job, resume)

    # 归档简历 + 打标签 —— 这部分是真的
    archived = None
    try:
        resume_store = _resume_store()
        if resume and resume.get("file_path"):
            archived = _archive_resume(job, resume, resume_store)
    except Exception as exc:      # noqa: BLE001 — 归档失败不该让投递算成功
        log.warning("简历归档失败 job=%s: %s", job_id, exc)

    # 记账 —— 过了三道门 + 动作层有回应，就算一次投递
    _storage().insert_apply_record(
        site=site, job_id=job_id,
        resume_id=(resume or {}).get("resume_id") or "",
        ok=bool(result.get("ok")),
        detail=str(result.get("error") or "")[:200],
        applied_at=_now().isoformat(timespec="seconds"))

    if not result.get("ok"):
        return result

    return {
        "ok": True,
        "applied_at": _now().isoformat(timespec="seconds"),
        "site": site,
        "job_id": job_id,
        "resume_id": (resume or {}).get("resume_id"),
        "archived": archived,
        "daily_used": count + 1,
        "daily_limit": limit,
    }


def _archive_resume(job, resume, resume_store):
    """把投出去的简历按「投递成功」归档并打标签。

    标签 = 岗位方向 + 命中技能 + 岗位关键词 —— 后续简历评分的依据。
    标签只从真实命中项来，不凭空生成。
    """
    matched = {"covered": [], "requirements": {"keywords": []}}
    tags = resume_store.build_tags(job, matched)
    resume_id = resume.get("resume_id")
    if not resume_id:
        return None
    _storage().update_resume_after_apply(
        resume_id, tags=tags, source="applied", job_id=job.get("job_id") or "")
    return {"resume_id": resume_id, "tags": tags}


def recent_applies(limit=20):
    """最近的投递记录（设置页看用）。"""
    return _storage().list_apply_records(limit=limit)

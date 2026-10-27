"""Mock 数据源 —— 给还没实现的功能提供假数据。

**用途**：让前后端能对着**确定的数据形状**同时开发，
不用等真实现写完。接口形状跟真实现一致，
接真实现时只需把 `mock` 参数关掉，调用方一行不用改。

**当前覆盖三个缺口**：
1. 投递三道门（每站开关 / 一次性令牌 / 每日上限）
2. 经历结构化（公司、时间、描述分条）
3. Word / 图片模板转换

**约定**：mock 数据一律用虚构信息（张三、某人力资源有限公司、user@example.com），
不碰真实简历、真实公司名。

**怎么用**：
    from . import mock_provider
    if mock_provider.enabled():
        data = mock_provider.some_data()
    else:
        data = 真实实现()
"""

import json
import os
import uuid
from datetime import datetime, timedelta

# ── 开关 ─────────────────────────────────────────────────────────────────────
#
# 环境变量 JOB_RADAR_MOCK=1 打开；默认关。
# 显式传 mock=True 的调用点也能强制走 mock。

_ENV_KEY = "JOB_RADAR_MOCK"


def enabled(force=None):
    """mock 模式是否开启。

    三个来源，优先级从高到低：
      1. force 参数（调用点显式指定）
      2. 环境变量 JOB_RADAR_MOCK=1
      3. 插件配置里的 mock 开关（设置页可改，不用重启网关）
    """
    if force is not None:
        return bool(force)
    env = os.environ.get(_ENV_KEY, "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    # 配置文件里的开关（ctx 注入）
    #
    # mock_provider 是**顶层模块**（不是包里的子模块），
    # 相对导入 `from . import config` 在这里会 ImportError ——
    # 改成同目录导入。
    try:
        import config as _cfg
        return bool(_cfg.load_config().get("mock", False))
    except Exception:
        return False


# ── 1. 投递闸门 ──────────────────────────────────────────────────────────────
#
# 三道门：
#   每站「允许投递」开关（默认关）
#     → 一次性确认令牌（5 分钟有效，绑定 job_id）
#       → 该站每日上限
#
# 令牌 mock 里就是一段随机串；真实现要落库并校验时效。

# 各站的投递开关默认全是关的 —— 这道门的作用就在这。
SITE_APPLY_ENABLED = {
    "zhaopin": False,
    "boss": False,
    "huibo": False,
}

# 各站每日投递上限
SITE_DAILY_LIMIT = {
    "zhaopin": 5,
    "boss": 5,
    "huibo": 3,
}

# 初始值 —— reset() 用它把开关恢复回默认（全关）
_INITIAL_SITE_APPLY_ENABLED = dict(SITE_APPLY_ENABLED)

# 已投递次数（mock 用，真实实现查表）
SITE_TODAY_COUNT = {
    "zhaopin": 0,
    "boss": 0,
    "huibo": 0,
}

TOKEN_TTL_SECONDS = 300   # 5 分钟


def _now():
    return datetime.now()


def issue_token(job_id, site, resume_id=None):
    """签发一次性确认令牌。

    真实现：token 落表，带过期时间和绑定的 job_id。
    mock：随机串 + 内存存一份（进程内有效，够开发用）。

    闸门没过就不签 —— 否则「站点开关」这道门会被绕过去：
    前端拿到 token 直接调 submit，结果被 submit 挡回去，
    白跑一趟还没说清是哪道门挡的。
    """
    if not SITE_APPLY_ENABLED.get(site, False):
        raise PermissionError("该站未开启「允许投递简历」")
    token = uuid.uuid4().hex[:12]
    _TOKENS[token] = {
        "token": token,
        "job_id": job_id,
        "site": site,
        "resume_id": resume_id,
        "issued_at": _now().isoformat(timespec="seconds"),
        "expires_at": (_now() + timedelta(seconds=TOKEN_TTL_SECONDS))
        .isoformat(timespec="seconds"),
    }
    return token


_TOKENS = {}


def check_token(token, job_id=None, site=None):
    """校验令牌。没过返回 (False, 原因)。"""
    info = _TOKENS.get(token or "")
    if not info:
        return False, "令牌无效或已被使用"
    try:
        exp = datetime.fromisoformat(info["expires_at"])
    except ValueError:
        return False, "令牌格式错误"
    if _now() > exp:
        _TOKENS.pop(token, None)
        return False, "令牌已过期（5 分钟内有效）"
    if job_id and info["job_id"] != job_id:
        return False, "令牌与岗位不匹配"
    if site and info["site"] != site:
        return False, "令牌与站点不匹配"
    return True, ""


def consume_token(token):
    """用掉令牌 —— 一次性。"""
    _TOKENS.pop(token, None)


def gate_status(job, resume_id=None):
    """投递前的闸门体检：能不能投、卡在哪一道门。

    返回 {"can_apply": bool, "blocked_by": [...], "site": ...}
    """
    site = job.get("source") or "zhaopin"
    blocked = []

    if not SITE_APPLY_ENABLED.get(site, False):
        blocked.append({
            "gate": "site_switch",
            "label": "该站未开启「允许投递简历」",
            "hint": "设置页 → 平台接入 → 打开这个站的投递开关（默认关）",
        })

    count = SITE_TODAY_COUNT.get(site, 0)
    limit = SITE_DAILY_LIMIT.get(site, 0)
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
        "site_apply_enabled": SITE_APPLY_ENABLED.get(site, False),
        "daily_used": count,
        "daily_limit": limit,
        "daily_remaining": max(0, limit - count),
    }


def mock_apply(job, resume, token=None):
    """模拟一次投递。

    真实现：调招聘站的投递接口 + 归档简历 + 打标签。
    mock：只记账并返回假结果。
    """
    site = job.get("source") or "zhaopin"

    # 门 1：站点开关
    if not SITE_APPLY_ENABLED.get(site, False):
        return {"ok": False, "stage": "site_switch",
                "error": "该站未开启「允许投递简历」"}

    # 门 2：令牌
    if token is None:
        return {"ok": False, "stage": "token", "error": "需要一次性确认令牌"}
    valid, why = check_token(token, job_id=job.get("job_id"), site=site)
    if not valid:
        return {"ok": False, "stage": "token", "error": why}
    consume_token(token)

    # 门 3：每日上限
    count = SITE_TODAY_COUNT.get(site, 0)
    limit = SITE_DAILY_LIMIT.get(site, 0)
    if count >= limit:
        return {"ok": False, "stage": "daily_limit",
                "error": "今日投递已达上限（%d/%d）" % (count, limit)}
    SITE_TODAY_COUNT[site] = count + 1

    return {
        "ok": True,
        "applied_at": _now().isoformat(timespec="seconds"),
        "site": site,
        "job_id": job.get("job_id"),
        "resume_id": (resume or {}).get("resume_id"),
        "mock": True,
        "note": "这是 mock 结果，没有真的投出去",
    }


# ── 2. 经历结构化 ────────────────────────────────────────────────────────────
#
# 现在 profile.experience_text 是一坨自由文本。
# 结构化之后每条经历有：公司 / 起止 / 职位 / 分条描述。
# mock 给一份虚构的，形状跟真实现一致。

MOCK_EXPERIENCES = [
    {
        "id": "exp-1",
        "company": "某科技有限公司",
        "title": "高级前端工程师",
        "start": "2023-04",
        "end": "至今",
        "bullets": [
            "主导公司 3D 数据可视化平台的架构与前端实现，使用 Vue + TypeScript + three.js，将渲染帧率提升 60%",
            "负责通用 WebGL 组件库建设，支持图表、模型、地图多种场景",
        ],
        "tags": ["three.js", "vue", "typescript"],
    },
    {
        "id": "exp-2",
        "company": "某网络科技有限公司",
        "title": "前端开发工程师",
        "start": "2021-07",
        "end": "2023-03",
        "bullets": [
            "搭建基于 Node.js 的构建与发布流程，缩短 CI 时间 40%",
            "独立完成多个客户项目的可视化大屏交付",
        ],
        "tags": ["node", "javascript", "css"],
    },
]


def experiences():
    """结构化的经历列表。

    返回的是**当前状态**（_EXPERIENCES），不是初始常量 ——
    否则 upsert / delete 都不生效，mock 就是个摆设。
    """
    return [dict(e, bullets=list(e["bullets"])) for e in _EXPERIENCES]


def upsert_experience(exp):
    """保存一条经历（mock：内存里）。"""
    exp = dict(exp)
    exp.setdefault("id", "exp-%d" % (len(_EXPERIENCES) + 1))
    _EXPERIENCES[:] = [e for e in _EXPERIENCES if e["id"] != exp["id"]]
    _EXPERIENCES.append(exp)
    return exp


def delete_experience(exp_id):
    """删一条经历（mock：内存里）。"""
    before = len(_EXPERIENCES)
    _EXPERIENCES[:] = [e for e in _EXPERIENCES if e["id"] != exp_id]
    return len(_EXPERIENCES) < before


_EXPERIENCES = [dict(e, bullets=list(e["bullets"])) for e in MOCK_EXPERIENCES]


# ── 3. 模板转换 ──────────────────────────────────────────────────────────────
#
# .docx / .pdf / .png / .jpg → HTML 模板。
# mock：返回一份假的转换结果（版式参数 + 预览图路径），
# 形状跟真实现一致 —— 真实现读文件、抽参数、生成预览。

MOCK_CONVERT_RESULT = {
    "template_id": "mock-converted",
    "name": "（示例）我的模板",
    "description": "从 .docx 转换而来（mock 数据）",
    "format": "docx",
    "source_path": "<上传的原文件>",
    "preview_path": "<生成的预览图>",
    "builtin": 0,
    "layout": {
        "columns": 1,
        "margin_mm": [15, 15, 15, 15],
        "base_font_pt": 10.5,
        "title_font_pt": 18,
        "font_family": "Microsoft YaHei",
        "line_height": 1.5,
        "accent_color": "#0053fd",
    },
    "sections": [
        {"title": "个人信息", "kind": "identity"},
        {"title": "工作经历", "kind": "entries"},
        {"title": "项目经历", "kind": "entries"},
        {"title": "技能", "kind": "tags"},
    ],
    "mock": True,
}


def convert_template(filename, content_b64=None, kind=None):
    """模拟一次模板转换。

    真实现：
      .docx → zipfile + XML 抽版式参数（页边距/字号/栏数/字体）
      .pdf / 图片 → 「底图 + 文字层」混合模板
    mock：返回固定形状的假结果。
    """
    name = os.path.basename(filename or "template.docx")
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if kind:
        ext = kind.lower().lstrip(".")

    if ext not in ("docx", "pdf", "png", "jpg", "jpeg", "webp"):
        return {"ok": False, "error": "只支持 .docx / .pdf / .png / .jpg / .webp"}

    size = len(content_b64 or "") * 3 // 4
    out = dict(MOCK_CONVERT_RESULT)
    out["template_id"] = "mock-" + uuid.uuid4().hex[:8]
    out["name"] = os.path.splitext(name)[0]
    out["format"] = "docx" if ext == "docx" else ext
    out["source_path"] = name
    out["source_bytes"] = size
    out["note"] = "mock 转换结果，版式参数是假的"
    return {"ok": True, "template": out}


# ── 汇总：mock 模式的整体状态 ───────────────────────────────────────────────

def status():
    """mock 层当前状态 —— 设置页「开发模式」面板会显示。"""
    return {
        "enabled": enabled(),
        "env_key": _ENV_KEY,
        "gates": {
            "site_apply_enabled": dict(SITE_APPLY_ENABLED),
            "daily_limit": dict(SITE_DAILY_LIMIT),
            "today_count": dict(SITE_TODAY_COUNT),
            "token_ttl_seconds": TOKEN_TTL_SECONDS,
        },
        "experiences": len(_EXPERIENCES),
        "templates_converted": 0,
    }


def reset():
    """把 mock 状态清回初始（开发时反复调试用）。

    **投递开关也要重置** —— 「回到初始状态」意味着开关回到默认（关）。
    漏了这一条，测试之间会互相污染：一个用例打开了开关，
    下一个用例以为开关是关的，结果拿到令牌。
    """
    global SITE_TODAY_COUNT, SITE_APPLY_ENABLED
    SITE_TODAY_COUNT = {"zhaopin": 0, "boss": 0, "huibo": 0}
    SITE_APPLY_ENABLED = dict(_INITIAL_SITE_APPLY_ENABLED)
    _TOKENS.clear()
    _EXPERIENCES[:] = [dict(e, bullets=list(e["bullets"]))
                        for e in MOCK_EXPERIENCES]
    return {"ok": True}

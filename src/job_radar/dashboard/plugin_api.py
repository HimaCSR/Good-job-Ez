"""job-radar 设置页后端 API，挂载在 /api/plugins/job-radar/。

前端（desktop/plugin.js）用 ctx.rest('/path') 调这里。
所有接口都返回 JSON，错误走 HTTPException。

设计要点：
- 配置读写走 config.yaml 的 plugins.entries.job-radar.settings
- 画像读写走 profile.yaml（插件目录），但**不写进插件目录**的硬规则不适用于
  profile.yaml —— 它是「用户手写的配置」而非「运行时状态」，用户明确要求
  能通过设置页编辑。真正的运行时状态（jobs.db / reports/）仍在 plugin-data。
- 路径解析全部走 get_hermes_home()，不硬编码。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter()


# ── 兄弟模块加载 ──────────────────────────────────────────────────────────────
#
# Hermes 把 dashboard/plugin_api.py 当独立模块加载
# （module name = hermes_dashboard_plugin_<name>），没有父包，
# 所以 `from . import storage` 一定失败。
#
# 解法：把插件根目录注册成一个真包 `job_radar`，兄弟模块作为它的子模块
# 按依赖顺序加载。这样它们之间的相对导入（`from . import bbclient, storage`）
# 天然可用 —— 和插件以 agent 插件方式运行时的结构一致。

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKG_NAME = "job_radar"
_SIBLINGS = (
    "config", "schemas", "matcher", "storage", "bbclient",
    "report", "push", "login_check", "browser_cookies", "tools",
    "logging_setup", "resume_template", "resume_builder", "resume_store",
    "mock_provider", "apply_gate", "browser_session",
)


def _load_siblings() -> Dict[str, Any]:
    """把插件根目录注册成 `job_radar` 包并按依赖顺序加载兄弟模块。"""
    import importlib.util
    import types

    if _PKG_NAME not in sys.modules:
        pkg = types.ModuleType(_PKG_NAME)
        pkg.__path__ = [_PLUGIN_ROOT]
        pkg.__package__ = _PKG_NAME
        sys.modules[_PKG_NAME] = pkg

    loaded: Dict[str, Any] = {}
    for name in _SIBLINGS:
        path = os.path.join(_PLUGIN_ROOT, name + ".py")
        if not os.path.exists(path):
            continue
        mod_name = _PKG_NAME + "." + name
        if mod_name in sys.modules:
            loaded[name] = sys.modules[mod_name]
            continue
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            loaded[name] = mod
        except Exception as exc:      # noqa: BLE001 — 一个模块坏掉不该拖垮整个 API
            log.warning("job-radar 模块 %s 加载失败: %s", name, exc)
            continue
    return loaded


_SIBLING_MODULES = _load_siblings()


def _sibling(name: str):
    """取一个兄弟模块；取不到就抛，避免静默返回 None。"""
    mod = _SIBLING_MODULES.get(name)
    if mod is None:
        raise ImportError(
            f"job-radar 兄弟模块 {name}.py 加载失败（{_PLUGIN_ROOT}）")
    return mod

PLUGIN_ID = "job-radar"


# ── 路径解析 ────────────────────────────────────────────────────────────────

def _hermes_home() -> str:
    """解析 Hermes 主目录。优先环境变量，其次平台默认。"""
    home = os.environ.get("HERMES_HOME")
    if home:
        return home
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return os.path.join(local, "hermes")
    return os.path.expanduser("~/.hermes")


def _plugin_dir() -> str:
    """插件自己的目录（profile.yaml 在这）。"""
    return os.path.join(_hermes_home(), "plugins", PLUGIN_ID)


def _profile_path() -> str:
    """个人画像路径。

    放在 <plugin-data>/job-radar/ 下，不在插件目录里 ——
    插件目录开发时是指向 git 仓库的链接，画像是私有数据。
    """
    try:
        from plugins.plugin_storage import plugin_data_dir
        base = plugin_data_dir("job-radar")
    except ImportError:
        base = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "hermes",
            "plugin-data", "job-radar")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "profile.yaml")


# ── 配置读写（config.yaml 的 plugins.entries.job-radar.settings）────────────

def _read_config_yaml() -> Dict[str, Any]:
    """读 plugins.entries.job-radar.settings。

    **走 `hermes config get`，不自己解析 YAML。**
    自己解析会漏掉块序列（`- 前端` 这种列表写法），
    而 CLI 是 Hermes 自己的解析器，格式永远对得上。
    """
    import subprocess

    hermes = _hermes_cli()
    if not hermes:
        return {}

    base = "plugins.entries.job-radar.settings"
    try:
        proc = subprocess.run(
            _cli_cmd(hermes) + ["config", "get", base],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.join(_hermes_home(), "hermes-agent"))
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}

    out: Dict[str, Any] = {}
    for line in (proc.stdout or "").splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line.strip())
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        out[key] = _parse_cli_value(raw, proc.stdout)
    _read_config_lists(out, proc.stdout or "")
    return out


def _parse_cli_value(raw: str, whole: str) -> Any:
    """解析 `hermes config get` 的输出值。

    CLI 对列表输出成多行 YAML（`- 前端`），标量输出成一行。
    这里按需回看整段输出，把列表项收起来。
    """
    if raw in ("[]", ""):
        return [] if raw == "[]" else ""
    if raw in ("true", "false"):
        return raw == "true"
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_cli_value(x.strip(), whole) for x in inner.split(",")]
    # 块序列：当前行是 "key:"，值在下面的 "- xxx" 行里
    if raw == "" or raw is None:
        return ""
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw.strip("\"'\"")


def _read_config_lists(settings: Dict[str, Any], whole: str) -> None:
    """补上块序列形式的列表值。

    `hermes config get` 对列表输出成多行：
        keywords:
          - 前端
          - vue
    逐行扫描时那些 "- xxx" 是独立行，要挂回上一个 key。
    """
    items: Dict[str, List[str]] = {}
    last_key = None
    for line in whole.splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            if last_key is not None:
                items.setdefault(last_key, []).append(
                    line.lstrip()[2:].strip().strip("\"'\""))
            continue
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line.strip())
        if m:
            last_key = m.group(1)
            if m.group(2).strip() == "":
                settings[last_key] = []      # 先占位，后面用收集到的项覆盖
    for key, vals in items.items():
        settings[key] = vals


def _write_config_settings(settings: Dict[str, Any]) -> None:
    """把 settings 写回 config.yaml。

    **走 `hermes config set`，不手写 YAML。**
    手改 config.yaml 容易缩进错位（写坏一个缩进，整个 job-radar 节点就废了），
    CLI 会自己建嵌套块、保证缩进正确。
    """
    import subprocess

    hermes = _hermes_cli()
    if not hermes:
        raise HTTPException(status_code=500,
                            detail="找不到 hermes CLI，无法写配置")

    base = "plugins.entries.job-radar.settings."
    for key, val in settings.items():
        arg = _cli_value(val)
        cmd = _cli_cmd(hermes) + ["config", "set", base + key, arg]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                cwd=os.path.join(_hermes_home(), "hermes-agent"))
        except Exception as e:
            raise HTTPException(status_code=500,
                                detail="调用 hermes config set 失败: %s" % e)
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail="写入 %s 失败: %s" % (key, (proc.stderr or proc.stdout or "").strip()))


def _cli_value(val: Any) -> str:
    """把 Python 值转成 CLI 能吃的字符串。"""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def _hermes_cli() -> Optional[str]:
    """定位 hermes CLI 的可执行文件。找不到返回 None。

    优先级：
      1. $HERMES_HOME/hermes-agent/.hermes/bin/hermes —— 跟着 Hermes 装的位置走
      2. PATH 里的 hermes
    不要用 `python -m hermes_cli` —— hermes_cli 是包，没有 __main__。
    """
    import shutil

    for name in ("hermes", "hermes.exe"):
        p = os.path.join(_hermes_home(), "hermes-agent", ".hermes", "bin", name)
        if os.path.exists(p):
            return p
    for p in (os.path.join(_hermes_home(), "hermes-agent", ".hermes", "bin", "hermes"),
              os.path.join(_hermes_home(), "hermes-agent", ".hermes", "bin", "hermes.exe")):
        if os.path.exists(p):
            return p
    found = shutil.which("hermes")
    return found if found else None


def _cli_cmd(hermes: str) -> List[str]:
    """把 CLI 定位结果变成可执行的命令前缀。"""
    return [hermes]


# ── 画像读写（profile.yaml，JSON 格式带 # 注释）────────────────────────────

DEFAULT_PROFILE: Dict[str, Any] = {
    "title_keywords": [],
    "skills": [],
    "cities": [],
    "city": "",
    "min_experience_years": 0,
    "min_salary": 0,
    "exclude_companies": [],
    "identity": {},
    "experience_text": "",
}


def _read_profile() -> Dict[str, Any]:
    path = _profile_path()
    if not os.path.exists(path):
        return dict(DEFAULT_PROFILE)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        cleaned = "\n".join(l for l in raw.splitlines()
                            if not l.strip().startswith("#"))
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            return dict(DEFAULT_PROFILE)
    except Exception:
        return dict(DEFAULT_PROFILE)
    prof = dict(DEFAULT_PROFILE)
    prof.update({k: v for k, v in data.items() if v is not None})
    return prof


def _write_profile(prof: Dict[str, Any]) -> None:
    path = _profile_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = (
        "# job-radar 个人画像（由设置页写入）\n"
        "#\n"
        "# 格式是 JSON（去掉注释后的纯 JSON）。改的时候注意：\n"
        "#   - 字符串用双引号\n"
        "#   - 数组用 [\"a\", \"b\"]\n"
        "#   - 最后一项后面不要加逗号\n"
        "#\n"
        "# title_keywords：期望的岗位方向关键词（每个 +10，最多 30）\n"
        "# skills：你的技能，JD 里提到就加分（按覆盖率折算 30 分）\n"
        "# cities：期望城市列表，命中任一即算符合城市项\n"
        "# min_experience_years：期望最少年限（暂不参与评分）\n"
        "# min_salary：期望最低月薪（K），0 表示不要求\n"
        "# exclude_companies：出现这些词就跳过\n"
        "# identity：身份信息（照片/姓名/电话/邮箱/学历…），不参与打分\n"
        "# experience_text：真实经历原文，简历生成的唯一依据\n"
    )
    body = json.dumps(prof, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body)


# ── 请求模型 ────────────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    title_keywords: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    min_experience_years: int = 0
    min_salary: int = 0
    exclude_companies: List[str] = Field(default_factory=list)
    identity: Dict[str, Any] = Field(default_factory=dict)
    experience_text: str = ""


class SettingsIn(BaseModel):
    settings: Dict[str, Any] = Field(default_factory=dict)


# ── 路由 ────────────────────────────────────────────────────────────────────

@router.get("/config")
def get_config() -> Dict[str, Any]:
    """设置页一次性拿到全部配置 + 画像。

    配置直接走 `hermes config get` 读磁盘上的真实值 ——
    不用 plugin_config.load_config()，那个读的是 ctx 注入的运行时副本，
    在后台进程里 ctx 可能还没注入，会返回默认值。
    """
    settings = _read_config_yaml()
    # 补上 manifest 里的默认值（用户没配过的键）
    settings = _with_defaults(settings)
    return {
        "settings": settings,
        "profile": _read_profile(),
    }


# manifest plugin.yaml 的 config_schema 默认值（与那边保持一致）
DEFAULT_SETTINGS: Dict[str, Any] = {
    "keywords": [],
    "city": "653",
    "boss_city": "101210100",
    "min_score": 50,
    "max_jobs_per_run": 30,
    "sites": ["zhaopin"],
    "request_gap_seconds": 12,
    "rounds_per_day": 4,
    "push_max": 3,
    "push_new_only": True,
    "notify_on_failure": True,
    "active_hours": "09:00 - 22:00",
}


def _with_defaults(settings: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in settings.items() if v is not None})
    return out


@router.post("/profile")
def save_profile(body: ProfileIn) -> Dict[str, Any]:
    """保存个人画像。"""
    prof = body.model_dump()
    _write_profile(prof)
    return {"ok": True, "profile": prof}


@router.post("/settings")
def save_settings(body: SettingsIn) -> Dict[str, Any]:
    """保存插件设置（config.yaml 的 plugins.entries.job-radar.settings）。"""
    if not body.settings:
        raise HTTPException(status_code=400, detail="settings 为空")
    _write_config_settings(body.settings)
    return {"ok": True, "settings": body.settings}


def _normalize_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """把岗位行整理成前端要的形状。

    SQLite 里 skills / reasons / missing 存的是 JSON 字符串，
    这里统一解析成数组 —— 前端不该处理「字符串里嵌 JSON」。
    """
    out = dict(job)
    for key in ("skills", "reasons", "missing"):
        val = out.get(key)
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                out[key] = parsed if isinstance(parsed, list) else (
                    [parsed] if parsed else [])
            except Exception:
                out[key] = []
        elif out.get(key) is None:
            out[key] = []
    # area 是 report 层用的名字，前端统一读 city
    if not out.get("area"):
        out["area"] = out.get("city") or ""
    if not out.get("city"):
        out["city"] = out.get("area") or ""
    return out


@router.get("/jobs")
def list_jobs(limit: int = 30, min_score: int = 0) -> Dict[str, Any]:
    """岗位池（按匹配度倒序）。"""
    storage = _sibling("storage")
    jobs = storage.all_jobs(limit=limit, min_score=min_score)
    return {"jobs": [_normalize_job(j) for j in jobs], "count": len(jobs)}


@router.get("/runs")
def recent_runs(limit: int = 5) -> Dict[str, Any]:
    """最近几次抓取。"""
    storage = _sibling("storage")
    runs = storage.recent_runs(limit=limit)
    return {"runs": runs}


@router.get("/login")
def login_status() -> Dict[str, Any]:
    """登录态体检。"""
    tools = _sibling("tools")
    import json as _json
    try:
        raw = tools.login_status({})
        return _json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report")
def report(date: Optional[str] = None) -> Dict[str, Any]:
    """今日日报（Markdown 正文 + 解析后的岗位列表 + 抓取记录）。"""
    storage = _sibling("storage")
    report_mod = _sibling("report")

    jobs = storage.jobs_since(days=1, min_score=0)
    runs = storage.recent_runs(limit=5)

    # build_daily 返回 Path（文件已落盘），这里把正文读回来给前端预览
    path = report_mod.build_daily(jobs, runs=runs, min_score=0)
    markdown = ""
    try:
        markdown = open(path, encoding="utf-8").read()
    except Exception:
        markdown = ""
    return {"markdown": markdown, "path": str(path),
            "jobs": [_normalize_job(j) for j in jobs], "runs": runs}


# ── 简历模板与用户简历 ────────────────────────────────────────────────────────

@router.get("/resumes")
def list_resumes() -> Dict[str, Any]:
    """用户简历档案列表 —— 投递成功的简历会自动出现在这里。"""
    storage = _sibling("storage")
    try:
        return {"resumes": storage.list_resumes()}
    except Exception as exc:
        return {"resumes": [], "error": str(exc)}


@router.post("/templates")
def add_template(payload: Dict[str, Any]) -> Dict[str, Any]:
    """登记一个上传的模板。文件转换在后续阶段实现，这里只入库。"""
    storage = _sibling("storage")
    tpl = payload.get("template") or {}
    if not tpl.get("name"):
        return {"ok": False, "error": "缺少模板名称"}
    tpl.setdefault("template_id", tpl.get("name"))
    try:
        storage.upsert_template(tpl)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.delete("/templates/{template_id}")
def remove_template(template_id: str) -> Dict[str, Any]:
    """删除一个用户上传的模板。内置模板不删。"""
    storage = _sibling("storage")
    try:
        ok = storage.delete_template(template_id)
        return {"ok": ok}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/logs")
def get_logs(lines: int = 200) -> Dict[str, Any]:
    """最近的插件运行日志（设置页「查看日志」用）。

    只返回已打码的内容 —— 凭证值不会出现在这里。
    """
    logging_setup = _sibling("logging_setup")
    try:
        text = logging_setup.tail(max(1, min(int(lines), 2000)))
    except Exception as exc:
        return {"text": "", "error": str(exc)}
    return {
        "text": text,
        "file": logging_setup.log_file(),
        "lines": text.count("\n") + (1 if text else 0),
    }


@router.post("/logs/purge")
def purge_logs(keep_days: int = 30) -> Dict[str, Any]:
    """删掉太老的轮转日志文件。"""
    logging_setup = _sibling("logging_setup")
    try:
        removed = logging_setup.purge(max(1, int(keep_days)))
        return {"ok": True, "removed": removed}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── 简历匹配优化与档案 ────────────────────────────────────────────────────────

@router.get("/resume/requirements")
def resume_requirements(job_id: str) -> Dict[str, Any]:
    """某岗位的 JD 核心要求（不生成简历，只做分析）。"""
    storage = _sibling("storage")
    resume_builder = _sibling("resume_builder")
    job = storage.get_job(job_id)
    if not job:
        return {"error": "找不到岗位 %s" % job_id}
    prof = _read_profile()
    reqs = resume_builder.extract_requirements(
        job.get("description") or "", prof.get("skills") or [])
    return {
        "job_id": job_id,
        "title": job.get("title"),
        "has_jd": bool((job.get("description") or "").strip()),
        "skills": reqs["skills"],
        "degree": reqs["degree"],
        "min_years": reqs["min_years"],
        "keywords": reqs["keywords"],
    }


@router.post("/resume/optimize")
def resume_optimize(body: Dict[str, Any]) -> Dict[str, Any]:
    """针对某岗位生成定向简历。

    body: {job_id, template_id?, save?}
    返回 html（正式版）+ html_preview（带依据标注）+ 分析结果。
    """
    storage = _sibling("storage")
    resume_builder = _sibling("resume_builder")
    resume_store = _sibling("resume_store")
    resume_template = _sibling("resume_template")
    job_id = (body.get("job_id") or "").strip()
    template_id = body.get("template_id") or "classic"
    want_save = bool(body.get("save", False))
    if not job_id:
        return {"ok": False, "error": "需要 job_id"}

    job = storage.get_job(job_id)
    if not job:
        return {"ok": False, "error": "找不到岗位 %s" % job_id}

    prof = _read_profile()
    if not (prof.get("experience_text") or "").strip():
        return {"ok": False, "error": "还没有填真实经历",
                "hint": "设置页 → 用户简历 → 填「真实经历」。没有它无法生成简历，也不该编造。"}

    out = resume_builder.optimize_resume(job, prof, template_id)
    sections = resume_builder.build_sections(out["resume"])
    ctx = {"title": "简历", "identity": out["resume"]["identity"], "sections": sections}
    html_final = resume_template.render_html(template_id, dict(ctx, show_basis=False))
    html_preview = resume_template.render_html(template_id, dict(ctx, show_basis=True))

    saved = None
    if want_save:
        saved = resume_store.save_resume(job, out["matched"], html_final,
                                         template_id=template_id)
    return {
        "ok": True,
        "job_id": job_id,
        "job_title": job.get("title"),
        "template_id": template_id,
        "requirements": out["requirements"],
        "matched": out["matched"],
        "resume": out["resume"],
        "html": html_final,
        "html_preview": html_preview,
        "saved": saved,
    }


@router.get("/resume/list")
def resume_list(job_id: str = "") -> Dict[str, Any]:
    """简历档案列表；给了 job_id 就顺便算每份对该岗的匹配分并排序。"""
    storage = _sibling("storage")
    resume_store = _sibling("resume_store")
    items = resume_store.list_resumes(limit=50)
    if job_id:
        job = storage.get_job(job_id)
        if not job:
            return {"resumes": [], "error": "找不到岗位 %s" % job_id}
        for it in items:
            it["match_score"] = resume_store.resume_matches(job, it)
        items.sort(key=lambda x: -x.get("match_score", 0))
    return {"resumes": items}


@router.get("/templates")
def list_templates() -> Dict[str, Any]:
    """简历模板库 —— 内置 4 套 + 用户上传转换的。"""
    resume_template = _sibling("resume_template")
    return {"templates": resume_template.list_all()}


# ── 证件照 ────────────────────────────────────────────────────────────────
#
# 照片存成**文件**，profile.yaml 里只存路径 ——
# base64 塞进 JSON 会把画像撑成几 MB，每次读写都拖着走。

PHOTO_MAX_BYTES = 5 * 1024 * 1024   # 5 MB，够用了
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _photo_path() -> str:
    storage = _sibling("storage")
    base = os.path.join(os.path.dirname(storage.__file__), "..", "..")
    # 落到 plugin-data 里，不进插件目录（插件目录可能是仓库链接）
    try:
        from plugins.plugin_storage import plugin_data_dir
        d = plugin_data_dir("job-radar")
    except ImportError:
        d = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes",
                         "plugin-data", "job-radar")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "photo")


@router.get("/photo")
def get_photo() -> Dict[str, Any]:
    """当前证件照（返回 base64，前端直接塞 <img>）。"""
    d = _photo_path()
    if not os.path.isdir(d):
        return {"ok": True, "photo": None}
    for name in sorted(os.listdir(d)):
        ext = os.path.splitext(name)[1].lower()
        if ext not in PHOTO_EXTS:
            continue
        fp = os.path.join(d, name)
        try:
            with open(fp, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if len(raw) > PHOTO_MAX_BYTES:
            continue
        import base64
        return {"ok": True,
                "photo": "data:image/%s;base64,%s" % (
                    ext.lstrip("."), base64.b64encode(raw).decode("ascii")),
                "filename": name,
                "bytes": len(raw)}
    return {"ok": True, "photo": None}


@router.post("/photo")
def upload_photo(body: Dict[str, Any]) -> Dict[str, Any]:
    """上传证件照。body: {data_base64, filename}

    只收 jpg/png/webp，限 5 MB。存在 plugin-data 里，不进插件目录。
    """
    import base64
    data = body.get("data_base64") or ""
    if not data:
        return {"ok": False, "error": "没有收到图片数据"}
    if "," in data[:80] and data.strip().startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        return {"ok": False, "error": "图片数据不是合法的 base64"}
    if not raw:
        return {"ok": False, "error": "图片是空的"}
    if len(raw) > PHOTO_MAX_BYTES:
        return {"ok": False, "error": "图片太大（上限 5 MB）"}

    name = os.path.basename(body.get("filename") or "photo.png")
    ext = os.path.splitext(name)[1].lower()
    if ext not in PHOTO_EXTS:
        ext = ".png"
    d = _photo_path()
    os.makedirs(d, exist_ok=True)
    # 只留一张，旧的全删
    for old in os.listdir(d):
        op = os.path.join(d, old)
        if os.path.isfile(op):
            try:
                os.remove(op)
            except OSError:
                pass
    fp = os.path.join(d, "photo" + ext)
    with open(fp, "wb") as fh:
        fh.write(raw)
    return {"ok": True, "filename": os.path.basename(fp), "bytes": len(raw)}


@router.delete("/photo")
def delete_photo() -> Dict[str, Any]:
    """删掉证件照。"""
    d = _photo_path()
    if os.path.isdir(d):
        for name in os.listdir(d):
            fp = os.path.join(d, name)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except OSError:
                    pass
    return {"ok": True}


# ── Mock 层 ─────────────────────────────────────────────────────────────────
#
# 给三个还没实现的功能提供假数据，**接口形状跟真实现一致**。
# 前端对着 mock 开发，真实现写完后把 JOB_RADAR_MOCK 关掉即可，
# 调用方一行不用改。
#
#   GET  /mock/status          mock 模式状态
#   POST /mock/reset           重置 mock 状态
#
#   ① 投递三道门
#   GET  /apply/gate?job_id=       闸门体检（能不能投、卡在哪）
#   POST /apply/token              签发一次性确认令牌
#   POST /apply/submit             执行投递（过三道门）
#
#   ② 经历结构化
#   GET    /experiences            经历列表
#   POST   /experiences            新增/更新一条
#   DELETE /experiences/{exp_id}   删一条
#
#   ③ 模板转换
#   POST /templates/convert        上传文件 → 转换 → 加入模板库


def _mock():
    return _sibling("mock_provider")


@router.get("/mock/status")
def mock_status() -> Dict[str, Any]:
    """mock 模式当前状态。"""
    try:
        return {"ok": True, "mock": _mock().status()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/mock/reset")
def mock_reset() -> Dict[str, Any]:
    """把 mock 状态清回初始。"""
    try:
        return _mock().reset()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── ① 投递三道门 ────────────────────────────────────────────────────────────
#
# **真实现已接**（apply_gate.py）。mock 开关打开时仍走 mock_provider，
# 接口形状一致 —— 前端不用分两条路。

def _gate():
    """取闸门实现：mock 开着用 mock，否则用真实现。"""
    mock = _mock()
    if mock.enabled():
        return mock, True
    return _sibling("apply_gate"), False


@router.get("/apply/gate")
def apply_gate(job_id: str, resume_id: str = "") -> Dict[str, Any]:
    """投递前的闸门体检。

    返回能不能投、卡在哪一道门。**只是体检，不投。**
    """
    storage = _sibling("storage")
    gate, is_mock = _gate()
    job = storage.get_job(job_id)
    if not job:
        return {"ok": False, "error": "找不到岗位 %s" % job_id}
    status = gate.gate_status(job, resume_id or None)
    status["ok"] = True
    status["job_id"] = job_id
    status["job_title"] = job.get("title")
    status["mock"] = is_mock
    return status


@router.post("/apply/token")
def apply_token(body: Dict[str, Any]) -> Dict[str, Any]:
    """签发一次性确认令牌（5 分钟有效，绑定 job_id + site）。"""
    gate, is_mock = _gate()
    job_id = (body.get("job_id") or "").strip()
    if not job_id:
        return {"ok": False, "error": "需要 job_id"}
    try:
        token = gate.issue_token(job_id, body.get("site") or "zhaopin",
                                 body.get("resume_id") or None)
    except PermissionError as exc:
        return {"ok": False, "stage": "site_switch", "error": str(exc)}
    return {"ok": True, "token": token,
            "expires_in": gate.TOKEN_TTL_SECONDS,
            "job_id": job_id, "mock": is_mock}


@router.post("/apply/submit")
def apply_submit(body: Dict[str, Any]) -> Dict[str, Any]:
    """执行投递 —— 过三道门。

    真实现：过三道门 → 归档简历 + 打标签 → 记账。
    动作层（真正投出去）还没接，见 apply_gate._submit_to_site。
    """
    storage = _sibling("storage")
    gate, is_mock = _gate()
    job_id = (body.get("job_id") or "").strip()
    if not job_id:
        return {"ok": False, "error": "需要 job_id"}
    job = storage.get_job(job_id)
    if not job:
        return {"ok": False, "error": "找不到岗位 %s" % job_id}

    resume = None
    resume_id = body.get("resume_id")
    if resume_id:
        for r in storage.list_resumes(limit=100):
            if r.get("resume_id") == resume_id:
                resume = r
                break
        if not resume:
            return {"ok": False, "error": "找不到简历 %s" % resume_id}

    if is_mock:
        result = gate.mock_apply(job, resume, body.get("token"))
    else:
        result = gate.apply(job, resume, body.get("token"))
    if result.get("ok"):
        log.info("投递成功 job=%s resume=%s mock=%s",
                 job_id, (resume or {}).get("resume_id"), is_mock)
    return result


# ── 招聘站浏览器与登录 ──────────────────────────────────────────────────────
#
# 登录态只在浏览器里。插件不碰密码、不碰验证码 ——
# 给用户一个「打开招聘网站登录」按钮，在插件专用的浏览器里手动登录一次，
# cookie 会持久化到磁盘，之后抓取和投递都复用它。

@router.get("/browser/status")
def browser_status() -> Dict[str, Any]:
    """招聘站浏览器状态：9222 通不通、cookie 几个、哪些站已登录。"""
    browser_session = _sibling("browser_session")
    try:
        data = browser_session.status()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    data["ok"] = True
    return data


@router.post("/browser/login")
def browser_login(body: Dict[str, Any]) -> Dict[str, Any]:
    """在插件专用的浏览器里打开某招聘站的登录页。

    body: {site}
    """
    browser_session = _sibling("browser_session")
    site = (body.get("site") or "").strip()
    if not site:
        return {"ok": False, "error": "需要 site"}
    try:
        result = browser_session.open_login(site)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if not result.get("ok"):
        return {"ok": False, "error": result.get("detail") or "打开登录页失败"}
    return {"ok": True, "site": site, "url": result.get("url"),
            "tab": result.get("tab"), "detail": result.get("detail")}


# ── 投递开关管理（设置页「平台接入」用）────────────────────────────────────

@router.get("/apply/switches")
def apply_switches() -> Dict[str, Any]:
    """各站的投递开关与每日上限。

    **开关默认全关** —— 这是第一道门，用户得自己显式打开。
    """
    gate, is_mock = _gate()
    try:
        data = gate.all_switches()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    data["ok"] = True
    data["mock"] = is_mock
    return data


@router.post("/apply/switches")
def save_apply_switches(body: Dict[str, Any]) -> Dict[str, Any]:
    """开/关某站的投递开关，或调它的每日上限。

    body: {site, enabled?, daily_limit?}
    """
    gate, is_mock = _gate()
    site = (body.get("site") or "").strip()
    if not site:
        return {"ok": False, "error": "需要 site"}
    try:
        if body.get("enabled") is not None:
            gate.set_site_switch(site, bool(body["enabled"]))
        if body.get("daily_limit") is not None:
            gate.set_daily_limit(site, int(body["daily_limit"]))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    data = gate.all_switches()
    data["ok"] = True
    data["mock"] = is_mock
    return data


# ── ② 经历结构化 ────────────────────────────────────────────────────────────

@router.get("/experiences")
def list_experiences() -> Dict[str, Any]:
    """结构化的经历列表（公司 / 起止 / 职位 / 分条）。"""
    mock = _mock()
    return {"ok": True, "experiences": mock.experiences(), "mock": mock.enabled()}


@router.post("/experiences")
def save_experience(body: Dict[str, Any]) -> Dict[str, Any]:
    """新增或更新一条经历。"""
    mock = _mock()
    exp = body.get("experience") or {}
    if not (exp.get("company") or "").strip():
        return {"ok": False, "error": "缺少公司名"}
    if not (exp.get("bullets") or []):
        return {"ok": False, "error": "至少要有一条经历描述"}
    try:
        saved = mock.upsert_experience(exp)
        return {"ok": True, "experience": saved}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.delete("/experiences/{exp_id}")
def delete_experience(exp_id: str) -> Dict[str, Any]:
    """删一条经历。"""
    mock = _mock()
    ok = mock.delete_experience(exp_id)
    return {"ok": ok}


# ── ③ 模板转换 ──────────────────────────────────────────────────────────────

@router.post("/templates/convert")
def convert_template(body: Dict[str, Any]) -> Dict[str, Any]:
    """上传模板文件 → 转成 HTML 模板 → 入库。

    body: {filename, data_base64, kind?}
    """
    mock = _mock()
    filename = body.get("filename") or ""
    if not filename:
        return {"ok": False, "error": "缺少文件名"}
    result = mock.convert_template(filename, body.get("data_base64"),
                                   body.get("kind"))
    if not result.get("ok"):
        return result

    tpl = dict(result["template"])
    storage = _sibling("storage")
    try:
        storage.upsert_template({
            "template_id": tpl["template_id"],
            "name": tpl["name"],
            "description": tpl.get("description", ""),
            "format": tpl.get("format", "docx"),
            "source_path": tpl.get("source_path", ""),
            "preview_path": tpl.get("preview_path", ""),
            "builtin": 0,
        })
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "template": tpl, "mock": True}

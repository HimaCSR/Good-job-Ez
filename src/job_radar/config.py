"""配置与个人画像的读取。

配置来自 Hermes 的 plugins.entries.job-radar.settings（由 ctx 注入到 _CTX）。
画像来自 <plugin-data>/job-radar/profile.yaml（你手写，AI 只读不写）。

**画像放在 plugin-data 而不是插件目录** —— 插件目录现在是仓库的符号链接
（开发时），画像是私有数据，绝不能进 git。
"""

import json
import os

_CTX = None   # register(ctx) 时注入

PROFILE_FILE = "profile.yaml"

DEFAULT_PROFILE = {
    "title_keywords": [],
    "skills": [],
    "cities": [],          # 期望城市（多选），命中任一即算符合
    "city": "",           # 兼容旧的单城市字段
    "min_experience_years": 0,
    "min_salary": 0,
    "exclude_companies": [],
    "identity": {},       # 身份信息，不参与打分，只填简历抬头
    "experience_text": "",  # 真实经历原文，简历生成的唯一依据
}


def set_context(ctx):
    global _CTX
    _CTX = ctx


def load_config():
    """插件配置。ctx 不可用时回落到默认值。"""
    if _CTX is None:
        return {"keywords": [], "city": "653", "boss_city": "101210100",
                "min_score": 50, "max_jobs_per_run": 30,
                "sites": ["zhaopin"], "request_gap_seconds": 12,
                "rounds_per_day": 4, "push_max": 3,
                "push_new_only": True, "notify_on_failure": True,
                "active_hours": "09:00 - 22:00"}
    get = _CTX.get_config
    return {
        "keywords": get("keywords", default=[]),
        "city": get("city", default="653"),
        "boss_city": get("boss_city", default="101210100"),
        "min_score": int(get("min_score", default=50)),
        "max_jobs_per_run": int(get("max_jobs_per_run", default=30)),
        "sites": get("sites", default=["zhaopin"]),
        "request_gap_seconds": int(get("request_gap_seconds", default=12)),
        "rounds_per_day": int(get("rounds_per_day", default=4)),
        "push_max": int(get("push_max", default=3)),
        "push_new_only": bool(get("push_new_only", default=True)),
        "notify_on_failure": bool(get("notify_on_failure", default=True)),
        "active_hours": get("active_hours", default="09:00 - 22:00"),
    }


def load_profile():
    """个人画像。读不到就返回空画像（分数会偏低，但流程不崩）。

    画像文件是 JSON 格式（允许 # 注释行），所以不需要 PyYAML。
    """
    path = profile_path()
    if not os.path.exists(path):
        return dict(DEFAULT_PROFILE)
    try:
        raw = open(path, encoding="utf-8").read()
        # 去掉整行注释
        cleaned = "\n".join(l for l in raw.splitlines()
                            if not l.strip().startswith("#"))
        data = json.loads(cleaned)
    except Exception:
        return dict(DEFAULT_PROFILE)
    if not isinstance(data, dict):
        return dict(DEFAULT_PROFILE)
    prof = dict(DEFAULT_PROFILE)
    prof.update({k: v for k, v in data.items() if v is not None})
    return prof


def profile_path():
    """个人画像文件路径。

    放在 <plugin-data>/job-radar/ 下，**不在插件目录里** ——
    插件目录在开发时是指向 git 仓库的链接，画像是私有数据，
    放那儿会被提交上去。
    """
    try:
        from plugins.plugin_storage import plugin_data_dir
        base = plugin_data_dir("job-radar")
    except ImportError:
        base = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "hermes",
            "plugin-data", "job-radar")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, PROFILE_FILE)

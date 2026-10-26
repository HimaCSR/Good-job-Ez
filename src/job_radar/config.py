"""配置与个人画像的读取。

配置来自 Hermes 的 plugins.entries.job-radar.settings（由 ctx 注入到 _CTX），
画像来自插件目录下的 profile.yaml（你手写，AI 只读不写）。
"""

import json
import os

_CTX = None   # register(ctx) 时注入

PROFILE_FILE = "profile.yaml"

DEFAULT_PROFILE = {
    "title_keywords": [],
    "skills": [],
    "city": "",
    "min_experience_years": 0,
    "min_salary": 0,
    "exclude_companies": [],
}


def set_context(ctx):
    global _CTX
    _CTX = ctx


def load_config():
    """插件配置。ctx 不可用时回落到默认值。"""
    if _CTX is None:
        return {"keywords": [], "city": "538", "boss_city": "101210100",
                "min_score": 60, "max_jobs_per_run": 40,
                "sites": ["zhaopin"], "request_gap_seconds": 12}
    get = _CTX.get_config
    return {
        "keywords": get("keywords", default=[]),
        "city": get("city", default="538"),
        "boss_city": get("boss_city", default="101210100"),
        "min_score": int(get("min_score", default=60)),
        "max_jobs_per_run": int(get("max_jobs_per_run", default=40)),
        "sites": get("sites", default=["zhaopin"]),
        "request_gap_seconds": int(get("request_gap_seconds", default=12)),
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
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), PROFILE_FILE)

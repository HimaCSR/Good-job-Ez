"""配置与个人画像的读取。

配置来自 Hermes 的 plugins.entries.job-radar.settings（由 ctx 注入到 _CTX）。
画像来自 <plugin-data>/job-radar/profile.yaml（你手写，AI 只读不写）。

**画像放在 plugin-data 而不是插件目录** —— 插件目录现在是仓库的符号链接
（开发时），画像是私有数据，绝不能进 git。
"""

import json
import os
import re
import sys

_CTX = None   # register(ctx) 时注入

PROFILE_FILE = "profile.yaml"

DEFAULT_PROFILE = {
    # 主攻方向（命中给满 30 分）
    "title_keywords_primary": [],
    # 次要方向（命中给 15 分）—— 也投，但排在主攻后面
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


def _defaults():
    """没有 ctx、也读不到 Hermes 配置时的兜底。"""
    return {"keywords": [], "city": "653", "cities": [],
            "boss_city": "101210100",
            "min_score": 50, "max_jobs_per_run": 30, "mock": False,
            "sites": ["zhaopin"], "request_gap_seconds": 12,
            "rounds_per_day": 4, "push_max": 3,
            "push_new_only": True, "notify_on_failure": True,
            "active_hours": "09:00 - 22:00"}


def _read_settings_from_hermes():
    """没有 ctx 时，直接从 Hermes 的 config.yaml 读 settings。

    ## 为什么需要

    `load_config()` 原来在 `_CTX is None` 时**直接返回默认值** ——
    `keywords` 是空的 → 抓取直接中止（「没有配置关键词」）。

    而 `_CTX` 只在 `register(ctx)` 里注入。
    **任何不走 register 的调用路径都会丢掉全部配置**：
    - 独立脚本（`python -c "from job_radar import tools; tools.scan()"`）
    - 某些定时任务路径
    - 单测

    所以这里兜底读一次 Hermes 的 config.yaml
    （`plugins.entries.job-radar.settings`）。

    **走 `hermes config get`**，不自己解析 YAML ——
    自己的解析器会漏掉块序列（`- 前端` 这种列表写法）。
    """
    import subprocess

    try:
        from hermes_cli import __main__  # noqa: F401
    except Exception:
        pass

    local = os.environ.get("LOCALAPPDATA")
    root = os.path.join(local, "hermes", "hermes-agent") if local else \
        os.path.expanduser("~/.hermes/hermes-agent")
    if not os.path.isdir(root):
        return {}

    base = "plugins.entries.job-radar.settings"
    for args in (
        [sys.executable, "-m", "hermes_cli.main", "--profile", "default",
         "config", "get", base],
        ["hermes", "config", "get", base],
    ):
        try:
            proc = subprocess.run(args, capture_output=True, text=True,
                                   timeout=60, cwd=root)
        except Exception:
            continue
        if proc.returncode != 0:
            continue
        out = _parse_cli_output(proc.stdout or "")
        if out:
            return out
    return {}


def _parse_cli_output(text):
    """解析 `hermes config get` 的输出。

    CLI 对列表输出成多行 YAML（`- 前端`），标量输出一行。
    """
    lines = text.splitlines()
    out = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw == "":
            # 块序列：值在下面的 "- xxx" 行里
            items = []
            while i < len(lines):
                nxt = lines[i].strip()
                if nxt.startswith("- "):
                    items.append(nxt[2:].strip().strip("\"'"))
                    i += 1
                else:
                    break
            out[key] = items
            continue
        if raw in ("true", "false"):
            out[key] = raw == "true"
            continue
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            out[key] = [] if not inner else \
                [x.strip().strip("\"'") for x in inner.split(",")]
            continue
        try:
            out[key] = int(raw)
            continue
        except ValueError:
            pass
        out[key] = raw.strip("\"'")
    return out


def load_config():
    """插件配置。

    优先用 ctx（`ctx.get_config`）；ctx 不可用时**兜底读 Hermes 的
    config.yaml** —— 否则独立脚本/定时任务会丢掉全部配置
    （`keywords` 为空 → 抓取直接中止）。
    """
    if _CTX is None:
        cfg = _defaults()
        try:
            saved = _read_settings_from_hermes()
        except Exception:
            saved = {}
        for k, v in (saved or {}).items():
            if v in (None, "", []):
                continue
            cfg[k] = v
        return cfg
    get = _CTX.get_config
    return {
        "keywords": get("keywords", default=[]),
        "city": get("city", default="653"),
        # 多个城市码（逐个抓）—— 空=只用 city
        "cities": get("cities", default=[]),
        "boss_city": get("boss_city", default="101210100"),
        "min_score": int(get("min_score", default=50)),
        "mock": bool(get("mock", default=False)),
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

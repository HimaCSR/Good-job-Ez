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
    "template_convert", "template_store", "city_codes",
    # **模板骨架规格** —— `/templates/slots` 要读写 spec.json
    # **新增模块必须注册** —— 列表外的 .py 永远不会被 import
    # → `_sibling("template_slots")` 抛 ImportError → 端点直接 500。
    "template_slots",
    # **从经历抽方向词** —— 保存画像时自动更新期望方向
    "profile_derive",
    # **BOSS 城市码表** —— `/cities` 要返回两站并集
    "boss_city_codes",
    # **方向分类** —— 把岗位归到「电商运营/建筑施工管理/AI产品开发」
    # **调度** —— 用户自定义抓取/推送时间
    # **方向评估** —— Agent 评估经历 → 可选方向
    "direction_catalog", "schedule", "direction_evaluate",
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
            # **已经加载过了** ——
            # 但那个模块可能是**旧版本**（别的插件先 import 了它，
            # 或者 app 在别处加载了一份）。
            #
            # 本机踩过：新进程里兄弟模块已经在 sys.modules 里（旧的），
            # 于是新加的功能不生效 —— 用户看到旧行为，
            # 而磁盘上的文件明明已经改好了。
            #
            # **改成总是从磁盘加载** —— 插件的兄弟模块之间没有
            # 必须共享实例的场景，重新 import 是安全的。
            log.info("job-radar 模块 %s 已在 sys.modules 中，"
                     "从磁盘重新加载（%s）", name, path)
            try:
                spec = importlib.util.spec_from_file_location(mod_name, path)
                if spec is not None and spec.loader is not None:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name] = mod
                    spec.loader.exec_module(mod)
                    loaded[name] = mod
                    continue
            except Exception as exc:      # noqa: BLE001
                log.warning("job-radar 模块 %s 重新加载失败: %s", name, exc)
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


def _module_mtime(name: str) -> float:
    """模块源文件的 mtime；拿不到返回 0。"""
    path = os.path.join(_PLUGIN_ROOT, name + ".py")
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


# 每个模块的源码 mtime —— 用来判断要不要重新加载
_SIBLING_MTIMES = {
    name: _module_mtime(name) for name in _SIBLING_MODULES
}


def _dev_hot_reload() -> bool:
    """开发模式热重载开了吗？

    ## 判据

    **插件目录是软链/junction** → 说明这是开发目录（指向仓库），
    自动开热重载。

    正式安装时 `plugins/job-radar` 是一个**真实目录**（拷过去的），
    不是软链 → 自动关。

    ## 为什么需要

    **Python 模块一旦 import 就固定了** —— 改了源码，跑着的进程
    还在用旧代码。本机踩过：加了 `.md` 支持，源文件改对了，
    但插件 API 进程是 16:11 起的，它 import 的是 16:11 的版本，
    于是用户看到「不支持的格式：.md」，而我看代码完全正确。

    前端有 fs-watch 能热重载，**后端没有** —— 不加这个的话，
    每改一次后端就要重启整个 Hermes。

    ## 怎么关

    环境变量 `JOB_RADAR_HOT_RELOAD=0` 显式关闭
    （正式安装时也不需要 —— 目录不是软链，本来就是关的）。
    """
    flag = os.environ.get("JOB_RADAR_HOT_RELOAD", "").strip().lower()
    if flag in ("0", "off", "false", "no"):
        return False
    if flag in ("1", "on", "true", "yes"):
        return True
    # 默认：插件目录是软链/junction → 开发模式
    try:
        if os.path.islink(_PLUGIN_ROOT):
            return True
        # junction 在 Windows 上 islink 为 False，用 realpath 判断
        real = os.path.realpath(_PLUGIN_ROOT)
        if real != os.path.abspath(_PLUGIN_ROOT):
            return True
        # plugins/ 目录本身是 junction（junction 指向仓库的 plugins 目录）
        parent = os.path.dirname(_PLUGIN_ROOT)
        if os.path.realpath(parent) != os.path.abspath(parent):
            return True
    except OSError:
        return False
    return False
def _log_load_summary() -> None:
    """启动时打一行「加载了哪些模块、从哪加载的」。

    ## 为什么

    「代码明明改了，但跑着的行为还是旧的」这类问题，
    **光看源码永远看不出来** —— 得知道进程实际用的是哪份文件。

    这行日志给出：
    - 插件根目录（`_PLUGIN_ROOT`）
    - 每个兄弟模块的 `__file__`（实际加载路径）
    - 开发模式热重载开没开

    ## 为什么要写文件

    **插件 API 跑在独立子进程里，它的日志不一定落到主日志。**
    本机就遇到：加了加载摘要日志，重启后日志里什么都没有 ——
    根本不知道是「没加载」还是「加载了但日志没落盘」。

    所以**额外写一个诊断文件**（scratch 目录），保证一定能看到。
    """
    try:
        files = {}
        for name, mod in _SIBLING_MODULES.items():
            f = getattr(mod, "__file__", "?")
            files[name] = f
        summary = (
            "job-radar API 已加载\n"
            "  本文件      : %s\n"
            "  插件根目录  : %s\n"
            "  热重载      : %s\n"
            "  模块来源    :\n%s\n"
            % (
                os.path.abspath(__file__),
                _PLUGIN_ROOT,
                _dev_hot_reload(),
                "\n".join("    %-16s %s" % (k, v)
                          for k, v in sorted(files.items())),
            )
        )
        log.info("job-radar API 已加载：root=%s 热重载=%s",
                 _PLUGIN_ROOT, _dev_hot_reload())

        # **写诊断文件** —— 日志可能不落盘，文件一定看得到
        try:
            home = os.environ.get("HERMES_HOME") or os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "hermes")
            diag_dir = os.path.join(home, "cache", "scratch")
            os.makedirs(diag_dir, exist_ok=True)
            with open(os.path.join(diag_dir, "job-radar-load.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write(summary)
        except Exception as exc:      # noqa: BLE001
            log.warning("job-radar 诊断文件写不出来: %s", exc)
    except Exception as exc:      # noqa: BLE001
        log.warning("job-radar 加载摘要打不出来: %s", exc)


# 启动时打一行加载摘要 —— 出问题第一眼看它
_log_load_summary()


def _reload_sibling(name: str):
    """重新加载一个兄弟模块（源码变了的时候）。"""
    import importlib.util

    path = os.path.join(_PLUGIN_ROOT, name + ".py")
    mod_name = _PKG_NAME + "." + name
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        _SIBLING_MODULES[name] = mod
        _SIBLING_MTIMES[name] = _module_mtime(name)
        log.info("job-radar 模块 %s 已热重载", name)
        return mod
    except Exception as exc:      # noqa: BLE001
        log.warning("job-radar 模块 %s 热重载失败: %s", name, exc)
        return None


def _sibling(name: str):
    """取一个兄弟模块；取不到就抛，避免静默返回 None。

    ## 开发模式热重载

    **Python 模块一旦 import 就固定了** —— 改了源码，跑着的进程
    还在用旧代码。本机踩过：加了 `.md` 支持，源文件改对了，
    但插件 API 进程是 16:11 起的，它 import 的是 16:11 的版本，
    于是用户看到「不支持的格式：.md」。

    所以这里在**开发模式**下（`JOB_RADAR_HOT_RELOAD=1` + 插件目录是软链）
    每次取模块都检查 mtime，变了就重新 import。
    **正式环境默认关** —— 不该有意外的热重载行为。
    """
    if _dev_hot_reload():
        mtime = _module_mtime(name)
        if name in _SIBLING_MODULES and mtime != _SIBLING_MTIMES.get(name):
            _reload_sibling(name)

    mod = _SIBLING_MODULES.get(name)
    if mod is None:
        # **字典里没有 → 试一次从磁盘加载** ——
        # 新加的模块忘了加进 `_SIBLINGS` 时，至少还能用上
        # （而不是直接抛 ImportError 让整个功能 500）。
        loaded = _reload_sibling(name)
        if loaded is not None:
            return loaded
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

    ## ⚠️ **只写「真正变了」的键** —— 否则会超时

    **踩过（2026-10-30）**：桌面端点「保存」报
    `Timed out connecting to Hermes backend after 30000ms`。
    **用户填了东西点保存，什么都没存上。**

    **根因**：一次 `hermes config set` 调用约 **2.2 秒**（CLI 启动开销）。
    而设置页的 `local` 是**整份配置对象**（所有面板的字段都在里面）→
    逐键写 → **15 个键 = 32 秒** → **超过桌面端 30 秒超时**。

    → **先跟磁盘上的现值比**，只写**真的变了**的键。
    用户只改一个时间点 → 只写 1 个键 → 2.2 秒，稳稳的。

    ## 为什么要「并行」

    即使去掉了没变的键，用户第一次点保存可能真要改 10 个键
    → 22 秒，仍在 30 秒边缘。→ **并行执行** → 总耗时 ≈ 最慢的那一个。
    """
    import subprocess

    hermes = _hermes_cli()
    if not hermes:
        raise HTTPException(status_code=500,
                            detail="找不到 hermes CLI，无法写配置")

    base = "plugins.entries.job-radar.settings."

    # ── ① 跟现值比，只留真正变了的 ──
    current = _read_config_yaml()
    pending = []
    for key, val in (settings or {}).items():
        if key not in current:
            pending.append((key, val))
            continue
        old = current[key]
        # **列表比较要按顺序** —— 用户重新排了序也算「变了」
        if isinstance(old, list) or isinstance(val, list):
            if _as_list(old) != _as_list(val):
                pending.append((key, val))
            continue
        # **数字/字符串比较要归一** —— CLI 回读可能是 "653"，
        # 前端传回来的是 653（int）→ 不归一会误判成「变了」
        if str(old) != str(val):
            pending.append((key, val))

    if not pending:
        return

    # ── ② 并行写 ──
    from concurrent.futures import ThreadPoolExecutor

    def _one(item):
        key, val = item
        cmd = _cli_cmd(hermes) + ["config", "set", base + key, _cli_value(val)]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            cwd=os.path.join(_hermes_home(), "hermes-agent"))
        return key, proc

    errors = []
    with ThreadPoolExecutor(max_workers=min(8, len(pending))) as pool:
        for key, proc in pool.map(_one, pending):
            if proc.returncode != 0:
                errors.append("%s: %s" % (
                    key, (proc.stderr or proc.stdout or "").strip()))
    if errors:
        raise HTTPException(status_code=500,
                            detail="写入配置失败: " + "; ".join(errors))


def _as_list(val: Any) -> list:
    """把配置值归一成列表（比较用）。"""
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return [str(v).strip() for v in val]
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                return [str(v).strip() for v in json.loads(s)]
            except Exception:
                pass
        return [x.strip() for x in s.split(",") if x.strip()]
    return [str(val)]


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
        "# title_keywords_primary：主攻方向（命中给满 30 分）\n"
        "# title_keywords：也投的方向（命中给 15 分，排在主攻后面）\n"
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
    # **主攻方向** —— 命中给满 30 分。
    # 不加这个字段的话，Pydantic 会把前端传来的主攻方向**直接丢掉**
    # （模型里没有的字段不保留）—— 界面填了，存不进去。
    title_keywords_primary: List[str] = Field(default_factory=list)
    # 也投的方向 —— 命中给 15 分，排在主攻后面
    title_keywords: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    min_experience_years: int = 0
    min_salary: int = 0
    exclude_companies: List[str] = Field(default_factory=list)
    identity: Dict[str, Any] = Field(default_factory=dict)
    experience_text: str = ""
    # **方向词权重** —— 按经历评定的方向强度（0.5 ~ 3.0）
    #
    # **不分主次** —— 主攻方向也在这张表里，只是权重高一点。
    # 评分时只认这张表 → 主次差异体现在**权重**上，不体现在**规则**上。
    #
    # 不加这个字段 → Pydantic 会把前端传来的权重**直接丢掉**。
    direction_weights: Dict[str, float] = Field(default_factory=dict)
    # **可选方向** —— 用户能投的方向（电商运营/建筑施工管理/AI产品开发…）
    #
    # 用户诉求：「由 Agent 评估用户经历，确定用户可选方向、
    # 根据可选方向每天只推荐单个方向中评分最高的 5 条」
    #
    # **空 = 全方向都算**（推分数最高的那个）。
    directions: List[str] = Field(default_factory=list)


class SettingsIn(BaseModel):
    settings: Dict[str, Any] = Field(default_factory=dict)


# **Pydantic 的注解是字符串** ——
#
# 本文件有 `from __future__ import annotations`，
# 所有注解都是**延迟求值的字符串** → Pydantic 解析不到 `List`/`Dict` 的
# 实际类型 → `TypeAdapter[ProfileIn] is not fully defined`。
#
# **本机踩过**：直接 `ProfileIn(**data)` 抛
# `PydanticUserError: ProfileIn is not fully defined`。
#
# → 显式 rebuild 一次，把注解解析成真类型。
#
# **为什么之前没炸** —— FastAPI 在**装饰器**时就把路由签名解析好了，
# 走 HTTP 是好的；**但代码里直接构造模型**（单测、脚本）会炸。
for _model in (ProfileIn, SettingsIn):
    try:
        _model.model_rebuild()
    except Exception:      # noqa: BLE001
        pass


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
#
# ⚠️ **必须跟 plugin.yaml 的 config_schema 对齐** ——
# 设置页用这份默认值去补「用户没配过的键」。
# 漏一个键 → 前端拿到 undefined → 那个输入框显示空白/保存后又被填回去。
#
# **踩过**：`scan_times` / `push_times` / `directions` 三个键漏在这里
# → 设置页的「每天抓取时间 / 每天推送时间」编辑器**读不到用户配的值**
# → 用户配了时间点，页面上却显示空白（像没保存）。
DEFAULT_SETTINGS: Dict[str, Any] = {
    "keywords": [],
    "city": "653",
    # **多城市（填城市名）** —— 空 = 只用上面的 city
    "cities": [],
    "boss_city": "101210100",
    "min_score": 50,
    "max_jobs_per_run": 30,
    "sites": ["zhaopin"],
    "request_gap_seconds": 12,
    "rounds_per_day": 4,
    # **每方向推几条** —— 与 plugin.yaml 一致（5，不是 3）
    "push_max": 5,
    "push_new_only": True,
    "notify_on_failure": True,
    "active_hours": "09:00 - 22:00",
    # **用户可选方向** —— 空 = 全方向都算
    "directions": [],
    # **抓取时间点** —— 与 plugin.yaml 一致
    # （**推送没有自己的时间点** —— 抓完就推，2026-10-30 用户决定）
    "scan_times": ["09:00", "13:00", "17:00", "21:00"],
    "mock": False,
}


def _with_defaults(settings: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in settings.items() if v is not None})
    return out


@router.post("/profile")
def save_profile(body: ProfileIn) -> Dict[str, Any]:
    """保存个人画像 —— **顺便根据经历更新方向词**。

    用户诉求：

    > 每次用户保存插件内的个人信息保存/更新，便重新根据经历内容
    > 更新期望内容标签，保证抓取的岗位更加契合用户

    ## 做了什么

    1. **从经历抽方向词** → 补进 `title_keywords`（次要方向）
    2. **重算所有老岗位的分数** —— 画像变了，分数要跟着变
       （skill 里记着这个坑：「改了画像老岗位不重算」）
    3. **返回变更说明** —— 前端告诉用户「根据你的经历补了这些方向」

    ## 为什么不改「主攻方向」

    主攻是**战略选择**（30 分 vs 15 分），自动抽的词只是「你干过什么」。
    → 自动抽的进**次要方向**，主攻永远由用户自己定。

    ## 为什么不自动补技能

    技能项 = 30 分 × (命中数 / 技能总数) → 加技能会让分数**变低**。
    本机踩过：加了 17 个技能 → 跨境电商运营 80 分掉到 70 分。

    → **只加方向词**。
    """
    prof = body.model_dump()

    # ── ① 从经历补方向词 ──
    derive_note = ""
    added = {"directions": [], "skills": []}
    try:
        storage = _sibling("storage")
        profile_derive = _sibling("profile_derive")
        experiences = storage.list_experiences()
        if experiences:
            prof, derive_note, added = profile_derive.apply_to_profile(
                prof, experiences)
    except Exception as exc:      # noqa: BLE001
        # **推导失败不能挡住保存** —— 用户填的东西要先存下来。
        derive_note = "方向词自动更新失败：%s" % exc

    _write_profile(prof)

    # ── ② 重算老岗位分数 ──
    #
    # **画像变了，分数必须跟着变** ——
    # 否则「改了画像老岗位不重算」→ 老方向的高分岗位一直霸着推荐位。
    rescored = 0
    try:
        storage = _sibling("storage")
        matcher = _sibling("matcher")
        experiences = storage.list_experiences()
        # **`score_fn` 不是 `matcher`** —— rescore_all 的签名是
        # `rescore_all(profile, experiences=None, score_fn=None)`。
        rescored = storage.rescore_all(prof, experiences=experiences,
                                       score_fn=matcher.score_job)
    except Exception as exc:      # noqa: BLE001
        rescored = 0
        derive_note = (derive_note + "  " if derive_note else "") + \
            "岗位分数重算失败：%s" % exc

    return {
        "ok": True,
        "profile": prof,
        "derived": added,
        "note": derive_note,
        "rescored": rescored,
    }


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
    # ── **方向**（主）──
    #
    # 用户诉求：「电商运营（速卖通、ozon、阿里国际站、虾皮等国际电商
    # 平台相关的运营工作归为一类）、建筑施工管理等方向归为一类、
    # AI产品开发等方向归为一类」
    #
    # → **推荐单位是「方向」** —— 前端按它分组。
    #
    # 数据库里存着（抓取时分类好的）→ 直接读。
    # 没存（老数据没回填）→ 现算一个。
    out["direction"] = (out.get("direction") or "").strip()
    if not out["direction"]:
        try:
            direction_catalog = _sibling("direction_catalog")
            hay = " ".join(str(out.get(k) or "") for k in
                           ("title", "jd_text", "description", "company"))
            out["direction"] = direction_catalog.classify(hay)
        except Exception:
            out["direction"] = ""

    # ── **类型标识**（辅）──
    #
    # **标题字面归一化** —— 同一措辞的不同层级
    # （跨境电商运营助理 / 专员 / 主管 → 同一个 type_key）。
    #
    # 跟 `direction` 的区别：
    #
    # | | 粒度 | 例子 |
    # | --- | --- | --- |
    # | `direction` | **方向**（粗） | 速卖通运营、ozon运营 → 电商运营 |
    # | `type_key` | **同措辞**（细） | 跨境电商运营助理 → 跨境电商运营 |
    #
    # 前端分组用 `direction`（用户诉求），`type_key` 留着做同类型折叠。
    try:
        matcher = _sibling("matcher")
        out["type_key"] = matcher.job_type_key(out.get("title") or "")
    except Exception:
        out["type_key"] = ""
    return out


@router.get("/directions")
def list_directions() -> Dict[str, Any]:
    """**方向列表** —— 设置页让用户选「能投哪些方向」。

    ## 返回

    ```json
    {"directions": [{"name": "电商运营", "count": 81, "top_score": 80,
                     "from_experience": true, "selected": true}],
     "selected": ["电商运营"], "unknown_count": 19}
    ```

    ## 为什么按岗位数排序

    **岗位多的方向才有得选** —— 只有 1 条岗位的方向推出来也没意义。

    `from_experience` 标出「用户做过」的方向 —— 那是最该选的。
    """
    storage = _sibling("storage")
    try:
        direction_catalog = _sibling("direction_catalog")
    except Exception:
        direction_catalog = None
    prof = _read_profile()

    rows = []
    try:
        with storage._conn() as conn:
            rows = conn.execute(
                """SELECT direction, COUNT(*) AS c, MAX(score) AS top
                   FROM jobs WHERE direction IS NOT NULL AND direction != ''
                   GROUP BY direction""").fetchall()
    except Exception:
        rows = []

    # **经历里出现过的方向** —— 用户做过
    from_exp = set()
    try:
        experiences = storage.list_experiences()
        for exp in experiences:
            text = " ".join([str(exp.get("title") or ""),
                             str(exp.get("company") or ""),
                             " ".join(str(b) for b in (exp.get("bullets") or []))])
            if direction_catalog is not None and text.strip():
                d = direction_catalog.classify(text)
                if d and d != direction_catalog.UNKNOWN:
                    from_exp.add(d)
    except Exception:
        pass

    selected = list(prof.get("directions") or [])
    out = []
    for r in rows:
        out.append({
            "name": r["direction"],
            "count": r["c"],
            "top_score": r["top"],
            "from_experience": r["direction"] in from_exp,
            "selected": r["direction"] in selected,
        })
    out.sort(key=lambda x: (not x["from_experience"], -x["count"], x["name"]))
    return {"directions": out, "selected": selected}


@router.post("/directions")
def save_directions(body: Dict[str, Any]) -> Dict[str, Any]:
    """**保存可选方向** —— 之后每天只推这些方向。

    ## 为什么不写在 settings 里

    方向是**画像的一部分**（跟经历、方向权重一起），
    存在 profile.yaml 里 → 改方向不用动 Hermes 全局配置。

    → 但**推送时也要读到** → `config.load_profile()` 里有就行。
    """
    raw = body.get("directions")
    if raw is None:
        raise HTTPException(status_code=400, detail="directions 不能为空")
    chosen = []
    seen = set()
    for d in (raw or []):
        d = str(d).strip()
        if d and d not in seen:
            seen.add(d)
            chosen.append(d)
    prof = _read_profile()
    prof["directions"] = chosen
    _write_profile(prof)
    return {"ok": True, "directions": chosen, "count": len(chosen)}


@router.get("/jobs")
def list_jobs(limit: int = 30, min_score: int = 0,
              per_type: int = 3) -> Dict[str, Any]:
    """岗位池（按匹配度倒序）—— **同类型只给最高分的 N 条**。

    ## 同类型怎么判

    `matcher.job_type_key(title)` —— 把标题归一化成**类型**：

    ```
    跨境电商运营助理                → 跨境电商运营
    跨境电商运营专员（速卖通/eBay） → 跨境电商运营
    跨境电商运营主管                → 跨境电商运营
    ```

    **职级后缀（助理/专员/主管/经理）全部去掉** ——
    那是同一类岗位的不同层级，不该拆成不同类型。

    ## 为什么必须做

    实测：主攻「跨境电商运营」→ 岗位池 30 条**全是**跨境电商运营的
    不同措辞 → 推荐列表被同一个方向刷屏，用户看不到别的机会。

    → **每个类型只留最高分的 3 条**，其余折叠（「看全部」里还能看到）。

    ## per_type=0 → 不限制

    「看全部」时前端会传 `per_type=0` → 全量返回。
    """
    storage = _sibling("storage")
    matcher = _sibling("matcher")
    jobs = storage.all_jobs(limit=limit, min_score=min_score)
    normalized = [_normalize_job(j) for j in jobs]

    if per_type and per_type > 0:
        seen = {}
        for j in normalized:
            # **必须用 `j["type_key"]`**（方向词法）——
            # 不能在这里另算一遍「标题法」，
            # 否则**两套键** → 前端分组和这里标记对不上。
            #
            # 本机踩过：这里用 `job_type_key(title)`，而 `_normalize_job`
            # 用 `job_type_by_direction(...)` → 键不同
            # → 标记数 21，预期 23 → 测试直接挂。
            key = j.get("type_key") or ""
            # **空标题的岗位不参与分组** —— 否则全挤成一组
            if not key:
                key = "__other__"
            seen.setdefault(key, 0)
            seen[key] += 1
            if seen[key] > per_type:
                j["_over_type_limit"] = True
        # **把超额的排到最后**（不删 —— 「看全部」还要能翻到）
        normalized.sort(key=lambda j: (1 if j.get("_over_type_limit") else 0,
                                       -(j.get("score") or 0)))

    return {"jobs": normalized, "count": len(normalized)}


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


def _fetch_jd(job: Dict[str, Any]) -> Dict[str, Any]:
    """抓一次岗位详情，把 JD 写回岗位记录。返回岗位（或 None）。

    ## 为什么必须有这一步

    **列表页不返回 JD** —— 描述、要求、学历、年限全在详情页里。
    没有 JD → `extract_requirements` 只能从岗位标题抽 →
    抽出的要求跟用户经历里的技能**对不上** →
    `_build_work_entries` 把**所有 bullet 都过滤掉** →
    **简历的工作经历章节只有公司/职位/时间，没有内容**。

    ## 两个站的详情页参数不一样

    | 站 | adapter | 参数 |
    | --- | --- | --- |
    | 智联 | `zhaopin/detail` | `jobId`（job_id 去掉非字母数字） |
    | BOSS | `boss/detail` | `securityId`（**不是 job_id**） |

    **BOSS 抓不到 securityId 就没法抓 JD** —— 所以抓取时要把它存进
    `jobs.security_id`（`tools.FIELD_MAP["boss"]` 负责映射）。
    """
    try:
        bbclient = _sibling("bbclient")
        storage = _sibling("storage")
    except Exception:
        return None

    source = (job.get("source") or "").strip()
    job_id = str(job.get("job_id") or "")
    detail = None

    if source == "boss":
        sec = (job.get("security_id") or "").strip()
        if not sec:
            return None
        detail = bbclient.fetch_detail("boss", sec)
    elif source == "zhaopin":
        if not job_id:
            return None
        detail = bbclient.fetch_detail("zhaopin", job_id)
    else:
        return None

    if not detail or detail.get("error"):
        return None

    # **BOSS 的详情返回嵌套结构** —— JD 在 `job.description`
    desc = (detail.get("description") or "").strip()
    if not desc:
        desc = ((detail.get("job") or {}).get("description") or "").strip()
    if not desc:
        return None

    # 写回岗位记录（下次就不用再抓）
    try:
        with storage._conn() as conn:
            conn.execute("UPDATE jobs SET description = ? WHERE job_id = ?",
                         (desc, job_id))
    except Exception:
        pass
    job = dict(job)
    job["description"] = desc
    return job


def _render_preview(template_id: str, css_override: str = "",
                    skeleton_override: str = "") -> str:
    """用用户的真实画像渲染一个模板 → 返回 HTML。失败返回空串。

    **内容全部来自用户自己的画像和经历** —— 不编造。

    `css_override` —— 上传流程的 dry_run 预览用：
    转换出的 CSS **还没落盘**，直接传进来渲染。
    """
    try:
        resume_template = _sibling("resume_template")
        resume_builder = _sibling("resume_builder")
    except Exception:
        return ""
    prof = _read_profile()
    experiences = []
    try:
        storage = _sibling("storage")
        experiences = storage.list_experiences()
    except Exception:
        experiences = []

    identity = dict(prof.get("identity") or {})
    identity.setdefault("headline", "简历")
    resume_data = {
        "identity": identity,
        "summary": "这是模板预览 —— 内容来自你的个人信息面板。",
        "skills": list(prof.get("skills") or [])[:12],
        "experiences": [],
        "projects": [],
        "education": ([{"title": " ".join(
            x for x in [identity.get("school"), identity.get("major")] if x),
            "meta": "", "subtitle": ""}]
            if identity.get("school") else []),
    }
    for e in experiences or []:
        bullets = [{"text": str(b), "basis": ""}
                   for b in (e.get("bullets") or []) if str(b).strip()]
        resume_data["experiences"].append({
            "title": " · ".join(x for x in [e.get("company"), e.get("title")]
                                if x),
            "meta": " - ".join(x for x in [e.get("start"), e.get("end")] if x),
            "subtitle": "",
            "bullets": bullets,
        })
    try:
        sections = resume_builder.build_sections(resume_data)
        ctx = {"title": "简历", "identity": identity, "sections": sections}
        return resume_template.render_html(template_id,
                                          dict(ctx, show_basis=False),
                                          css_override=css_override or None,
                                          skeleton_override=skeleton_override or None)
    except Exception:
        return ""



@router.get("/templates/slots")
def get_template_slots(template_id: str = "") -> Dict[str, Any]:
    """读一个模板的槽位规格（给前端「编辑槽位」用）。

    返回 {ok, has_slots, edit, roles}
    - `edit`   —— 当前槽位（姓名 / 联系方式 / 章节）
    - `roles`  —— 可选的角色列表（姓名 / 联系方式 / 章节标题 / 正文 / 忽略）
    """
    try:
        store = _sibling("template_store")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return store.load_slots((template_id or "").strip())


@router.post("/templates/slots")
def edit_template_slots(body: Dict[str, Any]) -> Dict[str, Any]:
    """保存用户编辑后的槽位 → 重建骨架 → 返回新骨架。

    body: {template_id, edit: {name, fields, sections}}

    ## 为什么要有这个端点

    自动推断**必然有猜错的时候**（「电话：138…」是联系方式还是正文？）。
    → 让用户在预览里点一下「这段是什么」，**一次确认永久复用**。
    """
    template_id = (body.get("template_id") or "").strip()
    if not template_id:
        return {"ok": False, "error": "缺少 template_id"}
    try:
        store = _sibling("template_store")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    result = store.save_slots(template_id, body.get("edit") or {})
    if not result.get("ok"):
        return result
    # **顺便重新渲染一份** —— 前端改完直接看效果，不用再点一次预览
    html = _render_preview(template_id)
    return {
        "ok": True,
        "edit": result.get("edit") or {},
        "html": html or "",
    }

@router.post("/templates/preview")
def preview_template(body: Dict[str, Any]) -> Dict[str, Any]:
    """预览一个模板渲染成什么样 —— **用用户的真实画像填内容**。

    body: {template_id}
    返回 {ok, html}

    ## 为什么要有这个

    用户反馈：「没有点击简历模板转换按钮，也无法预览所转换模板的样子」。

    上传的模板**转换完只登记一条记录**（名字 + CSS 片段），
    **看不到渲染成什么样** —— 不知道版式对不对、能不能用。

    → 这里用**用户的真实画像**（姓名/技能/经历）渲染一遍，
    返回完整 HTML，前端在弹窗里显示。

    **不编造内容** —— 内容全部来自用户自己的画像和经历。
    """
    template_id = (body.get("template_id") or "classic").strip()
    try:
        resume_template = _sibling("resume_template")
        resume_builder = _sibling("resume_builder")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    prof = _read_profile()
    experiences = []
    try:
        storage = _sibling("storage")
        experiences = storage.list_experiences()
    except Exception:
        experiences = []

    # **造一份「示例简历」** —— 内容全部来自用户自己的画像和经历，
    # **不编造任何用户没有的经历**。
    identity = dict(prof.get("identity") or {})
    identity.setdefault("headline", "简历")
    resume_data = {
        "identity": identity,
        "summary": "这是模板预览 —— 内容来自你的个人信息面板。",
        "skills": list(prof.get("skills") or [])[:12],
        "experiences": [],
        "projects": [],
        "education": ([{"title": " ".join(
            x for x in [identity.get("school"), identity.get("major")] if x),
            "meta": "", "subtitle": ""}]
            if identity.get("school") else []),
    }
    for e in experiences or []:
        bullets = [{"text": str(b), "basis": ""}
                   for b in (e.get("bullets") or []) if str(b).strip()]
        resume_data["experiences"].append({
            "title": " · ".join(x for x in [e.get("company"), e.get("title")]
                                if x),
            "meta": " - ".join(x for x in [e.get("start"), e.get("end")] if x),
            "subtitle": "",
            "bullets": bullets,
        })

    try:
        sections = resume_builder.build_sections(resume_data)
        ctx = {"title": "简历", "identity": identity, "sections": sections}
        html = resume_template.render_html(template_id, dict(ctx, show_basis=False))
    except Exception as exc:
        return {"ok": False, "error": "预览失败：%s" % exc}

    return {"ok": True, "template_id": template_id, "html": html}


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

    # **JD 缺失就抓一次详情页** ——
    #
    # 列表页**不返回 JD**（描述、要求全在详情页里）。
    # 不抓的话 `job["description"]` 是空的 →
    # `extract_requirements` 只能从岗位标题抽 → 抽出 1 条要求 →
    # 用户经历里的 bullet 全都命中不了 → **工作经历章节是空的**。
    #
    # **BOSS 用 securityId，智联用 jobId** —— 两者都在岗位记录里。
    if not (job.get("description") or "").strip():
        job = _fetch_jd(job) or job

    prof = _read_profile()
    # **结构化经历优先** ——
    # 它有公司/职位/起止，是简历「工作经历」章节真正需要的东西；
    # 自由文本只是兜底。
    experiences = storage.list_experiences()
    has_text = bool((prof.get("experience_text") or "").strip())
    if not experiences and not has_text:
        return {"ok": False, "error": "还没有填经历",
                "hint": "设置页 → 用户简历 → 填「结构化经历」"
                        "（推荐，有公司/职位/起止）或「真实经历」文本。"
                        "没有它无法生成简历，也不该编造。"}

    out = resume_builder.optimize_resume(job, prof, template_id,
                                         experiences=experiences)
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


@router.post("/rescore")
def rescore_all_jobs() -> Dict[str, Any]:
    """用当前画像**重算所有岗位的分数**。

    ## 为什么需要

    改了画像（方向/技能/城市）之后，**没被抓到的老岗位**分数还是旧的 ——
    `upsert()` 只在岗位被重新抓到时更新分数。

    实测踩到：方向从「web 前端」改成「跨境电商运营」后，
    杭州的 web 前端老岗位还留着 78 分，比新抓的运营岗（76）还高
    → **老岗位全挤在推荐前面**，跟用户改的方向完全对不上。

    改完画像点一下这个，就立刻按新画像重排，不用等下次抓取。
    """
    try:
        prof = _read_profile()
        try:
            experiences = _sibling("storage").list_experiences()
        except Exception:
            experiences = []
        n = _sibling("storage").rescore_all(prof, experiences=experiences)
        return {"ok": True, "rescored": n}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/cities")
def list_cities() -> Dict[str, Any]:
    """城市列表（城市名 → 码）。

    **前端给用户城市名，不给码** —— 用户不知道「南宁 = 3150」，但看得懂「南宁」。

    ## 两个站的码表**取并集**

    智联 3~4 位 `jl` 码、BOSS 9 位 `city` 码，**完全不是一个体系**
    （重庆：智联 551 / BOSS 101040100）。

    但**前端只关心城市名**（码是后端抓取时才翻译的），
    所以这里直接给**并集** —— 用户在设置页选「成都」，
    启用 BOSS 时用 BOSS 的码，启用智联时用智联的码。

    **某站没有的城市，那个站就跳过**（`cities_to_codes` 会过滤掉）。

    码都是**实测**出来的（不是抄的）：
    - 智联：逐个码跑真实抓取，看返回岗位的 `area` 城市名
    - BOSS：官方接口 `city/site.json` 交叉核对 + 逐个实测
    """
    try:
        cc = _sibling("city_codes")
        merged = {}
        try:
            bcc = _sibling("boss_city_codes")
        except Exception:
            bcc = None
        for src in (cc, bcc):
            if src is None:
                continue
            try:
                for item in src.known_cities():
                    merged[item["name"]] = item
            except Exception:
                continue
        cities = [merged[name] for name in sorted(merged)]
        return {"ok": True, "cities": cities}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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
    """结构化的经历列表（公司 / 起止 / 职位 / 分条）。

    **默认走 SQLite** —— 之前放在 mock 的内存里，
    进程重启就全丢，而且多条记录会共用空 id，
    新增一条就把旧的挤掉。
    """
    mock = _mock()
    if mock.enabled():
        return {"ok": True, "experiences": mock.experiences(), "mock": True}
    storage = _sibling("storage")
    return {"ok": True, "experiences": storage.list_experiences(), "mock": False}


@router.post("/experiences")
def save_experience(body: Dict[str, Any]) -> Dict[str, Any]:
    """新增或更新一条经历。

    **空 id 会生成新的** —— 前端新增时传 `id: ''`，
    直接拿它当主键会把同 id 的旧记录顶掉。
    """
    exp = body.get("experience") or {}
    if not (exp.get("company") or "").strip():
        return {"ok": False, "error": "缺少公司名"}
    bullets = [b for b in (exp.get("bullets") or []) if str(b).strip()]
    if not bullets:
        return {"ok": False, "error": "至少要有一条经历描述"}
    exp = dict(exp)
    exp["bullets"] = bullets

    mock = _mock()
    try:
        if mock.enabled():
            saved = mock.upsert_experience(exp)
        else:
            saved = _sibling("storage").upsert_experience(exp)
        return {"ok": True, "experience": saved}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.delete("/experiences/{exp_id}")
def delete_experience(exp_id: str) -> Dict[str, Any]:
    """删一条经历。"""
    mock = _mock()
    try:
        if mock.enabled():
            ok = mock.delete_experience(exp_id)
        else:
            ok = _sibling("storage").delete_experience(exp_id)
        return {"ok": ok}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── ③ 模板转换 ──────────────────────────────────────────────────────────────

@router.post("/templates/convert")
def convert_template(body: Dict[str, Any]) -> Dict[str, Any]:
    """上传模板文件 → 转成 CSS 模板 → 落盘 + 入库。

    body: {filename, data_base64, kind?, name?, description?, dry_run?}

    **转换全在本机完成，不调大模型** —— 简历内容不外传。
    .docx 走 zipfile+XML 抽版式参数，.pdf 抽页面尺寸，
    图片走「底图 + 文字层」。
    """
    filename = body.get("filename") or ""
    if not filename:
        return {"ok": False, "error": "缺少文件名"}

    store = _sibling("template_store")
    dry = bool(body.get("dry_run"))
    result = store.save_upload(
        filename,
        body.get("data_base64"),
        kind=body.get("kind"),
        name=body.get("name"),
        description=body.get("description"),
        dry_run=dry,
    )
    if not result.get("ok"):
        return result

    out = {
        "ok": True,
        "template": result["template"],
        "extracted": result.get("extracted") or [],
        "note": result.get("note") or "",
        "css_preview": result.get("css_preview") or "",
    }

    # **槽位规格 + 骨架** —— 前端要用来「点选槽位」。
    #
    # **只在 dry_run 时返回** —— 正式落盘时前端不需要再编辑一遍
    # （用户可能直接点「加入模板库」）。
    if dry:
        spec = result.get("spec")
        out["slots"] = None
        if spec:
            try:
                ts = _sibling("template_slots")
                out["slots"] = ts.spec_to_edit(spec)
                out["roles"] = ts.slot_role_labels()
            except Exception:
                out["slots"] = None

    # **dry_run 时返回渲染好的 HTML 预览** ——
    #
    # 用户反馈：「没有点击简历模板转换按钮，也无法预览所转换模板的样子」。
    #
    # dry_run 转换出的是 **CSS 片段** —— 光看 CSS 片段**看不出版式对不对**。
    # 这里用**用户的真实画像**渲染一遍，返回完整 HTML，
    # 前端弹窗显示 → 用户看完再决定「加入模板库」。
    #
    # **dry_run 不落盘** —— 用户不点确认就不会有垃圾模板。
    if dry:
        html = _render_preview(result["template"].get("template_id"),
                               css_override=result.get("css_preview") or "",
                               skeleton_override=result.get("skeleton") or "")
        if html:
            out["html_preview"] = html
    return out


@router.post("/templates/delete")
def delete_template(body: Dict[str, Any]) -> Dict[str, Any]:
    """删掉一个上传的模板（内置的不给删）。"""
    tid = body.get("template_id") or ""
    if not tid:
        return {"ok": False, "error": "缺少 template_id"}
    store = _sibling("template_store")
    return store.remove_upload(tid)

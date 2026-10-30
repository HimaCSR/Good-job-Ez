"""配置读写的单元测试 —— **不碰用户的真实 config.yaml**。

## 为什么单独一个文件

配置读写是**设置页能不能用**的最后一环，
出过两个**静默失效**的 bug：

1. **保存超时**（2026-10-30）—— 逐键调 `hermes config set`，
   一次约 2.2 秒；设置页把**整份配置**都发过来 → 15 个键 = 32 秒
   → **超过桌面端 30 秒超时** → 用户点了保存，**什么都没存上**，
   而且前端只弹一句「连接超时」，看不出是哪个键的问题。
   → 修法：**只写真正变了的键** + **并行执行**。

2. **YAML 引号脏值**（2026-10-30）—— `hermes config set` 写列表时，
   YAML 会给某些元素加引号（`06:20` 像时间戳 → 加引号）：

   ```
   scan_times:
     - 06:20
     - '11:20'
   ```

   **值本身是对的**（YAML 表示层的差异），但**读取端不剥引号**的话
   → cron 脚本读到 `"'11:20'"` → `parse_hhmm()` 失败
   → **那个时间点永远不会触发**（静默失效，用户完全看不出来）。

## 测什么

- `_as_list()` —— 各种形状的列表归一
- `_unquote()` —— YAML 引号剥离
- **写路径的「只写变化的键」** —— 用假 CLI 计数，**不真的调 CLI**
"""

import os
import sys
import types
import importlib.util
import unittest

_HERMES = os.environ.get("HERMES_HOME") or os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes")
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(os.path.dirname(_PLUGIN_DIR))


def _load_api():
    """把插件包当成 job_radar 导入。"""
    if "job_radar" not in sys.modules:
        pkg = types.ModuleType("job_radar")
        pkg.__path__ = [_PLUGIN_DIR]
        sys.modules["job_radar"] = pkg
    for name in ["config", "schemas", "tools", "storage", "report",
                 "matcher", "push", "login_check", "browser_cookies", "bbclient"]:
        key = "job_radar." + name
        if key in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(
            key, os.path.join(_PLUGIN_DIR, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    key = "job_radar.plugin_api"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            key, os.path.join(_PLUGIN_DIR, "dashboard", "plugin_api.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[key]


api = _load_api()


def _load_cron_script():
    """加载 cron 脚本（部署副本优先，找不到就用仓库里的 examples）。"""
    candidates = [
        os.path.join(_HERMES, "scripts", "job_radar_cron.py"),
        os.path.join(_REPO_ROOT, "examples", "job_radar_cron.py"),
    ]
    for path in candidates:
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location(
                "job_radar_cron_under_test", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise unittest.SkipTest("找不到 cron 脚本（examples/job_radar_cron.py）")


class TestAsList(unittest.TestCase):
    """`_as_list()` —— 把配置值归一成列表。"""

    def test_none_and_empty(self):
        self.assertEqual(api._as_list(None), [])
        self.assertEqual(api._as_list(""), [])
        self.assertEqual(api._as_list([]), [])

    def test_real_list(self):
        self.assertEqual(api._as_list(["a", "b"]), ["a", "b"])

    def test_comma_string(self):
        """CLI 回读列表有时是逗号分隔的字符串。"""
        self.assertEqual(api._as_list("a,b,c"), ["a", "b", "c"])

    def test_json_array_string(self):
        self.assertEqual(api._as_list('["a", "b"]'), ["a", "b"])

    def test_scalar_becomes_single_item(self):
        self.assertEqual(api._as_list("only"), ["only"])

    def test_strips_whitespace(self):
        self.assertEqual(api._as_list([" a ", " b "]), ["a", "b"])


class TestUnquote(unittest.TestCase):
    """cron 脚本的 `_unquote()` —— 剥 YAML 引号。"""

    def setUp(self):
        self.cron = _load_cron_script()

    def test_plain_value_unchanged(self):
        self.assertEqual(self.cron._unquote("09:00"), "09:00")

    def test_single_quotes_stripped(self):
        self.assertEqual(self.cron._unquote("'11:20'"), "11:20")

    def test_double_quotes_stripped(self):
        self.assertEqual(self.cron._unquote('"11:20"'), "11:20")

    def test_unbalanced_quote_kept(self):
        """**只剥成对的引号** —— "'abc" 不是合法的引号包裹。"""
        self.assertEqual(self.cron._unquote("'abc"), "'abc")

    def test_short_string_kept(self):
        self.assertEqual(self.cron._unquote("'"), "'")

    def test_empty(self):
        self.assertEqual(self.cron._unquote(""), "")


class TestScheduleParsingWithQuotedValues(unittest.TestCase):
    """**引号不剥 → 时间点永远不触发**（静默失效）。"""

    def setUp(self):
        self.cron = _load_cron_script()
        try:
            from job_radar import schedule as self_sched
        except ImportError:
            spec = importlib.util.spec_from_file_location(
                "job_radar.schedule", os.path.join(_PLUGIN_DIR, "schedule.py"))
            self_sched = importlib.util.module_from_spec(spec)
            sys.modules["job_radar.schedule"] = self_sched
            spec.loader.exec_module(self_sched)
        self.schedule = self_sched

    def test_unquoted_values_parse(self):
        for t in ["06:20", "11:20", "16:20"]:
            self.assertEqual(self.schedule.parse_hhmm(t), tuple(
                int(x) for x in t.split(":")))

    def test_quoted_values_would_fail_without_unquote(self):
        """**证明这个坑是真的** —— 不剥引号就解析不了。"""
        self.assertIsNone(self.schedule.parse_hhmm("'11:20'"))
        # 剥了就能解析
        self.assertEqual(
            self.schedule.parse_hhmm(self.cron._unquote("'11:20'")),
            (11, 20))


class TestWriteOnlyChangedKeys(unittest.TestCase):
    """**写路径：只写真正变了的键** —— 否则会超时。"""

    def setUp(self):
        self.calls = []
        self._orig_cli = api._hermes_cli
        self._orig_read = api._read_config_yaml
        api._hermes_cli = lambda: "fake-hermes"

    def tearDown(self):
        api._hermes_cli = self._orig_cli
        api._read_config_yaml = self._orig_read

    def _fake_read(self, current):
        api._read_config_yaml = lambda: dict(current)

    def _fake_run(self, cmd, **kw):
        """假装执行 CLI —— 记录调用，不真的写。"""
        self.calls.append(cmd)
        p = types.SimpleNamespace(returncode=0, stdout="ok", stderr="")
        return p

    def _patched(self, current):
        import subprocess
        self._fake_read(current)
        orig_run = subprocess.run
        subprocess.run = self._fake_run
        self.addCleanup(lambda: setattr(subprocess, "run", orig_run))

    def _written_keys(self):
        out = []
        for cmd in self.calls:
            # cmd = [cli, 'config', 'set', 'plugins...settings.<key>', value]
            for part in cmd:
                if str(part).startswith("plugins.entries.job-radar.settings."):
                    out.append(str(part).split("plugins.entries.job-radar.settings.")[1])
        return out

    def test_unchanged_settings_write_nothing(self):
        """**没改任何东西 → 一个键都不写** → 0 秒，不会超时。"""
        self._patched({"keywords": ["a"], "min_score": 40})
        api._write_config_settings({"keywords": ["a"], "min_score": 40})
        self.assertEqual(self._written_keys(), [],
                         "没变的东西不该写")

    def test_only_changed_key_is_written(self):
        """**只改一个时间点 → 只写那一个键** → 2.2 秒，稳稳的。"""
        self._patched({"keywords": ["a"], "scan_times": ["09:00"]})
        api._write_config_settings(
            {"keywords": ["a"], "scan_times": ["07:30", "12:30"]})
        self.assertEqual(self._written_keys(), ["scan_times"])

    def test_int_vs_str_not_treated_as_change(self):
        """**CLI 回读是 "653"（字符串），前端传回 653（int）** —— 不归一
        会误判成「变了」→ 白写一遍（每次 2.2 秒）。"""
        self._patched({"city": "653"})
        api._write_config_settings({"city": 653})
        self.assertEqual(self._written_keys(), [], "653 和 '653' 是同一个值")

    def test_list_order_matters(self):
        """**用户重排了列表顺序也算「变了」** —— 顺序有语义。"""
        self._patched({"scan_times": ["09:00", "17:00"]})
        api._write_config_settings({"scan_times": ["17:00", "09:00"]})
        self.assertEqual(self._written_keys(), ["scan_times"])

    def test_missing_key_is_written(self):
        """**磁盘上没有的键 → 要写**（比如新加的 scan_times）。"""
        self._patched({"keywords": ["a"]})
        api._write_config_settings({"keywords": ["a"], "scan_times": ["09:00"]})
        self.assertEqual(self._written_keys(), ["scan_times"])

    def test_bool_change_written(self):
        self._patched({"mock": False})
        api._write_config_settings({"mock": True})
        self.assertEqual(self._written_keys(), ["mock"])


class TestConfigDefaultsAligned(unittest.TestCase):
    """**三处默认值必须一致** —— 漏一个键 = 用户配了却看不到。"""

    def test_default_settings_has_all_keys(self):
        """`plugin_api.DEFAULT_SETTINGS` 不能漏键。"""
        for key in ("keywords", "city", "cities", "boss_city", "min_score",
                    "max_jobs_per_run", "sites", "request_gap_seconds",
                    "rounds_per_day", "push_max", "push_new_only",
                    "notify_on_failure", "active_hours",
                    # **下面两个是 2026-10-30 补上的** —— 漏了设置页读不到
                    "directions", "scan_times", "mock"):
            self.assertIn(key, api.DEFAULT_SETTINGS,
                          "DEFAULT_SETTINGS 漏了 %s" % key)

    def test_push_times_removed(self):
        """**`push_times` 不该再出现** —— 推送改成「抓完就推」。

        2026-10-30 用户决定：「推送时间与抓取完岗位后推送即可。」
        → 推送没有自己的时间点了。

        **`plugin.yaml` 里那个键留着**（兼容老配置，读到就忽略），
        但 **`DEFAULT_SETTINGS` / `config.load_config()` 里不能有** ——
        否则设置页又会显示出一个「推送时间」输入框。
        """
        self.assertNotIn("push_times", api.DEFAULT_SETTINGS,
                         "推送已经没有独立时间点了，别放回默认配置")
        cfg = api._sibling("config") if hasattr(api, "_sibling") else None
        if cfg is not None:
            self.assertNotIn("push_times", cfg._defaults())
            # **有 ctx 的分支也不能有** —— 两个分支的键必须一致
            class _Ctx:
                def get_config(self, key, default=None):
                    return default
            cfg.set_context(_Ctx())
            try:
                self.assertNotIn("push_times", cfg.load_config())
            finally:
                cfg.set_context(None)

    def test_push_max_consistent(self):
        """**`push_max` 三处默认值必须一致**（历史上是 3/3/5）。"""
        self.assertEqual(api.DEFAULT_SETTINGS["push_max"], 5)
        cfg = api._sibling("config") if hasattr(api, "_sibling") else None
        if cfg is not None:
            self.assertEqual(cfg._defaults()["push_max"], 5)

    def test_plugin_yaml_schema_has_time_keys(self):
        """`plugin.yaml` 的 config_schema 是权威来源 —— 别漏键。"""
        path = os.path.join(_PLUGIN_DIR, "plugin.yaml")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for key in ("scan_times:", "directions:", "push_max:"):
            self.assertIn(key, text, "plugin.yaml 漏了 %s" % key)
        # **`push_times` 留着只为兼容老配置** —— 描述里要写明「已废弃」
        self.assertIn("push_times:", text)
        self.assertIn("已废弃", text)


if __name__ == "__main__":
    unittest.main()

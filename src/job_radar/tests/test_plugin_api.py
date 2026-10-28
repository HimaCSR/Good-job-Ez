"""设置页后端 API 的单元测试。

只测纯函数和读路径 —— **不测写路径**。
写路径会改 config.yaml，测试里跑会污染用户的真实配置。
写路径靠集成测试（手动跑）验证。

跑法：
    cd src/job_radar && python -m unittest discover -s tests
"""

import os
import sys
import types
import importlib.util
import unittest

_HERMES = os.environ.get("HERMES_HOME") or os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes")
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_api():
    """把插件包当成 job_radar 导入，让相对 import（from . import storage）能用。"""
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


class TestSiblingModules(unittest.TestCase):
    """每个 `_sibling("X")` 用到的模块，**必须在 `_SIBLINGS` 里注册**。

    ## 为什么需要这个

    `_sibling()` 查的是 `_SIBLING_MODULES` 字典 ——
    字典里没有的模块会抛 ImportError：

        ImportError: job-radar 兄弟模块 template_store.py 加载失败

    本机踩过：加了 `template_convert` / `template_store` 两个模块，
    写完 API 就以为好了 —— **但忘了注册**，
    模板上传功能在后端直接 500。

    **代码完全正常、单测也过**（因为没人调那个端点），
    只有真点「上传模板」才会炸。
    """

    def _api_source(self):
        path = os.path.join(_PLUGIN_DIR, "dashboard", "plugin_api.py")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_all_siblings_registered(self):
        import re
        src = self._api_source()

        m = re.search(r"_SIBLINGS\s*=\s*\((.*?)\n\)", src, re.S)
        self.assertIsNotNone(m, "找不到 _SIBLINGS 定义")
        registered = set(re.findall(r'"([\w]+)"', m.group(1)))

        used = set(re.findall(r'_sibling\(\s*"([\w]+)"\s*\)', src))
        self.assertTrue(used, "没找到任何 _sibling 调用")

        missing = sorted(used - registered)
        self.assertEqual(
            missing, [],
            "这些模块被 _sibling() 用了但没在 _SIBLINGS 里注册 —— "
            "调用时会抛 ImportError：%s" % missing)

    def test_registered_modules_exist(self):
        """注册了但文件不存在 —— 加载时会跳过，_sibling 会抛。"""
        import re
        src = self._api_source()
        m = re.search(r"_SIBLINGS\s*=\s*\((.*?)\n\)", src, re.S)
        registered = re.findall(r'"([\w]+)"', m.group(1))
        missing = [n for n in registered
                   if not os.path.exists(os.path.join(_PLUGIN_DIR, n + ".py"))]
        self.assertEqual(missing, [], "注册了但文件不存在：%s" % missing)

    def test_known_modules_present(self):
        """关键的模块不能被误删。"""
        import re
        src = self._api_source()
        m = re.search(r"_SIBLINGS\s*=\s*\((.*?)\n\)", src, re.S)
        registered = set(re.findall(r'"([\w]+)"', m.group(1)))
        for name in ("storage", "resume_import", "resume_template",
                     "template_convert", "template_store", "apply_gate",
                     "browser_session", "mock_provider"):
            self.assertIn(name, registered,
                          "%s 必须注册为兄弟模块" % name)


class TestHotReload(unittest.TestCase):
    """开发模式热重载。

    ## 为什么

    **Python 模块一旦 import 就固定了。** 改了源码，跑着的进程
    还在用旧代码 —— 本机踩过：加了 `.md` 支持，源文件改对了，
    但插件 API 进程是 16:11 起的，它 import 的是 16:11 的版本，
    于是用户看到「不支持的格式：.md」。

    前端有 fs-watch 能热重载，**后端没有** ——
    不加这个的话每改一次后端就要重启整个 Hermes。
    """

    def test_hot_reload_detects_dev_link(self):
        """插件目录是软链/junction → 自动开热重载。

        测试里 `_PLUGIN_ROOT` 是仓库路径（不是软链），
        所以这里**造一个软链目录**来验判据本身。
        """
        import shutil
        import tempfile

        api = _load_api()
        real = os.path.join(tempfile.gettempdir(), "jr-reload-target")
        link = os.path.join(tempfile.gettempdir(), "jr-reload-link")
        shutil.rmtree(real, ignore_errors=True)
        shutil.rmtree(link, ignore_errors=True)
        os.makedirs(real, exist_ok=True)
        try:
            os.symlink(real, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("这个平台不支持建软链")
        try:
            old_root = api._PLUGIN_ROOT
            api._PLUGIN_ROOT = link
            try:
                self.assertTrue(api._dev_hot_reload(),
                                "软链目录应该自动开热重载")
            finally:
                api._PLUGIN_ROOT = old_root
        finally:
            shutil.rmtree(link, ignore_errors=True)
            shutil.rmtree(real, ignore_errors=True)

    def test_hot_reload_off_by_env(self):
        """`JOB_RADAR_HOT_RELOAD=0` 显式关。"""
        api = _load_api()
        old = os.environ.get("JOB_RADAR_HOT_RELOAD")
        os.environ["JOB_RADAR_HOT_RELOAD"] = "0"
        try:
            self.assertFalse(api._dev_hot_reload())
        finally:
            if old is None:
                os.environ.pop("JOB_RADAR_HOT_RELOAD", None)
            else:
                os.environ["JOB_RADAR_HOT_RELOAD"] = old

    def test_reload_sibling_reloads_module(self):
        """`_reload_sibling` 真的重新 import 了模块。"""
        import shutil
        import tempfile

        api = _load_api()
        tmp = tempfile.mkdtemp(prefix="jr-reload-")
        try:
            mod_path = os.path.join(tmp, "reload_probe.py")
            with open(mod_path, "w", encoding="utf-8") as fh:
                fh.write("VALUE = 1\n")

            old_root = api._PLUGIN_ROOT
            api._PLUGIN_ROOT = tmp
            try:
                first = api._reload_sibling("reload_probe")
                self.assertIsNotNone(first)
                self.assertEqual(first.VALUE, 1)

                # 改文件 → 再 reload → 拿到新值
                with open(mod_path, "w", encoding="utf-8") as fh:
                    fh.write("VALUE = 2\n")
                os.utime(mod_path, (0, 0))     # 确保 mtime 变了
                second = api._reload_sibling("reload_probe")
                self.assertIsNotNone(second)
                self.assertEqual(second.VALUE, 2)
            finally:
                api._PLUGIN_ROOT = old_root
                api._SIBLING_MODULES.pop("reload_probe", None)
                api._SIBLING_MTIMES.pop("reload_probe", None)
                sys.modules.pop("job_radar.reload_probe", None)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestPaths(unittest.TestCase):

    def test_hermes_home_from_env(self):
        home = api._hermes_home()
        self.assertTrue(os.path.isabs(home), home)
        self.assertIn("hermes", home.lower())

    def test_plugin_dir_under_hermes_home(self):
        self.assertTrue(api._plugin_dir().startswith(api._hermes_home()))


class TestCliValue(unittest.TestCase):

    def test_bool_and_number(self):
        # _cli_value 返回的是「给 CLI 的字符串」，不是 Python 值
        self.assertEqual(api._cli_value(True), "true")
        self.assertEqual(api._cli_value(False), "false")
        self.assertEqual(api._cli_value(5), "5")
        self.assertEqual(api._cli_value(5.5), "5.5")

    def test_list_is_json(self):
        out = api._cli_value(["前端", "vue"])
        self.assertIn("前端", out)
        self.assertTrue(out.startswith("["))


class TestNormalizeJob(unittest.TestCase):

    def test_json_string_fields_become_lists(self):
        job = {"job_id": "x", "skills": '["vue","css"]',
               "reasons": '["城市符合"]', "missing": "[]"}
        out = api._normalize_job(job)
        self.assertEqual(out["skills"], ["vue", "css"])
        self.assertEqual(out["reasons"], ["城市符合"])
        self.assertEqual(out["missing"], [])

    def test_none_fields_become_lists(self):
        out = api._normalize_job({"job_id": "x"})
        self.assertEqual(out["skills"], [])
        self.assertEqual(out["reasons"], [])
        self.assertEqual(out["missing"], [])

    def test_area_and_city_mirror_each_other(self):
        out = api._normalize_job({"area": "杭州 西湖"})
        self.assertEqual(out["city"], "杭州 西湖")
        out2 = api._normalize_job({"city": "上海 徐汇"})
        self.assertEqual(out2["area"], "上海 徐汇")


class TestProfileRead(unittest.TestCase):

    def test_profile_has_expected_keys(self):
        prof = api._read_profile()
        for key in ("title_keywords", "skills", "cities", "min_salary",
                    "identity", "experience_text"):
            self.assertIn(key, prof)


if __name__ == "__main__":
    unittest.main(verbosity=2)

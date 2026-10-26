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

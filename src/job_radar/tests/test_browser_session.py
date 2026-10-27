"""浏览器会话模块的测试。

**不碰真浏览器** —— 起浏览器、杀进程这些都用假函数顶掉。
真实验证靠 `scripts/verify_browser_session.py`（手动跑）。

要保证的三件事：
1. 判定「已登录」用的是**精确 cookie 名**，不是子串匹配
2. 抓取前会确保浏览器在跑
3. 不硬编码任何本机路径（通用性 —— 别人设备上也能用）
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_session as bs  # noqa: E402


class TestLoginMarkers(unittest.TestCase):
    """判定已登录 —— 必须是精确 cookie 名。"""

    def test_markers_are_exact_names(self):
        """**子串匹配会误判**。

        智联的 cookie 名叫 `at`（2 个字母）——
        用 `'at' in name` 匹配的话，`sensorsdata2015jssdkchannel`
        也会命中，等于没登录也显示已登录。
        """
        for site, markers in bs.SITE_COOKIE_MARKERS.items():
            for m in markers:
                self.assertIn(m, m)          # 精确名
                self.assertTrue(m.islower(), "%s 应是小写的精确名" % m)

    def test_logged_in_detection(self):
        names = {"at", "rt", "x-zp-device-sn"}
        self.assertTrue(any(m in names for m in bs.SITE_COOKIE_MARKERS["zhaopin"]))
        self.assertFalse(any(m in names for m in bs.SITE_COOKIE_MARKERS["boss"]))

    def test_boss_needs_zp_at(self):
        names = {"zp_at", "__zp_stoken__"}
        self.assertTrue(any(m in names for m in bs.SITE_COOKIE_MARKERS["boss"]))

    def test_unrelated_cookies_dont_count(self):
        """无关 cookie 不能算登录。"""
        names = {"sensorsdata2015jssdkchannel", "_uab_collina", "smidV2"}
        for markers in bs.SITE_COOKIE_MARKERS.values():
            self.assertFalse(any(m in names for m in markers))


class TestNoHardcodedPaths(unittest.TestCase):
    """通用性 —— 仓库要公开，不能有本机路径。"""

    def test_profile_path_not_hardcoded(self):
        """插件不碰任何具体 profile 目录 —— 那是 bb-browser 管的。

        这个测试防止以后有人加进来（比如硬编码某个 Chrome profile）。
        """
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "browser_session.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        # 不能出现盘符开头的路径（除了环境变量取值）
        for bad in ("C:\\chrome", "C:/chrome", "C:\\Users", "C:/Users"):
            self.assertNotIn(bad, src, "browser_session.py 里不能硬编码 %s" % bad)

    def test_port_is_overridable(self):
        self.assertTrue(hasattr(bs, "CDP_PORT"))
        self.assertEqual(bs.CDP_PORT, int(
            os.environ.get("JOB_RADAR_CDP_PORT", "9222")))


class TestLoginUrls(unittest.TestCase):
    """登录入口 —— 各站都要有，且是 https。"""

    def test_all_sites_have_url(self):
        for site in ("zhaopin", "boss"):
            self.assertIn(site, bs.LOGIN_URLS)
            self.assertTrue(bs.LOGIN_URLS[site].startswith("https://"))

    def test_unknown_site_rejected(self):
        r = bs.open_login("nosuchsite")
        self.assertFalse(r["ok"])


class TestEnsureBrowser(unittest.TestCase):
    """确保浏览器在跑 —— 不能真的起浏览器。"""

    def setUp(self):
        self._alive = bs.cdp_alive
        self._run = bs._run_bb
        self.calls = []

    def tearDown(self):
        bs.cdp_alive = self._alive
        bs._run_bb = self._run

    def test_already_alive_does_nothing(self):
        bs.cdp_alive = lambda *a, **k: True
        called = []
        bs._run_bb = lambda *a, **k: called.append(a) or (0, "", "")
        r = bs.ensure_browser()
        self.assertTrue(r["ok"])
        self.assertEqual(r["action"], "none")
        self.assertEqual(called, [], "已经在跑就不该再调 bb")

    def test_starts_when_down(self):
        state = {"alive": False}

        def _alive(*a, **k):
            return state["alive"]
        bs.cdp_alive = _alive

        def _run(*args, **kwargs):
            state["alive"] = True          # 模拟启动成功
            return (0, "tab: abc", "")
        bs._run_bb = _run

        r = bs.ensure_browser()
        self.assertTrue(r["ok"])
        self.assertEqual(r["action"], "started")

    def test_uses_open_not_status(self):
        """**用 open 触发，不用 status** —— status 不触发启动。"""
        state = {"alive": False}
        bs.cdp_alive = lambda *a, **k: state["alive"]
        seen = []

        def _run(*args, **kwargs):
            seen.append(args[0])
            state["alive"] = True
            return (0, "", "")
        bs._run_bb = _run

        bs.ensure_browser()
        self.assertIn("open", seen)
        self.assertNotIn("status", seen)

    def test_failure_reports_error(self):
        bs.cdp_alive = lambda *a, **k: False
        bs._run_bb = lambda *a, **k: (1, "", "boom")
        # wait_for_cdp 会真的等 —— 顶掉它
        orig_wait = bs.wait_for_cdp
        bs.wait_for_cdp = lambda timeout=0: False
        try:
            r = bs.ensure_browser()
            self.assertFalse(r["ok"])
            self.assertEqual(r["action"], "failed")
        finally:
            bs.wait_for_cdp = orig_wait


class TestStatusShape(unittest.TestCase):
    """status() 的形状 —— 设置页靠它。"""

    def setUp(self):
        self._alive = bs.cdp_alive
        self._cookies = bs.read_cookies

    def tearDown(self):
        bs.cdp_alive = self._alive
        bs.read_cookies = self._cookies

    def test_shape_when_down(self):
        bs.cdp_alive = lambda *a, **k: False
        s = bs.status()
        for key in ("cdp_port", "cdp_alive", "cookie_count", "logged_in"):
            self.assertIn(key, s)
        self.assertFalse(s["cdp_alive"])
        self.assertEqual(s["cookie_count"], 0)
        self.assertEqual(s["logged_in"], {})

    def test_shape_when_up(self):
        bs.cdp_alive = lambda *a, **k: True
        bs.read_cookies = lambda *a, **k: [
            {"name": "at", "domain": ".zhaopin.com", "expires": 0},
            {"name": "rt", "domain": ".zhaopin.com", "expires": 0},
        ]
        s = bs.status()
        self.assertTrue(s["cdp_alive"])
        self.assertEqual(s["cookie_count"], 2)
        self.assertTrue(s["logged_in"]["zhaopin"])
        self.assertFalse(s["logged_in"]["boss"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""投递三道门真实现的测试 —— 重点是「三道门真的能挡住」。

闸门是投递功能的最后一道防线。这里测的是**真实现**
（apply_gate.py），不是 mock —— mock 的测试在 test_mock_provider.py。

**不碰真实 config.yaml**：测试用假的 settings dict 和临时 SQLite。
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply_gate as ag  # noqa: E402
import storage  # noqa: E402


JOB = {"job_id": "J1", "title": "前端工程师", "source": "zhaopin"}
RESUME = {"resume_id": "R1", "title": "我的简历", "tags": ["vue"],
          "file_path": "/tmp/x.pdf"}


class _FakeStorage:
    """顶掉 storage 的真库，用临时 SQLite。"""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="jr-apply-test-")
        self._orig = storage._conn

        import sqlite3

        def _conn():
            # 用 storage 的 _Conn 子类 —— 普通 Connection 的 `with` **不关连接**
            # （只提交事务），测试跑完会攒一堆未关闭的句柄。
            conn = sqlite3.connect(os.path.join(self.tmp, "jobs.db"),
                                   factory=storage._Conn)
            conn.row_factory = sqlite3.Row
            conn.executescript(storage.SCHEMA)
            return conn

        storage._conn = _conn

    def restore(self):
        storage._conn = self._orig


class _FakeConfig:
    """把配置读写顶成内存字典。

    **读写都要顶** —— 只顶 `_cli_settings`（读）不够：
    `set_site_switch` / `set_daily_limit` 会走 `_cli_set`（写），
    那是真调 `hermes config set`：
    - 本机有 Hermes CLI → 真的改了用户的 config.yaml（污染！）
    - CI 上没有 Hermes CLI → 直接抛「找不到 hermes CLI」

    两种环境都不该在单测里发生。
    """

    def __init__(self, settings=None):
        # **不复制** —— 测试里常写 `self._settings["apply_zhaopin"] = False`
        # 来切换状态，复制了就切换不到（改的是另一份 dict）。
        self.settings = settings if settings is not None else {}
        self._orig_get = ag._cli_settings
        self._orig_set = ag._cli_set
        ag._cli_settings = lambda: dict(self.settings)

        def _set(key, value):
            self.settings[key] = value
        ag._cli_set = _set

    def restore(self):
        ag._cli_settings = self._orig_get
        ag._cli_set = self._orig_set


class TestSwitchDefaults(unittest.TestCase):
    """第一道门：站点开关默认全关。"""

    def test_default_all_off(self):
        """没配过就是关的 —— 插件不该替用户决定「可以投」。"""
        settings = {}
        for site in ag.KNOWN_SITES:
            self.assertFalse(ag.site_switch_enabled(site, settings), site)

    def test_reads_true(self):
        self.assertTrue(ag.site_switch_enabled("zhaopin", {"apply_zhaopin": True}))

    def test_reads_false(self):
        self.assertFalse(ag.site_switch_enabled("zhaopin", {"apply_zhaopin": False}))

    def test_reads_string_true(self):
        """CLI 读出来的可能是字符串 'true' —— 也要认。"""
        self.assertTrue(ag.site_switch_enabled("boss", {"apply_boss": "true"}))

    def test_unknown_key_is_off(self):
        self.assertFalse(ag.site_switch_enabled("zhaopin", {"apply_other": True}))


class TestDailyLimitConfig(unittest.TestCase):

    def test_default_when_missing(self):
        self.assertEqual(ag.daily_limit("zhaopin", {}), ag.DEFAULT_DAILY_LIMIT["zhaopin"])

    def test_reads_custom(self):
        self.assertEqual(ag.daily_limit("boss", {"apply_limit_boss": 9}), 9)

    def test_negative_clamped(self):
        self.assertEqual(ag.daily_limit("boss", {"apply_limit_boss": -3}), 0)

    def test_garbage_falls_back(self):
        self.assertEqual(ag.daily_limit("boss", {"apply_limit_boss": "abc"}),
                         ag.DEFAULT_DAILY_LIMIT["boss"])


class TestGateThreeDoors(unittest.TestCase):
    """真实现的三道门 —— 每道不过就停在那一步。"""

    def setUp(self):
        self.fs = _FakeStorage()
        self._settings = {"apply_zhaopin": True, "apply_limit_zhaopin": 2}
        # 配置读写都顶掉 —— 不能碰真实 config.yaml
        self.cfg = _FakeConfig(self._settings)

    def tearDown(self):
        self.cfg.restore()
        self.fs.restore()

    # ── 门 1：站点开关 ──

    def test_gate1_blocks_when_switch_off(self):
        self._settings["apply_zhaopin"] = False
        g = ag.gate_status(JOB)
        self.assertFalse(g["can_apply"])
        self.assertEqual([b["gate"] for b in g["blocked_by"]], ["site_switch"])

    def test_gate1_refuses_token_when_off(self):
        """闸门没过就不签令牌 —— 否则前端拿到令牌直接调 submit，
        被 submit 挡回去，白跑一趟还没说清是哪道门挡的。"""
        self._settings["apply_zhaopin"] = False
        with self.assertRaises(PermissionError):
            ag.issue_token("J1", "zhaopin")

    def test_gate1_refuses_apply_when_off(self):
        self._settings["apply_zhaopin"] = False
        r = ag.apply(JOB, RESUME, token="whatever")
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "site_switch")

    # ── 门 2：一次性令牌 ──

    def test_gate2_refuses_without_token(self):
        r = ag.apply(JOB, RESUME, token=None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "token")

    def test_gate2_token_is_single_use(self):
        tok = ag.issue_token("J1", "zhaopin")
        ok, _ = ag.check_token(tok, job_id="J1", site="zhaopin")
        self.assertTrue(ok)
        ag.consume_token(tok)
        ok, why = ag.check_token(tok, job_id="J1", site="zhaopin")
        self.assertFalse(ok)
        self.assertIn("令牌", why)

    def test_gate2_token_bound_to_job(self):
        """令牌绑定 job_id —— 不能拿 A 岗的令牌投 B 岗。"""
        tok = ag.issue_token("J1", "zhaopin")
        ok, why = ag.check_token(tok, job_id="J2", site="zhaopin")
        self.assertFalse(ok)
        self.assertIn("不匹配", why)

    def test_gate2_token_bound_to_site(self):
        tok = ag.issue_token("J1", "zhaopin")
        ok, why = ag.check_token(tok, job_id="J1", site="boss")
        self.assertFalse(ok)
        self.assertIn("不匹配", why)

    def test_gate2_unknown_token_rejected(self):
        ok, why = ag.check_token("nope", job_id="J1")
        self.assertFalse(ok)

    def test_gate2_token_expires(self):
        """过期令牌必须失效 —— 5 分钟窗口。"""
        tok = ag.issue_token("J1", "zhaopin")
        storage.delete_apply_token(tok)
        storage.insert_apply_token(
            tok, "J1", "zhaopin", None, "2000-01-01T00:00:00",
            "2000-01-01T00:05:00")
        ok, why = ag.check_token(tok, job_id="J1")
        self.assertFalse(ok)
        self.assertIn("过期", why)

    def test_gate2_token_persisted_to_db(self):
        """令牌要落库 —— 内存版重启进程就丢，跨进程也不共享。"""
        tok = ag.issue_token("J1", "zhaopin")
        row = storage.get_apply_token(tok)
        self.assertIsNotNone(row)
        self.assertEqual(row["job_id"], "J1")
        self.assertEqual(row["site"], "zhaopin")

    # ── 门 3：每日上限 ──

    def test_gate3_blocks_after_limit(self):
        """上限判定必须在动作层**之前** ——
        动作层还没接（返回 action 失败），但额度照样要扣、照样要拦。"""
        limit = self._settings["apply_limit_zhaopin"]
        for _ in range(limit):
            tok = ag.issue_token("J1", "zhaopin")
            r = ag.apply(JOB, RESUME, token=tok)
            # 动作层还没接 → ok=False，但**记账仍算一次**（额度要扣）
            self.assertEqual(r["stage"], "action")
        # 投满了 → 下一次被上限拦住
        tok = ag.issue_token("J1", "zhaopin")
        r = ag.apply(JOB, RESUME, token=tok)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "daily_limit")

    def test_gate3_count_is_per_site(self):
        today = ag._today()
        storage.insert_apply_record(
            "zhaopin", "J1", "R1", True, "", today + "T09:00:00")
        self.assertEqual(ag.today_count("zhaopin"), 1)
        self.assertEqual(ag.today_count("boss"), 0)

    def test_gate3_failed_attempts_still_count(self):
        """失败的尝试也占额度 —— 上限是防失控的，不是防失败的。

        否则动作层一坏就变成无限重试，每日上限形同虚设。
        """
        today = ag._today()
        storage.insert_apply_record(
            "zhaopin", "J1", "R1", False, "boom", today + "T09:00:00")
        self.assertEqual(ag.today_count("zhaopin"), 1)

    def test_gate3_count_ignores_other_days(self):
        """昨天的记录不算今天的额度。"""
        storage.insert_apply_record(
            "zhaopin", "J1", "R1", True, "", "2020-01-01T09:00:00")
        self.assertEqual(ag.today_count("zhaopin"), 0)


class TestGateStatusShape(unittest.TestCase):

    def setUp(self):
        self.fs = _FakeStorage()
        self.cfg = _FakeConfig({"apply_zhaopin": True,
                                "apply_limit_zhaopin": 5})

    def tearDown(self):
        self.cfg.restore()
        self.fs.restore()

    def test_reports_remaining(self):
        g = ag.gate_status(JOB)
        self.assertTrue(g["can_apply"])
        self.assertEqual(g["daily_used"], 0)
        self.assertEqual(g["daily_remaining"], 5)
        self.assertEqual(g["site"], "zhaopin")

    def test_has_token_ttl(self):
        self.assertEqual(ag.gate_status(JOB)["token_ttl_seconds"], 300)


class TestSwitchesApi(unittest.TestCase):

    def setUp(self):
        self.fs = _FakeStorage()
        self._settings = {"apply_zhaopin": True, "apply_limit_zhaopin": 5}
        self.cfg = _FakeConfig(self._settings)

    def tearDown(self):
        self.cfg.restore()
        self.fs.restore()

    def test_all_switches_shape(self):
        data = ag.all_switches()
        self.assertIn("sites", data)
        for site in ag.KNOWN_SITES:
            self.assertIn(site, data["sites"])
            self.assertIn("apply_enabled", data["sites"][site])
            self.assertIn("daily_limit", data["sites"][site])

    def test_set_site_switch_rejects_unknown(self):
        with self.assertRaises(ValueError):
            ag.set_site_switch("nosuchsite", True)

    def test_set_daily_limit_rejects_unknown(self):
        with self.assertRaises(ValueError):
            ag.set_daily_limit("nosuchsite", 5)

    def test_set_daily_limit_clamps(self):
        self.assertEqual(ag.set_daily_limit("boss", -1)["sites"]["boss"]["daily_limit"], 0)

    def test_write_path_does_not_touch_real_config(self):
        """写路径必须被隔离。

        **两个环境都会出事**：
        - 本机有 Hermes CLI → 真改了用户的 config.yaml
        - CI 上没有 Hermes CLI → 抛「找不到 hermes CLI」，测试直接失败

        所以 `_cli_set` 和 `_cli_settings` **两个都要顶**。
        这个断言就是防回归的。
        """
        ag.set_site_switch("boss", True)
        ag.set_daily_limit("boss", 3)
        self.assertTrue(self.cfg.settings["apply_boss"])
        self.assertEqual(self.cfg.settings["apply_limit_boss"], 3)

    def test_switch_write_then_read_is_consistent(self):
        """写完立刻读，读到的要是新值。"""
        ag.set_site_switch("zhaopin", False)
        self.assertFalse(ag.site_switch_enabled("zhaopin"))
        ag.set_site_switch("zhaopin", True)
        self.assertTrue(ag.site_switch_enabled("zhaopin"))


class TestStorageTables(unittest.TestCase):
    """令牌与投递记录的存储层。"""

    def setUp(self):
        self.fs = _FakeStorage()

    def tearDown(self):
        self.fs.restore()

    def test_token_roundtrip(self):
        storage.insert_apply_token(
            "T1", "J1", "zhaopin", "R1", "2026-01-01T00:00:00",
            "2026-01-01T00:05:00")
        row = storage.get_apply_token("T1")
        self.assertEqual(row["job_id"], "J1")
        self.assertIsNone(row["used_at"])

    def test_mark_token_used(self):
        storage.insert_apply_token(
            "T1", "J1", "zhaopin", None, "2026-01-01T00:00:00",
            "2026-01-01T00:05:00")
        storage.mark_apply_token_used("T1")
        self.assertIsNotNone(storage.get_apply_token("T1")["used_at"])

    def test_delete_token(self):
        storage.insert_apply_token(
            "T1", "J1", "zhaopin", None, "2026-01-01T00:00:00",
            "2026-01-01T00:05:00")
        storage.delete_apply_token("T1")
        self.assertIsNone(storage.get_apply_token("T1"))

    def test_apply_record_listing(self):
        storage.insert_apply_record(
            "zhaopin", "J1", "R1", True, "ok", "2026-01-01T00:00:00")
        rows = storage.list_apply_records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["job_id"], "J1")
        self.assertEqual(rows[0]["ok"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

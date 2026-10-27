"""Mock 层的测试 —— 重点是「三道门真的能挡住」。

闸门是投递功能的最后一道防线：如果 mock 层挡不住，
后面换真实现时很容易把闸门做漏。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mock_provider as mp  # noqa: E402


JOB = {"job_id": "J1", "title": "前端工程师", "source": "zhaopin"}
RESUME = {"resume_id": "R1", "title": "我的简历", "tags": ["vue"]}


class TestMockSwitch(unittest.TestCase):

    def setUp(self):
        mp.reset()
        mp.SITE_APPLY_ENABLED["zhaopin"] = False
        mp.SITE_APPLY_ENABLED["boss"] = False
        mp.SITE_APPLY_ENABLED["huibo"] = False

    def tearDown(self):
        mp.reset()

    def test_disabled_by_default(self):
        """投递开关默认全是关的 —— 这就是第一道门存在的意义。"""
        for site in ("zhaopin", "boss", "huibo"):
            self.assertFalse(mp.SITE_APPLY_ENABLED[site], site)

    def test_env_switch(self):
        self.assertFalse(mp.enabled())
        self.assertTrue(mp.enabled(force=True))
        self.assertFalse(mp.enabled(force=False))


class TestGate1SiteSwitch(unittest.TestCase):
    def setUp(self):
        mp.reset()

    def tearDown(self):
        mp.reset()


    def test_blocked_when_switch_off(self):
        g = mp.gate_status(JOB)
        self.assertFalse(g["can_apply"])
        self.assertEqual([b["gate"] for b in g["blocked_by"]], ["site_switch"])

    def test_token_refused_when_switch_off(self):
        """闸门没过就不该签发令牌 —— 否则前端拿到令牌直接调 submit，
        被 submit 挡回去，白跑一趟还没说清是哪道门挡的。"""
        with self.assertRaises(PermissionError):
            mp.issue_token("J1", "zhaopin")

    def test_apply_refused_when_switch_off(self):
        r = mp.mock_apply(JOB, RESUME, token="whatever")
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "site_switch")

    def test_passes_when_switch_on(self):
        mp.SITE_APPLY_ENABLED["zhaopin"] = True
        g = mp.gate_status(JOB)
        self.assertTrue(g["can_apply"])


class TestGate2Token(unittest.TestCase):

    def setUp(self):
        mp.reset()
        mp.SITE_APPLY_ENABLED["zhaopin"] = True

    def tearDown(self):
        mp.reset()

    def test_token_is_single_use(self):
        tok = mp.issue_token("J1", "zhaopin")
        ok, _ = mp.check_token(tok, job_id="J1", site="zhaopin")
        self.assertTrue(ok)
        mp.consume_token(tok)
        ok, why = mp.check_token(tok, job_id="J1", site="zhaopin")
        self.assertFalse(ok)
        self.assertIn("令牌", why)

    def test_token_bound_to_job(self):
        """令牌绑定 job_id —— 不能拿 A 岗的令牌投 B 岗。"""
        tok = mp.issue_token("J1", "zhaopin")
        ok, why = mp.check_token(tok, job_id="J2", site="zhaopin")
        self.assertFalse(ok)
        self.assertIn("不匹配", why)

    def test_token_bound_to_site(self):
        tok = mp.issue_token("J1", "zhaopin")
        ok, why = mp.check_token(tok, job_id="J1", site="boss")
        self.assertFalse(ok)
        self.assertIn("不匹配", why)

    def test_unknown_token_rejected(self):
        ok, why = mp.check_token("nope", job_id="J1")
        self.assertFalse(ok)

    def test_token_expires(self):
        """过期令牌必须失效 —— 5 分钟窗口。"""
        tok = mp.issue_token("J1", "zhaopin")
        # 手工把过期时间挪到过去
        mp._TOKENS[tok]["expires_at"] = "2000-01-01T00:00:00"
        ok, why = mp.check_token(tok, job_id="J1")
        self.assertFalse(ok)
        self.assertIn("过期", why)

    def test_apply_without_token_refused(self):
        r = mp.mock_apply(JOB, RESUME, token=None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "token")


class TestGate3DailyLimit(unittest.TestCase):

    def setUp(self):
        mp.reset()
        mp.SITE_APPLY_ENABLED["zhaopin"] = True

    def tearDown(self):
        mp.reset()

    def test_limit_blocks_after_n(self):
        limit = mp.SITE_DAILY_LIMIT["zhaopin"]
        for _ in range(limit):
            tok = mp.issue_token("J1", "zhaopin")
            r = mp.mock_apply(JOB, RESUME, token=tok)
            self.assertTrue(r["ok"])
        # 超出
        tok = mp.issue_token("J1", "zhaopin")
        r = mp.mock_apply(JOB, RESUME, token=tok)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "daily_limit")

    def test_gate_reports_remaining(self):
        g = mp.gate_status(JOB)
        self.assertEqual(g["daily_remaining"], g["daily_limit"])
        tok = mp.issue_token("J1", "zhaopin")
        mp.mock_apply(JOB, RESUME, token=tok)
        g = mp.gate_status(JOB)
        self.assertEqual(g["daily_used"], 1)
        self.assertEqual(g["daily_remaining"], g["daily_limit"] - 1)

    def test_limit_is_per_site(self):
        """一个站投满了，不影响另一个站。"""
        limit = mp.SITE_DAILY_LIMIT["zhaopin"]
        for _ in range(limit):
            tok = mp.issue_token("J1", "zhaopin")
            mp.mock_apply(JOB, RESUME, token=tok)
        mp.SITE_APPLY_ENABLED["boss"] = True
        boss_job = dict(JOB, source="boss")
        g = mp.gate_status(boss_job)
        self.assertTrue(g["can_apply"])


class TestMockExperiences(unittest.TestCase):

    def setUp(self):
        mp.reset()

    def test_has_default_data(self):
        items = mp.experiences()
        self.assertGreaterEqual(len(items), 1)
        for e in items:
            self.assertIn("company", e)
            self.assertIn("bullets", e)
            self.assertGreaterEqual(len(e["bullets"]), 1)

    def test_upsert_and_delete(self):
        n0 = len(mp.experiences())
        e = mp.upsert_experience({"company": "某公司", "title": "前端",
                                  "start": "2020-01", "end": "2021-01",
                                  "bullets": ["做了件事"]})
        self.assertEqual(len(mp.experiences()), n0 + 1)
        self.assertTrue(mp.delete_experience(e["id"]))
        self.assertEqual(len(mp.experiences()), n0)

    def test_update_keeps_one(self):
        e = mp.upsert_experience({"company": "A", "bullets": ["x"]})
        n = len(mp.experiences())
        mp.upsert_experience({"id": e["id"], "company": "B", "bullets": ["y"]})
        self.assertEqual(len(mp.experiences()), n)
        found = [x for x in mp.experiences() if x["id"] == e["id"]][0]
        self.assertEqual(found["company"], "B")


class TestMockConvert(unittest.TestCase):
    def setUp(self):
        mp.reset()

    def tearDown(self):
        mp.reset()


    def test_accepts_supported(self):
        for ext in (".docx", ".pdf", ".png", ".jpg", ".webp"):
            r = mp.convert_template("我的模板" + ext, "AAAA")
            self.assertTrue(r["ok"], ext)
            self.assertEqual(r["template"]["format"],
                             "docx" if ext == ".docx" else ext.lstrip("."))

    def test_rejects_unsupported(self):
        r = mp.convert_template("x.exe", "AAAA")
        self.assertFalse(r["ok"])
        self.assertIn("只支持", r["error"])

    def test_result_has_layout(self):
        """转换结果要带版式参数 —— 真实现抽出来的就是这些。"""
        r = mp.convert_template("t.docx", "AAAA")
        layout = r["template"]["layout"]
        for key in ("columns", "margin_mm", "base_font_pt",
                    "title_font_pt", "font_family", "line_height"):
            self.assertIn(key, layout)


class TestMockReset(unittest.TestCase):
    def setUp(self):
        mp.reset()

    def tearDown(self):
        mp.reset()


    def test_reset_clears_counts(self):
        mp.SITE_APPLY_ENABLED["zhaopin"] = True
        tok = mp.issue_token("J1", "zhaopin")
        mp.mock_apply(JOB, RESUME, token=tok)
        self.assertEqual(mp.SITE_TODAY_COUNT["zhaopin"], 1)
        mp.reset()
        self.assertEqual(mp.SITE_TODAY_COUNT["zhaopin"], 0)

    def test_status_shape(self):
        st = mp.status()
        for key in ("enabled", "gates", "experiences"):
            self.assertIn(key, st)
        self.assertIn("site_apply_enabled", st["gates"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

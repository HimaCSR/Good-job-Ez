"""登录态体检的判定逻辑测试。

只测纯函数 check_from_cookies，不碰浏览器。
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from login_check import check_from_cookies, format_report  # noqa: E402


DAY = 86400


def ck(name, domain="www.zhipin.com", expires=0, days=None):
    """days=None 表示会话级 cookie（expires=0）。"""
    if days is not None:
        expires = int(time.time() + days * DAY)
    return {"name": name, "domain": domain, "expires": expires, "session": expires == 0}


class TestLoginCheck(unittest.TestCase):

    def test_boss_logged_in_is_ok(self):
        cookies = [ck("zp_at", days=12), ck("wt2", days=12),
                   ck("__zp_stoken__", days=3)]
        r = check_from_cookies(cookies, ["zhipin"])
        s = r["sites"][0]
        self.assertEqual(s["status"], "ok")
        self.assertTrue(s["login_ok"])
        self.assertTrue(s["risk_ok"])

    def test_boss_missing_stoken_is_expiring_not_expired(self):
        """风控 token 缺失 ≠ 需要重新登录，只需在浏览器搜一次。"""
        cookies = [ck("zp_at", days=12)]
        r = check_from_cookies(cookies, ["zhipin"])
        s = r["sites"][0]
        self.assertEqual(s["status"], "expiring")
        self.assertTrue(s["login_ok"])   # 登录态还在
        self.assertFalse(s["risk_ok"])
        self.assertIn("不需要重新登录", s["hint"])

    def test_boss_missing_login_cookie_is_expired(self):
        cookies = [ck("__zp_stoken__", days=3)]  # 只有风控 token，没有 zp_at
        r = check_from_cookies(cookies, ["zhipin"])
        s = r["sites"][0]
        self.assertEqual(s["status"], "expired")
        self.assertFalse(s["login_ok"])
        self.assertIn("zp_at", s["detail"])

    def test_zhaopin_ok(self):
        cookies = [ck("at", "www.zhaopin.com", days=7),
                   ck("rt", "www.zhaopin.com", days=30)]
        r = check_from_cookies(cookies, ["zhaopin"])
        s = r["sites"][0]
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["days_left"], 7)  # at 是 7 天，取最短

    def test_risk_token_far_from_expiry_stays_ok(self):
        """风控 token 还有 10 天 —— 不该报临期。"""
        cookies = [ck("zp_at", days=12), ck("__zp_stoken__", days=10)]
        r = check_from_cookies(cookies, ["zhipin"])
        s = r["sites"][0]
        self.assertEqual(s["status"], "ok")
        self.assertTrue(s["risk_ok"])

    def test_risk_token_near_expiry_warns(self):
        """风控 token 只剩 1 天 —— 报警，但仍说不用重新登录。"""
        cookies = [ck("zp_at", days=12), ck("__zp_stoken__", days=1)]
        r = check_from_cookies(cookies, ["zhipin"])
        s = r["sites"][0]
        self.assertEqual(s["status"], "expiring")
        self.assertTrue(s["login_ok"])
        self.assertIn("不需要重新登录", s["hint"])

    def test_session_cookie_falls_back_to_known_ttl(self):
        """会话级 cookie（expires=0）退回已知 TTL。"""
        cookies = [ck("zp_at"), ck("__zp_stoken__", days=10)]
        r = check_from_cookies(cookies, ["zhipin"])
        s = r["sites"][0]
        self.assertEqual(s["days_left"], 12)  # zp_at 的已知 TTL

    def test_site_without_required_cookie_is_unknown(self):
        r = check_from_cookies([ck("whatever")], ["gxrc"])
        s = r["sites"][0]
        self.assertEqual(s["status"], "unknown")
        self.assertFalse(s["login_ok"])

    def test_duplicate_cookie_keeps_longest_expiry(self):
        """同名 cookie 取有效期最长的那个。"""
        cookies = [ck("zp_at", days=1), ck("zp_at", days=12),
                   ck("__zp_stoken__", days=3)]
        r = check_from_cookies(cookies, ["zhipin"])
        self.assertEqual(r["sites"][0]["status"], "ok")

    def test_boss_with_all_cookies_is_ok(self):
        cookies = [ck("zp_at", days=12), ck("wt2", days=12),
                   ck("__zp_stoken__", days=3), ck("wbg", days=12)]
        r = check_from_cookies(cookies, ["zhipin"])
        self.assertEqual(r["sites"][0]["status"], "ok")
        self.assertEqual(r["summary"]["need_attention"], 0)

    def test_summary_counts_attention(self):
        cookies = [ck("zp_at", days=12),
                   ck("at", "www.zhaopin.com", days=7),
                   ck("rt", "www.zhaopin.com", days=30)]
        r = check_from_cookies(cookies)
        self.assertEqual(r["summary"]["total"], 3)
        self.assertEqual(r["summary"]["need_attention"], 1)  # BOSS 缺 stoken

    def test_empty_cookies_all_expired(self):
        r = check_from_cookies([], ["zhipin", "zhaopin"])
        self.assertEqual(r["summary"]["need_attention"], 2)
        for s in r["sites"]:
            self.assertEqual(s["status"], "expired")

    def test_format_report_contains_all_sites(self):
        cookies = [ck("zp_at", days=12),
                   ck("at", "www.zhaopin.com", days=7),
                   ck("rt", "www.zhaopin.com", days=30)]
        r = check_from_cookies(cookies)
        text = format_report(r)
        self.assertIn("BOSS直聘", text)
        self.assertIn("智联招聘", text)
        self.assertIn("结论：", text)


if __name__ == "__main__":
    unittest.main()

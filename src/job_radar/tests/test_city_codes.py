"""城市码表 + 「主攻方向 / 也投方向」两级打分的测试。

## 为什么测这个

**① 城市码不能靠记忆**

我一开始按记忆填了一批码，实测 **28 个是错的**：

| 我猜的 | 实际是 |
|---|---|
| 成都 599 | 沈阳 |
| 西安 566 | 唐山 |
| 武汉 565 | 石家庄 |
| 长沙 558 | 西宁 |
| 郑州 566 | 唐山 |

错的码**不报错、不警告**，只是静默抓到别的城市 ——
用户看到的是「我在成都投简历，结果全是沈阳的岗位」。

所以码表里只留**实测通过**的，并有 `scripts/verify-city-codes.sh` 守着。

**② 两级方向**

用户同时投多个方向时（「主攻运营，顺便看结构设计」），
关键词混在一张列表里会**平分 30 分** → 两个方向岗位混排，
主攻方向被次要方向挤下去。

分两级：
- `title_keywords_primary` —— 主攻，命中给满 30 分
- `title_keywords` —— 也投，命中给 15 分

**没填主攻时按老规则**（每个 +10，最多 30）——
不然老用户的分数会整体掉 15 分。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from city_codes import (CITY_CODES, NATIONWIDE, UNVERIFIED_CITIES,  # noqa: E402
                        cities_to_codes, code_for, known_cities)
import storage  # noqa: E402
from matcher import score_job  # noqa: E402


class TestCityCodes(unittest.TestCase):

    def test_known_cities_not_empty(self):
        self.assertGreater(len(CITY_CODES), 10)

    def test_four_user_cities_present(self):
        """**用户实际要用的四个城市**必须在码表里。"""
        for name in ["重庆", "广州", "南宁", "桂林"]:
            self.assertIn(name, CITY_CODES, "%s 不在码表里" % name)

    def test_codes_are_digits(self):
        for name, code in CITY_CODES.items():
            self.assertTrue(code.isdigit(),
                            "%s 的码不是数字: %r" % (name, code))

    def test_code_for_exact(self):
        self.assertEqual(code_for("南宁"), "3150")
        self.assertEqual(code_for("桂林"), "3165")
        self.assertEqual(code_for("重庆"), "551")
        self.assertEqual(code_for("广州"), "763")

    def test_code_for_with_suffix(self):
        """「广西南宁」「杭州市」这种带后缀的也能认。"""
        self.assertEqual(code_for("广西南宁"), "3150")
        self.assertEqual(code_for("杭州市"), "540")

    def test_code_for_unknown_returns_empty(self):
        """**认不出来就返回空** —— 不能瞎猜一个码。"""
        self.assertEqual(code_for("火星"), "")
        self.assertEqual(code_for(""), "")

    def test_cities_to_codes_dedupes(self):
        out = cities_to_codes(["重庆", "重庆", "广州"])
        self.assertEqual(out, ["551", "763"])

    def test_cities_to_codes_skips_unknown(self):
        """**认不出来的城市要跳过** —— 不然会塞空串，抓取时报错。"""
        out = cities_to_codes(["重庆", "火星"])
        self.assertEqual(out, ["551"])
        self.assertNotIn("", out)

    def test_unverified_cities_not_in_table(self):
        """**没验证过的城市不能出现在码表里**。

        这些是我猜错过的 —— 留着就会静默抓到别的城市。
        """
        for name in UNVERIFIED_CITIES:
            self.assertNotIn(name, CITY_CODES,
                             "%s 的码没验证过，不该在码表里" % name)

    def test_known_cities_shape(self):
        rows = known_cities()
        self.assertTrue(rows)
        for r in rows:
            self.assertIn("name", r)
            self.assertIn("code", r)

    def test_nationwide_code(self):
        self.assertEqual(NATIONWIDE, "489")


class TestTwoLevelDirection(unittest.TestCase):

    def _job(self, title):
        return {"title": title, "city": "广州", "salary": "8-12K",
                "description": "", "tags": []}

    def _profile(self, primary=None, secondary=None, skills=None):
        return {
            "title_keywords_primary": primary or [],
            "title_keywords": secondary or [],
            "skills": skills or [],
            "cities": ["广州"],
            "min_salary": 0,
        }

    def test_primary_gets_full_30(self):
        prof = self._profile(primary=["跨境电商运营"],
                              secondary=["结构设计"])
        out = score_job(self._job("跨境电商运营专员"), prof)
        self.assertTrue(any("主攻方向命中" in r for r in out["reasons"]))

    def test_secondary_only_15_when_primary_set(self):
        """**填了主攻 → 次要只给 15 分**（主攻要排在前面）。"""
        prof = self._profile(primary=["跨境电商运营"],
                              secondary=["结构设计"])
        out = score_job(self._job("结构设计工程师"), prof)
        self.assertTrue(any("期望岗位词命中" in r for r in out["reasons"]))
        self.assertFalse(any("主攻方向命中" in r for r in out["reasons"]))

    def test_no_primary_keeps_old_rule(self):
        """**没填主攻 → 老规则**（每个 +10，最多 30）。

        老用户的分数不能整体掉 15 分 ——
        所以这里对比「填了主攻」和「没填主攻」两种情况：
        没填主攻时，职位名项要拿满 30 分。
        """
        prof = self._profile(secondary=["前端", "web", "three.js"])
        out = score_job(self._job("web前端开发工程师"), prof)
        # 城市命中 = 20 分；职位名项 = 30 分（命中 ≥3 个 → 满）
        # 分数里职位名那部分要是 30，不能是 15
        self.assertGreaterEqual(out["score"], 50, out)

    def test_secondary_is_fixed_15_when_primary_set(self):
        """**填了主攻时，次要方向固定 15 分**（不管命中几个词）。

        这样主攻（30 分）和次要（15 分）之间的差距是稳定的，
        主攻方向一定排在前面。
        """
        job = self._job("结构设计工程师")
        out = score_job(job, self._profile(primary=["跨境电商运营"],
                                           secondary=["结构设计"]))
        # 同一个岗位，只改「有没有填主攻」——
        # 差值就是职位名项的差（次要固定 15 vs 老规则每词 +10）。
        with_primary = score_job(job, self._profile(
            primary=["跨境电商运营"], secondary=["结构设计"]))["score"]
        no_primary = score_job(job, self._profile(
            secondary=["结构设计"]))["score"]
        self.assertEqual(with_primary - no_primary, 5,
                         "次要固定 15 分、老规则 10 分，差应该是 5")

    def test_secondary_fixed_15_regardless_of_hit_count(self):
        """命中 1 个和命中 3 个，**次要都给 15 分**。"""
        job = self._job("结构设计工程师")
        one = score_job(job, self._profile(primary=["跨境电商运营"],
                                           secondary=["结构设计"]))
        three = score_job(job, self._profile(primary=["跨境电商运营"],
                                             secondary=["结构设计", "结构",
                                                        "设计"]))
        self.assertEqual(one["score"], three["score"],
                         "次要方向的给分不该随命中个数变化")

    def test_primary_beats_secondary(self):
        """**主攻方向的分数要高于也投方向** —— 否则排序没意义。"""
        prof = self._profile(primary=["跨境电商运营"],
                              secondary=["结构设计"])
        primary_score = score_job(self._job("跨境电商运营专员"), prof)["score"]
        secondary_score = score_job(self._job("结构设计工程师"), prof)["score"]
        self.assertGreater(primary_score, secondary_score,
                           "主攻方向分数没有高于也投方向")

    def test_unmatched_direction_reported(self):
        prof = self._profile(primary=["跨境电商运营"])
        out = score_job(self._job("行政专员"), prof)
        self.assertIn("职位名未命中期望岗位词", out["missing"])


class TestConfigFallback(unittest.TestCase):
    """没有 ctx 时，`load_config()` 要能读到 Hermes 的配置。

    ## 为什么

    `config.set_context(ctx)` 只在 `register(ctx)` 里调用。
    **任何不走 register 的调用路径**（独立脚本、某些定时任务、单测）
    原来都会拿到**默认值** ——
    `keywords` 是空的 → 抓取直接中止「没有配置关键词」。

    本机踩过：跑验证脚本时 `tools.scan({...})` 直接返回
    「没有配置关键词」，而设置页里关键词明明填好了。

    ## 怎么读

    走 `hermes config get` —— **不自己解析 YAML**
    （自己的解析器会漏掉块序列 `- 前端` 这种列表写法）。
    """

    def test_parser_reads_scalars(self):
        from config import _parse_cli_output
        out = _parse_cli_output("keywords:\n  - 跨境电商运营\n  - 亚马逊运营\n"
                                "city: 763\nmin_score: 40\n"
                                "mock: false\nactive_hours: 09:00 - 22:00\n")
        self.assertEqual(out["keywords"], ["跨境电商运营", "亚马逊运营"])
        # city 存的是数字（Hermes 的 YAML 里 `city: 763` 没引号）→ 解析成 int
        self.assertEqual(out["city"], 763)
        self.assertEqual(out["min_score"], 40)
        self.assertIs(out["mock"], False)
        self.assertEqual(out["active_hours"], "09:00 - 22:00")

    def test_parser_reads_inline_list(self):
        from config import _parse_cli_output
        out = _parse_cli_output("cities: ['重庆', '广州']\n")
        self.assertEqual(out["cities"], ["重庆", "广州"])

    def test_defaults_when_nothing(self):
        from config import _defaults
        d = _defaults()
        self.assertEqual(d["keywords"], [])
        self.assertEqual(d["cities"], [])

    def test_load_config_without_ctx_returns_mapping(self):
        """**没有 ctx 也要返回完整的 dict**（不能是 None）。"""
        from config import load_config
        cfg = load_config()
        self.assertIsInstance(cfg, dict)
        for k in ("keywords", "cities", "min_score", "max_jobs_per_run"):
            self.assertIn(k, cfg)


class TestRescoreAll(unittest.TestCase):
    """改了画像后，**老岗位的分数要重算**。

    ## 为什么

    `upsert()` 只在岗位**被重新抓到**时更新分数。
    没被抓到的老岗位**分数永远停在旧值**。

    实测踩到：把方向从「web 前端」改成「跨境电商运营」后，
    杭州的 web 前端老岗位还留着 **78 分**，
    比新抓的运营岗（76 分）还高 → **老岗位全挤在推荐前面**。

    这跟用户看到的东西完全对不上 —— 他会问
    「我明明投的是运营，怎么给我推前端」。
    """

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="jr-rescore-")
        self._orig = storage.plugin_data_dir
        storage.plugin_data_dir = lambda name: self.tmp

    def tearDown(self):
        import shutil
        if self._orig:
            storage.plugin_data_dir = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rescore_uses_new_profile(self):
        old = {
            "title_keywords": ["前端", "web"],
            "skills": ["vue"],
            "cities": ["杭州"],
            "min_salary": 0,
        }
        new = {
            "title_keywords": ["跨境电商运营"],
            "skills": ["亚马逊"],
            "cities": ["重庆"],
            "min_salary": 0,
        }
        job = {"job_id": "j1", "title": "web前端开发工程师",
               "company": "某公司", "area": "杭州 余杭", "city": "杭州",
               "salary": "1-2万", "source": "zhaopin", "tags": ["vue"],
               "url": "", "description": "", "reasons": [], "missing": []}
        storage.upsert(job, {"score": 78, "reasons": ["老画像"], "missing": []})
        self.assertEqual(storage.get_job("j1")["score"], 78)

        n = storage.rescore_all(new)
        self.assertEqual(n, 1)
        after = storage.get_job("j1")
        self.assertLess(after["score"], 78,
                        "换画像后老岗位的分数没重算")

    def test_rescore_keeps_pushed_state(self):
        """**不动 first_seen / pushed_at** —— 那是投递状态，跟分数无关。"""
        job = {"job_id": "j2", "title": "跨境电商运营", "company": "某公司",
               "area": "重庆", "city": "重庆", "salary": "8-12K",
               "source": "zhaopin", "tags": [], "url": "", "description": "",
               "reasons": [], "missing": []}
        storage.upsert(job, {"score": 70, "reasons": [], "missing": []})
        before = storage.get_job("j2")
        storage.rescore_all({"title_keywords": ["跨境电商运营"], "skills": [],
                             "cities": ["重庆"], "min_salary": 0})
        after = storage.get_job("j2")
        self.assertEqual(after.get("first_seen"), before.get("first_seen"),
                         "重算分数不该动 first_seen")
        self.assertEqual(after.get("pushed_at"), before.get("pushed_at"),
                         "重算分数不该动 pushed_at")

    def test_rescore_empty_pool(self):
        n = storage.rescore_all({"title_keywords": [], "skills": [],
                                 "cities": [], "min_salary": 0})
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

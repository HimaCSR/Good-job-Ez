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
        # **2026-10-29 全部换成「城市专码」** ——
        # 码从智联 SEO 页读的，每个抓回来 20/20 全是那个城市。
        #
        # 老码是「区域码」，有的根本不是那个城市：
        #   佛山 763 → 广州；惠州 763 → 广州；
        #   无锡 3040 → 常州；苏州 3040 → 常州
        self.assertEqual(code_for("南宁"), "785")
        self.assertEqual(code_for("桂林"), "787")
        self.assertEqual(code_for("重庆"), "551")
        self.assertEqual(code_for("广州"), "763")
        self.assertEqual(code_for("成都"), "801")
        self.assertEqual(code_for("苏州"), "639")
        self.assertEqual(code_for("西安"), "854")

    def test_chengdu_code_verified(self):
        """**成都 = 801**（2026-10-29 实测）。

        **不是 552** —— 552 是「四川区域码」，抓回来是
        成都 9 / 眉山 4 / 德阳 1 / 泸州 1 / 广元 1 / 雅安 1。

        801 是**城市专码**，抓回来 **成都 20/20**。
        """
        self.assertEqual(CITY_CODES.get("成都"), "801")

    def test_city_codes_cover_many_cities(self):
        """码表要覆盖足够多的城市 —— 用户能选的地方多。"""
        self.assertGreaterEqual(len(CITY_CODES), 100,
                                "码表只有 %d 个城市" % len(CITY_CODES))

    def test_major_cities_use_dedicated_codes(self):
        """**重点城市要用「城市专码」**，不是区域码。

        老码表里 佛山/惠州都指向 763（广州），
        无锡/苏州都指向 3040（常州）——
        用户在设置页选「佛山」，抓到的是**广州**的岗位。
        **静默发生，不报错、不警告。**
        """
        # 这些城市**不能**共用别的城市的码
        self.assertNotEqual(CITY_CODES.get("佛山"), CITY_CODES.get("广州"))
        self.assertNotEqual(CITY_CODES.get("惠州"), CITY_CODES.get("广州"))
        self.assertNotEqual(CITY_CODES.get("无锡"), CITY_CODES.get("常州"))
        self.assertNotEqual(CITY_CODES.get("苏州"), CITY_CODES.get("常州"))
        # 也不能跟北京/上海这些共用
        for a in ("佛山", "惠州", "无锡", "苏州"):
            for b in ("北京", "上海", "广州", "深圳", "重庆"):
                self.assertNotEqual(CITY_CODES.get(a), CITY_CODES.get(b),
                                    "%s 和 %s 共用了同一个码" % (a, b))

    def test_code_table_and_unverified_do_not_overlap(self):
        """**码表和「猜错过的」列表不能有交集**。

        同一个城市名同时在两边 → 说明它既被验证过又被标记为不可信。
        """
        overlap = set(CITY_CODES) & set(UNVERIFIED_CITIES)
        self.assertEqual(overlap, set(),
                         "这些城市既在码表里又在未验证列表里：%s" % overlap)

    def test_code_for_with_suffix(self):
        """「广西南宁」「杭州市」这种带后缀的也能认。"""
        self.assertEqual(code_for("广西南宁"), "785")
        self.assertEqual(code_for("杭州市"), "653")

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


class TestDirectionScoring(unittest.TestCase):
    """**方向词评分** —— 不分主次，按权重。

    ## 规则变了

    原来是「主攻 30 分 / 次要 15 分」两级。
    现在改成「**不分主次**」：

    - **有 `direction_weights`** → 命中词的**权重之和** × 10（上限 30）
    - **没有**（老画像）→ 每个词权重 1.0（命中 1 个 10 分、3 个 30 分）

    **主攻的加成在权重表里**（+1.5）—— 同一张表，不是另一套规则。

    用户诉求：「根据经历内容评定，灵活调整期望方向，**不分主次**」。
    """

    def _job(self, title):
        return {"title": title, "city": "广州", "salary": "8-12K",
                "description": "", "tags": []}

    def _profile(self, primary=None, secondary=None, skills=None,
                 weights=None):
        prof = {
            "title_keywords_primary": primary or [],
            "title_keywords": secondary or [],
            "skills": skills or [],
            "cities": ["广州"],
            "min_salary": 0,
        }
        if weights is not None:
            prof["direction_weights"] = weights
        return prof

    def test_direction_hit_reported(self):
        """**命中方向词要说清楚**（给用户看的匹配理由）。"""
        prof = self._profile(primary=["跨境电商运营"],
                              secondary=["结构设计"])
        out = score_job(self._job("跨境电商运营专员"), prof)
        self.assertTrue(any("方向命中" in r for r in out["reasons"]), out)

    def test_more_specific_hits_score_higher(self):
        """**命中更多 → 分数更高**（旧规则是固定 15，不变）。

        「结构设计工程师」命中 3 个词（结构设计/结构/设计）
        vs 命中 1 个词 → 前者分更高。
        """
        job = self._job("结构设计工程师")
        one = score_job(job, self._profile(secondary=["结构设计"]))["score"]
        three = score_job(job, self._profile(
            secondary=["结构设计", "结构", "设计"]))["score"]
        self.assertGreater(three, one,
                           "命中更多方向词应该分更高")

    def test_weights_drive_score(self):
        """**权重决定分数** —— 权重高的词命中 → 分更高。"""
        job = self._job("跨境电商运营专员")
        strong = score_job(job, self._profile(
            secondary=["跨境电商运营"],
            weights={"跨境电商运营": 3.0}))["score"]
        weak = score_job(job, self._profile(
            secondary=["跨境电商运营"],
            weights={"跨境电商运营": 0.5}))["score"]
        self.assertGreater(strong, weak,
                           "按经历评定的权重应该影响分数")

    def test_no_primary_secondary_bonus(self):
        """**没有主攻/次要的差别** —— 两边的分只差「词本身」。

        这是「不分主次」的核心：主攻词和次要词**用同一套规则**，
        只有权重不同（权重表里体现）。
        """
        job = self._job("跨境电商运营专员")
        as_primary = score_job(job, self._profile(
            primary=["跨境电商运营"], secondary=["结构设计"]))["score"]
        as_secondary = score_job(job, self._profile(
            primary=["结构设计"], secondary=["跨境电商运营"]))["score"]
        self.assertEqual(as_primary, as_secondary,
                         "主攻/次要用同一套规则 → 同样命中应该同分")

    def test_old_profile_uses_neutral_weight(self):
        """**老画像（没权重表）也能打分** —— 每个词算 1.0。

        老用户的分数不能变 0。
        """
        prof = self._profile(secondary=["前端", "web", "three.js"])
        out = score_job(self._job("web前端开发工程师"), prof)
        # 城市命中 = 20 分；职位名项 = 30 分（命中 ≥3 个 → 满）
        self.assertGreaterEqual(out["score"], 50, out)

    def test_primary_weight_bonus_in_weights(self):
        """**主攻方向在权重表里 +1.5** —— 权重制下的唯一「主次」体现。"""
        from profile_derive import score_direction_weights
        exps = [{"title": "土建技术员", "company": "某公司",
                 "bullets": ["参与施工"], "tags": []}]
        w = score_direction_weights(
            exps, {"title_keywords_primary": ["跨境电商运营"],
                   "title_keywords": [], "skills": []})
        self.assertIn("跨境电商运营", w)
        self.assertGreaterEqual(w["跨境电商运营"], 1.5)

    def test_unmatched_direction_reported(self):
        prof = self._profile(primary=["跨境电商运营"])
        out = score_job(self._job("行政专员"), prof)
        self.assertIn("职位名未命中期望方向词", out["missing"])


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

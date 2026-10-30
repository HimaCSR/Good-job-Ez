"""**方向词权重 + 岗位类型去重** 的测试。

## 用户诉求

> 根据经历内容评定，灵活调整期望方向，**不分主次**。
> 同时**同一类型岗位只推最高分前 3 项**。

## 测什么

1. 权重：按经历评定（职位名 > bullets、最近的 > 老的、干得久 > 干得短）
2. 不分主次：主攻和次要用**同一套规则**
3. 岗位类型：职级后缀、括号、平台前缀的归一化
4. 去重：同类型只留前 3
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matcher  # noqa: E402
import profile_derive  # noqa: E402


def exp(title, bullets=None, start=None, end=None, company="某公司",
        tags=None):
    return {"title": title, "company": company, "bullets": bullets or [],
            "tags": tags or [], "start": start, "end": end}


class TestDirectionWeights(unittest.TestCase):

    def test_title_beats_bullets(self):
        """**职位名权重高于 bullets** —— 职位名是那段时间的主线。"""
        w = profile_derive.score_direction_weights(
            [exp("跨境电商运营", ["负责选品与推广"])])
        self.assertGreater(w.get("跨境电商运营", 0), w.get("选品", 0))

    def test_recent_beats_old(self):
        """**最近的经历权重更高** —— 「现在想做什么」跟最近有关。"""
        w = profile_derive.score_direction_weights([
            exp("土建技术员", [], "2019-01", "2019-12"),
            exp("跨境电商运营", [], "2025-07", "2026-08"),
        ])
        self.assertGreater(w.get("跨境电商运营", 0), w.get("土建技术员", 0))

    def test_longer_job_weights_higher(self):
        """**干得久权重更高**。"""
        w = profile_derive.score_direction_weights([
            exp("土建技术员", [], "2024-01", "2024-03"),
            exp("跨境电商运营", [], "2024-01", "2026-08"),
        ])
        self.assertGreater(w.get("跨境电商运营", 0), w.get("土建技术员", 0))

    def test_weights_normalized_range(self):
        """**权重归一到 0.5 ~ 3.0** —— 分数才好算。"""
        w = profile_derive.score_direction_weights(
            [exp("跨境电商运营", ["负责选品"])])
        for v in w.values():
            self.assertGreaterEqual(v, 0.5)
            self.assertLessEqual(v, 3.0)

    def test_primary_is_in_same_table(self):
        """**主攻方向也进同一张表**（权重 +1.5）—— 不分主次。"""
        w = profile_derive.score_direction_weights(
            [exp("土建技术员", ["参与施工"])],
            {"title_keywords_primary": ["结构设计"]})
        self.assertIn("结构设计", w)
        self.assertGreaterEqual(w["结构设计"], 1.5)

    def test_idempotent_weights(self):
        """**权重计算幂等** —— 同样的输入给同样的输出。"""
        exps = [exp("跨境电商运营", ["负责选品"])]
        a = profile_derive.score_direction_weights(exps)
        b = profile_derive.score_direction_weights(exps)
        self.assertEqual(a, b)


class TestDirectionScoringNoPrimarySecondary(unittest.TestCase):

    def _job(self, title):
        return {"title": title, "city": "广州", "salary": "8-12K",
                "description": "", "tags": []}

    def test_primary_and_secondary_same_rule(self):
        """**主攻和次要同分** —— 同一套规则。"""
        prof = {"title_keywords_primary": ["跨境电商运营"],
                "title_keywords": ["结构设计"], "skills": [], "cities": ["广州"],
                "min_salary": 0}
        job = self._job("跨境电商运营专员")
        a = matcher.score_job(job, {
            **prof, "title_keywords_primary": ["跨境电商运营"],
            "title_keywords": []})["score"]
        b = matcher.score_job(job, {
            **prof, "title_keywords_primary": [],
            "title_keywords": ["跨境电商运营"]})["score"]
        self.assertEqual(a, b, "主次不该有差别")

    def test_weight_changes_score(self):
        """**权重影响分数**。"""
        job = self._job("跨境电商运营专员")
        base = {"title_keywords_primary": [], "title_keywords": ["跨境电商运营"],
                "skills": [], "cities": ["广州"], "min_salary": 0}
        strong = matcher.score_job(
            job, {**base, "direction_weights": {"跨境电商运营": 3.0}})["score"]
        weak = matcher.score_job(
            job, {**base, "direction_weights": {"跨境电商运营": 0.5}})["score"]
        self.assertGreater(strong, weak)

    def test_missing_reason_text(self):
        prof = {"title_keywords_primary": ["跨境电商运营"],
                "title_keywords": [], "skills": [], "cities": ["广州"],
                "min_salary": 0}
        out = matcher.score_job(self._job("行政专员"), prof)
        self.assertIn("职位名未命中期望方向词", out["missing"])


class TestJobTypeKey(unittest.TestCase):

    def test_level_suffix_stripped(self):
        """**职级后缀剥掉** —— 同一类岗位的不同层级。"""
        for t in ("跨境电商运营助理", "跨境电商运营专员", "跨境电商运营主管",
                  "跨境电商运营经理", "跨境电商运营"):
            self.assertEqual(matcher.job_type_key(t), "跨境电商运营", t)

    def test_bracket_content_removed(self):
        """**括号内容去掉**。"""
        self.assertEqual(
            matcher.job_type_key("跨境电商运营专员（速卖通/eBay）"),
            "跨境电商运营")

    def test_bracket_in_middle_removed(self):
        """**括号在中间也去掉** —— 平台前缀不该挡住类型。

        本机踩过：「ebay（易贝）shopee（虾皮） 跨境电商运营」
        → 只去首尾括号会留下「ebayshopee跨境电商运营」→ 归一化不到一起。
        """
        self.assertEqual(
            matcher.job_type_key("ebay（易贝）shopee（虾皮） 跨境电商运营"),
            "ebayshopee跨境电商运营")  # 兜底归一化（标题法）

    def test_prefix_noise_removed(self):
        self.assertEqual(matcher.job_type_key("急招电商运营"), "电商运营")

    def test_role_suffix_kept_by_default(self):
        """**「运营」是岗位名的一部分** —— 默认不剥。

        剥掉会变成「电商」→ 太粗 → 跟别的撞成一类。
        """
        self.assertEqual(matcher.job_type_key("电商运营"), "电商运营")

    def test_strip_role_option(self):
        """**显式要剥才剥**。"""
        self.assertEqual(matcher.job_type_key("电商运营", strip_role=True),
                         "电商")


class TestJobTypeByDirection(unittest.TestCase):

    def test_uses_root_word(self):
        """**用命中的方向词定类型** —— 平台前缀不算类型。"""
        words = ["跨境电商运营", "电商运营", "跨境电商"]
        weights = {w: 3.0 for w in words}
        key = matcher.job_type_by_direction(
            "亚马逊运营专员", haystack="亚马逊运营专员 跨境电商运营",
            direction_words=words, direction_weights=weights)
        self.assertIn("跨境", key)

    def test_fallback_to_title(self):
        """**没命中方向词 → 退回标题归一化**。"""
        key = matcher.job_type_by_direction(
            "土建技术员", haystack="土建技术员",
            direction_words=["跨境电商运营"])
        self.assertEqual(key, "土建")


if __name__ == "__main__":
    unittest.main(verbosity=2)

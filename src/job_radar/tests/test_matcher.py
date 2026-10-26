"""匹配打分单测 —— 四项权重：职位名 30 + 技能 30 + 城市 20 + 薪资 20。

2026-10-26 改：去掉经验项（用户决定暂不纳入评分），
城市改多选（20 分），薪资从 10 提到 20。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from matcher import score_job, _salary_score  # noqa: E402

PROFILE = {
    "title_keywords": ["前端", "web", "three.js"],
    "skills": ["three.js", "vue", "typescript", "node"],
    "cities": ["杭州"],
    "city": "杭州",          # 兼容旧字段
    "min_experience_years": 3,
    "min_salary": 15,
    "exclude_companies": [],
}


def job(**kw):
    base = {
        "title": "web前端工程师",
        "company": "某公司",
        "area": "杭州 拱墅",
        "salary": "1.5-1.8万",
        "tags": "three.js vue typescript node javascript html5 css webgl",
        "description": "",
        "experience": "3-5年",
    }
    base.update(kw)
    return base


class TestScoreWeights(unittest.TestCase):

    def test_perfect_match_is_100(self):
        r = score_job(job(), PROFILE)
        # 职位名 30（三个关键词全中）+ 技能 30（4/4）+ 城市 20 + 薪资 20 = 100
        self.assertEqual(r["score"], 100, r)

    def test_experience_not_scored(self):
        """经验项已移出评分：经验完全不同，分数必须一样。"""
        j3 = job(experience="3-5年")
        j0 = job(experience="应届生")
        self.assertEqual(score_job(j3, PROFILE)["score"],
                         score_job(j0, PROFILE)["score"])

    def test_city_is_20_points(self):
        good = score_job(job(area="杭州 拱墅"), PROFILE)
        bad = score_job(job(area="北京 朝阳"), PROFILE)
        self.assertEqual(good["score"] - bad["score"], 20)

    def test_multi_city_any_match(self):
        """期望多个城市时，命中任一即算符合。"""
        prof = dict(PROFILE, cities=["杭州", "上海"])
        for city in ("杭州 拱墅", "上海 徐汇"):
            r = score_job(job(area=city), prof)
            self.assertTrue(any("城市符合" in x for x in r["reasons"]),
                            f"{city} 应该算符合，实际 {r}")

    def test_multi_city_none_match(self):
        prof = dict(PROFILE, cities=["杭州", "上海"])
        r = score_job(job(area="北京 朝阳"), prof)
        self.assertTrue(any("城市不符" in m for m in r["missing"]), r)

    def test_salary_is_20_points(self):
        good = score_job(job(salary="2-3万"), PROFILE)
        bad = score_job(job(salary="5-6千"), PROFILE)
        self.assertEqual(good["score"] - bad["score"], 20)

    def test_score_never_exceeds_100(self):
        prof = dict(PROFILE,
                    title_keywords=["前端", "web", "three.js", "工程师"],
                    skills=["three.js", "vue", "typescript", "node", "a", "b"])
        r = score_job(job(), prof)
        self.assertLessEqual(r["score"], 100)
        self.assertGreaterEqual(r["score"], 0)

    def test_score_never_negative(self):
        r = score_job(job(title="完全不相关的岗位", area="北京",
                          salary="面议", tags="", description=""),
                      PROFILE)
        self.assertGreaterEqual(r["score"], 0)

    def test_wrong_city_wrong_skill_is_low(self):
        r = score_job(job(title="文员", area="北京 朝阳", salary="3-4千",
                          tags="word excel", description="行政"),
                      PROFILE)
        self.assertLess(r["score"], 50, r)


class TestScoreJob(unittest.TestCase):

    def test_perfect_match_is_high(self):
        # 职位名命中「前端」+「web」+「three.js」= 30；
        # 技能 4/4 = 30；城市 20；薪资 20-40K >= 15K = 20 -> 100
        job = {"title": "高级 web 前端工程师（three.js/vue）",
               "tags": "three.js, vue, typescript, node",
               "area": "杭州 西湖", "experience": "3-5年", "salary": "20-40K"}
        r = score_job(job, PROFILE)
        self.assertGreaterEqual(r["score"], 95, r)
        self.assertEqual(r["missing"], [], r)

    def test_wrong_city_and_skill_low(self):
        job = {"title": "Java 后端", "tags": "spring", "area": "北京 朝阳",
               "experience": "5-10年", "salary": "30-50K"}
        r = score_job(job, PROFILE)
        self.assertLess(r["score"], 45, r)

    def test_score_never_out_of_range(self):
        for name in ["", "x" * 500, "前端" * 50]:
            r = score_job({"title": name, "tags": name}, PROFILE)
            self.assertGreaterEqual(r["score"], 0)
            self.assertLessEqual(r["score"], 100)

    def test_missing_skill_is_reported(self):
        job = {"title": "前端工程师", "tags": "vue", "area": "杭州",
               "experience": "3-5年", "salary": "20K"}
        r = score_job(job, PROFILE)
        self.assertTrue(any("three.js" in m for m in r["missing"]), r)

    def test_masked_salary_gets_neutral_score(self):
        base = dict(PROFILE, skills=[], title_keywords=[])
        masked = score_job({"title": "前端", "area": "杭州", "salary": "**-**元"}, base)
        plain = score_job({"title": "前端", "area": "杭州", "salary": "5-8K"}, base)
        self.assertGreater(masked["score"], plain["score"], (masked, plain))

    def test_empty_profile_scores_in_range(self):
        r = score_job({"title": "前端", "area": "杭州"}, {})
        self.assertGreaterEqual(r["score"], 0)
        self.assertLessEqual(r["score"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestSalaryWithoutUnit(unittest.TestCase):
    """「8000-12000」这种不带单位的写法。

    2026-10-26 实测踩过：这条分支没给 unit 赋值，后面还在用 unit
    → UnboundLocalError，扫描直接崩。日志加上去才看见。
    """

    def test_plain_number_range(self):
        # 不抛异常就是过了；顺便确认给出的分数在合理区间
        score = _salary_score("8000-12000", 15)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 20)

    def test_plain_number_range_below_expectation(self):
        score = _salary_score("3000-4000", 15)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 20)

    def test_masked_salary_is_neutral(self):
        self.assertEqual(_salary_score("**-**元", 15), 10)

    def test_unreadable_salary_is_neutral(self):
        self.assertEqual(_salary_score("面议", 15), 10)

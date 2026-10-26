import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from matcher import score_job  # noqa: E402

PROFILE = {
    "title_keywords": ["前端", "web"],
    "skills": ["three.js", "vue"],
    "city": "杭州",
    "min_experience_years": 3,
    "min_salary": 20,
}


class TestScoreJob(unittest.TestCase):

    def test_perfect_match_is_high(self):
        # 职位名命中「前端」+「web」两个词 = 30 分；
        # 技能 2/2 = 30；城市 15；经验 3-5年 ≥ 3年 = 15；薪资 20-40K ≥ 20K = 10
        # 合计 100
        job = {"title": "高级 web 前端工程师（three.js/vue）",
               "tags": "three.js, vue",
               "area": "杭州 西湖", "experience": "3-5年", "salary": "20-40K"}
        r = score_job(job, PROFILE)
        self.assertGreaterEqual(r["score"], 85, r)
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

    def test_experience_below_requirement_scores_lower(self):
        base = dict(PROFILE, skills=[], title_keywords=[])
        low = score_job({"title": "前端", "area": "杭州", "experience": "1年以内",
                         "salary": "30K"}, base)
        ok = score_job({"title": "前端", "area": "杭州", "experience": "5-10年",
                        "salary": "30K"}, base)
        self.assertGreater(ok["score"], low["score"], (ok, low))

    def test_empty_profile_scores_in_range(self):
        r = score_job({"title": "前端", "area": "杭州"}, {})
        self.assertGreaterEqual(r["score"], 0)
        self.assertLessEqual(r["score"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)

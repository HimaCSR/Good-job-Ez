import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from push import build_push, format_job, split_for_qq  # noqa: E402

LIMIT = 50


class TestSplit(unittest.TestCase):

    def test_short_text_stays_one(self):
        self.assertEqual(split_for_qq("短句"), ["短句"])

    def test_long_text_respects_limit(self):
        long = "这是一个很长的岗位描述，包含很多技术栈要求。" * 20
        out = split_for_qq(long)
        self.assertTrue(all(len(p) <= LIMIT for p in out),
                        [len(p) for p in out])

    def test_content_is_preserved(self):
        long = "前端开发工程师岗位要求熟悉 Vue 与 TypeScript。" * 10
        out = split_for_qq(long)
        joined = "".join(out).replace(" ", "")
        self.assertEqual(joined, long.replace(" ", ""))


class TestFormatJob(unittest.TestCase):

    JOB = {
        "title": "高级 web 前端工程师",
        "company": "某某科技有限公司",
        "area": "杭州 西湖",
        "score": 88,
        "url": "https://www.zhaopin.com/jobdetail/CCL123.htm",
        "reasons": ["职位名命中: 前端、web", "技能覆盖 5/8: vue、node"],
    }

    def test_every_message_within_limit(self):
        for m in format_job(self.JOB):
            self.assertLessEqual(len(m), LIMIT, m)

    def test_contains_key_fields(self):
        out = " ".join(format_job(self.JOB))
        self.assertIn("高级 web 前端工程师", out)
        self.assertIn("88", out)
        self.assertIn("杭州", out)
        self.assertIn("zhaopin.com", out)

    def test_very_long_title_is_truncated(self):
        job = dict(self.JOB, title="超长" * 60)
        for m in format_job(job):
            self.assertLessEqual(len(m), LIMIT, m)

    def test_missing_fields_do_not_crash(self):
        out = format_job({"title": "前端"})
        self.assertTrue(out)
        for m in out:
            self.assertLessEqual(len(m), LIMIT, m)


class TestBuildPush(unittest.TestCase):

    def test_limits_job_count(self):
        jobs = [{"title": "岗位%d" % i, "score": 90 - i, "company": "C",
                 "area": "杭州", "url": "u%d" % i, "reasons": []}
                for i in range(10)]
        msgs = build_push(jobs, max_jobs=3)
        joined = " ".join(msgs)
        for i in range(3):
            self.assertIn("岗位%d" % i, joined)
        self.assertNotIn("岗位3", joined)

    def test_filters_below_min_score(self):
        jobs = [{"title": "低分", "score": 20, "company": "C", "area": "杭州",
                 "url": "u", "reasons": []}]
        self.assertEqual(build_push(jobs, min_score=50), [])

    def test_all_text_messages_within_limit(self):
        """URL 豁免（拆了就点不开），其余文本必须 <=50 字。"""
        jobs = [{"title": "岗位" * 20, "score": 90, "company": "很长的公司名称" * 5,
                 "area": "杭州 西湖区 三墩镇", "url": "https://www.zhaopin.com/jobdetail/CCL1.htm",
                 "reasons": ["命中理由" * 10]}]
        for m in build_push(jobs):
            if m.startswith("http"):
                continue
            self.assertLessEqual(len(m), LIMIT, m)

    def test_url_is_never_split(self):
        job = {"title": "前端", "score": 90, "company": "C", "area": "杭州",
               "url": "https://www.zhaopin.com/jobdetail/" + "A" * 80 + ".htm",
               "reasons": []}
        urls = [m for m in format_job(job) if m.startswith("http")]
        self.assertEqual(len(urls), 1)
        self.assertIn("AAAA", urls[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestUrlNotSplit(unittest.TestCase):
    """URL 不能被切成两半 —— 切了就点不开。"""

    def test_url_survives_split(self):
        text = ("web前端开发工程师 · 杭州拱墅\n"
                "https://www.zhaopin.com/jobdetail/CC3985.htm")
        parts = split_for_qq(text, limit=50)
        joined = "".join(parts)
        self.assertIn("https://www.zhaopin.com/jobdetail/CC3985.htm", joined)
        # 没有任何一段以 "//" 开头（那是被切断的链接）
        for p in parts:
            self.assertFalse(p.startswith("//"), p)

    def test_two_urls_stay_whole(self):
        text = ("标题很长很长很长很长很长很长很长很长很长很长很长\n"
                "https://a.example.com/one\nhttps://b.example.com/two")
        parts = split_for_qq(text, limit=50)
        joined = "".join(parts)
        self.assertIn("https://a.example.com/one", joined)
        self.assertIn("https://b.example.com/two", joined)

    def test_format_job_url_intact(self):
        url = "https://www.zhaopin.com/jobdetail/CC398533130J40905945205.htm"
        job = {"title": "web前端开发工程师", "company": "某人力资源有限公司",
               "city": "杭州 拱墅", "score": 73, "url": url,
               "reasons": ["职位名命中: 前端"]}
        msgs = format_job(job)
        self.assertIn(url, msgs)

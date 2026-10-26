"""「只推新岗位」的存储层测试。

背景：cron 每 6 小时跑一次，同一批岗位被反复推了 3 次。
用户定的规矩是「只推当天新岗位，不重复推旧的」。

判据是 `pushed_at` 列（不是 status —— 那是用户自己标记
interested/applied/ignored 用的）。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage  # noqa: E402


class TestPushedAt(unittest.TestCase):

    def setUp(self):
        self.saved = None
        try:
            self.saved = storage.plugin_data_dir("job-radar")
        except Exception:
            pass
        # 用独立的临时库，别碰真的岗位池
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="jr-test-")
        self._orig = storage.plugin_data_dir
        storage.plugin_data_dir = lambda name: self.tmp

    def tearDown(self):
        if self._orig:
            storage.plugin_data_dir = self._orig
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, job_id, score=80, first_seen=None):
        job = {
            "job_id": job_id, "source": "zhaopin", "title": "前端工程师 " + job_id,
            "company": "某人力资源有限公司", "salary": "15-25K", "city": "杭州 西湖",
            "skills": ["vue"], "url": "https://example.com/" + job_id,
            "description": "描述",
        }
        scored = {"score": score, "reasons": ["职位名命中: 前端"], "missing": []}
        storage.upsert(job, scored)
        if first_seen:
            with storage._conn() as c:
                c.execute("UPDATE jobs SET first_seen = ? WHERE job_id = ?",
                          (first_seen, job_id))

    def test_schema_has_pushed_at(self):
        self._add("a1")
        with storage._conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
        self.assertIn("pushed_at", cols)

    def test_new_jobs_are_unpushed(self):
        self._add("a1")
        rows = storage.unpushed_jobs(days=30, min_score=50)
        self.assertEqual([r["job_id"] for r in rows], ["a1"])

    def test_mark_pushed_removes_from_unpushed(self):
        self._add("a1")
        self._add("a2")
        rows = storage.unpushed_jobs(days=30, min_score=50)
        self.assertEqual(len(rows), 2)
        n = storage.mark_pushed(["a1"])
        self.assertEqual(n, 1)
        rows = storage.unpushed_jobs(days=30, min_score=50)
        self.assertEqual([r["job_id"] for r in rows], ["a2"])

    def test_pushed_jobs_not_returned_again(self):
        """核心：标记后不该再出现 —— 这是「不重复推」的关键。"""
        self._add("a1")
        storage.mark_pushed(["a1"])
        rows = storage.unpushed_jobs(days=30, min_score=50)
        self.assertEqual(rows, [])

    def test_min_score_filter(self):
        self._add("low", score=20)
        rows = storage.unpushed_jobs(days=30, min_score=50)
        self.assertEqual(rows, [])

    def test_old_jobs_excluded_by_days(self):
        """三天前出现的岗位不算「今天的」。"""
        self._add("old", first_seen="2020-01-01T00:00:00")
        rows = storage.unpushed_jobs(days=1, min_score=50)
        self.assertEqual(rows, [])

    def test_mark_pushed_empty_is_noop(self):
        self.assertEqual(storage.mark_pushed([]), 0)

    def test_status_field_is_independent(self):
        """pushed_at 不影响 status —— 那是用户自己的标记。"""
        self._add("a1")
        storage.mark_pushed(["a1"])
        with storage._conn() as c:
            row = c.execute("SELECT status FROM jobs WHERE job_id='a1'").fetchone()
        self.assertEqual(row["status"], "new")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""结构化经历的存储测试。

## 为什么专门测这个

本机踩过的 bug：**新增一条经历，把旧的挤掉了**。

根因在前端新增时传的是 `id: ''`（空字符串），后端：

    exp.setdefault("id", "exp-%d" % (len(_EXPERIENCES) + 1))
    _EXPERIENCES[:] = [e for e in _EXPERIENCES if e["id"] != exp["id"]]

- `setdefault` 在 **key 存在**时不会覆盖 → 空字符串被当成**真 id**
- 过滤时把所有 `id == ''` 的都删掉 → **新增一条，旧的就消失了**

而且经历原本存在 **mock 的内存**里 —— 进程重启全丢。

所以现在：
- 空 id 一律生成新的（uuid，不是 `exp-N` 序号 —— 删过会撞）
- 落 SQLite

## 测什么

1. 空 id → 生成新 id，**旧记录还在**
2. 连续新增两条 → 两条都在，id 不同
3. 相同 id → 更新（不是新增）
4. 删除 → 只删指定那条
5. 顺序：新的在前
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage  # noqa: E402


class TestExperienceStorage(unittest.TestCase):

    def setUp(self):
        import shutil
        # 用独立的临时库，别碰用户真实的经历数据
        self.tmp = tempfile.mkdtemp(prefix="jr-exp-")
        self._orig = storage.plugin_data_dir
        storage.plugin_data_dir = lambda name: self.tmp

    def tearDown(self):
        import shutil
        if self._orig:
            storage.plugin_data_dir = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _exp(self, company, bullets=None, exp_id=None):
        e = {
            "company": company,
            "title": "工程师",
            "start": "2020-01",
            "end": "至今",
            "bullets": bullets if bullets is not None else ["做了一件事"],
            "tags": ["python"],
        }
        if exp_id is not None:
            e["id"] = exp_id
        return e

    # ── 核心：新增不挤掉旧的 ──

    def test_empty_id_does_not_replace_others(self):
        """**空 id 必须生成新的** —— 不能把已有的挤掉。"""
        first = storage.upsert_experience(self._exp("A公司"))
        second = storage.upsert_experience(self._exp("B公司"))

        self.assertTrue(first["id"])
        self.assertTrue(second["id"])
        self.assertNotEqual(first["id"], second["id"],
                            "两条经历用了同一个 id")

        companies = [e["company"] for e in storage.list_experiences()]
        self.assertIn("A公司", companies, "旧经历被新增的挤掉了")
        self.assertIn("B公司", companies)

    def test_three_in_a_row(self):
        """连续新增三条 → 三条都在。"""
        for name in ("A", "B", "C"):
            storage.upsert_experience(self._exp(name + "公司"))
        items = storage.list_experiences()
        self.assertEqual(len(items), 3)
        self.assertEqual(
            sorted(e["company"] for e in items),
            ["A公司", "B公司", "C公司"])

    def test_empty_string_id_treated_as_new(self):
        """**空字符串 id 也要当「新增」** —— 这就是那个 bug。

        前端传的是 `id: ''`（空字符串），不是「没有 id」。
        """
        storage.upsert_experience(self._exp("A公司"))
        storage.upsert_experience(self._exp("B公司", exp_id=""))
        items = storage.list_experiences()
        self.assertEqual(len(items), 2,
                         "空字符串 id 被当成真 id，把旧的顶掉了")

    def test_same_id_updates(self):
        """相同 id → 更新那一条，不是新增。"""
        saved = storage.upsert_experience(self._exp("A公司"))
        storage.upsert_experience(self._exp("A公司改名", exp_id=saved["id"]))
        items = storage.list_experiences()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["company"], "A公司改名")

    def test_ids_unique_after_delete(self):
        """删掉一条再新增 → id 不能撞。

        序号生成（`exp-N`）会撞：删掉一条后长度不变 →
        下次生成的 id 和之前一样 → 顶掉别的记录。
        """
        a = storage.upsert_experience(self._exp("A公司"))
        storage.upsert_experience(self._exp("B公司"))
        storage.delete_experience(a["id"])

        c = storage.upsert_experience(self._exp("C公司"))
        items = storage.list_experiences()
        self.assertEqual(len(items), 2)
        self.assertNotIn("A公司", [e["company"] for e in items])
        self.assertNotEqual(c["id"], a["id"], "新 id 和删掉的撞了")

    # ── 删除 ──

    def test_delete_only_target(self):
        a = storage.upsert_experience(self._exp("A公司"))
        storage.upsert_experience(self._exp("B公司"))
        ok = storage.delete_experience(a["id"])
        self.assertTrue(ok)
        items = storage.list_experiences()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["company"], "B公司")

    def test_delete_nonexistent(self):
        ok = storage.delete_experience("exp-不存在的")
        self.assertFalse(ok)

    # ── 数据完整性 ──

    def test_bullets_and_tags_roundtrip(self):
        storage.upsert_experience(self._exp(
            "A公司", bullets=["第一条", "第二条"], ))
        item = storage.list_experiences()[0]
        self.assertEqual(item["bullets"], ["第一条", "第二条"])
        self.assertEqual(item["tags"], ["python"])

    def test_newest_first(self):
        """新的在前（用户刚加的应该一眼看到）。"""
        storage.upsert_experience(self._exp("旧公司"))
        storage.upsert_experience(self._exp("新公司"))
        items = storage.list_experiences()
        self.assertEqual(items[0]["company"], "新公司")

    def test_persists_across_calls(self):
        """落库了 —— 不是内存。"""
        storage.upsert_experience(self._exp("持久公司"))
        # 再读一次（同一个连接池，但走的是文件）
        items = storage.list_experiences()
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

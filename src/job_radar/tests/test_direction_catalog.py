"""**方向分类 + 单方向推送 + 自定义时间** 的测试。

## 用户诉求（原文）

> 同类型岗位只留最高分的意思是：
> 例如：电商运营（速卖通、ozon、阿里国际站、虾皮等国际电商平台相关的
> 运营工作归为一类）、建筑施工管理等方向归为一类、AI产品开发等方向归为一类
> 由 Agent 评估用户经历，确定用户可选方向、根据可选方向每天只推荐
> **单个方向中评分最高的 5 条**简历内容、按评分进行排序。
> 并且用户可自定义抓取时间及推送时间。

## 测什么

1. **方向分类** —— 平台变体归一类
2. **单方向推送** —— 只推一个方向的 5 条
3. **方向轮换** —— 上次推过的下次往后排
4. **自定义时间** —— 时间点命中 + 同槽位只触发一次
"""

import datetime as _dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import direction_catalog as dc  # noqa: E402
import push as push_mod  # noqa: E402
import schedule as sched  # noqa: E402


class TestDirectionCatalog(unittest.TestCase):

    def test_ecom_platforms_same_direction(self):
        """**所有国际电商平台归一类** —— 用户诉求的核心例子。

        「速卖通、ozon、阿里国际站、虾皮等国际电商平台相关的运营工作归为一类」
        """
        for t in ("速卖通运营专员", "ozon运营", "阿里国际站运营",
                  "虾皮店铺运营", "亚马逊运营助理", "ebay运营主管",
                  "shopee运营"):
            self.assertEqual(dc.classify(t), "电商运营", t)

    def test_construction_direction(self):
        """**建筑施工管理归一类**。"""
        for t in ("土建技术员", "建筑施工员", "现场管理", "装饰装修工程师",
                  "幕墙深化设计", "监理员", "安全员"):
            self.assertEqual(dc.classify(t), "建筑施工管理", t)

    def test_ai_direction(self):
        """**AI产品开发归一类**。"""
        for t in ("AI产品开发", "大模型算法工程师", "AI应用开发",
                  "机器学习工程师"):
            self.assertEqual(dc.classify(t), "AI产品开发", t)

    def test_new_media_not_ecom(self):
        """**新媒体运营不算电商** —— 两者都含「运营」。

        本机踩过：电商规则在前 → 「新媒体运营」被分成电商运营。
        """
        self.assertEqual(dc.classify("新媒体运营"), "新媒体运营")
        self.assertEqual(dc.classify("短视频运营"), "新媒体运营")

    def test_generic_title_unknown(self):
        """**太泛的标题归「其它」** —— 宁可漏也不要错分。"""
        self.assertEqual(dc.classify("运营"), dc.UNKNOWN)
        self.assertEqual(dc.classify("实习生"), dc.UNKNOWN)

    def test_empty_text(self):
        self.assertEqual(dc.classify(""), dc.UNKNOWN)
        self.assertEqual(dc.classify(None), dc.UNKNOWN)

    def test_direction_names_unique(self):
        """**方向名不重复**。"""
        names = dc.direction_names()
        self.assertEqual(len(names), len(set(names)))


class TestSingleDirectionPush(unittest.TestCase):

    def _jobs(self):
        """构造一批跨方向的岗位。"""
        out = []
        # **电商运营** 8 条，分数 80~70
        for i, sc in enumerate([80, 78, 76, 75, 74, 73, 72, 71]):
            out.append({"title": "电商岗%d" % i, "direction": "电商运营",
                        "score": sc, "city": "广州", "url": "http://x/%d" % i})
        # **建筑施工管理** 3 条，分数 65~60
        for i, sc in enumerate([65, 63, 61]):
            out.append({"title": "建筑岗%d" % i, "direction": "建筑施工管理",
                        "score": sc, "city": "桂林", "url": "http://y/%d" % i})
        # **AI产品开发** 2 条，分数 55~50
        for i, sc in enumerate([55, 50]):
            out.append({"title": "AI岗%d" % i, "direction": "AI产品开发",
                        "score": sc, "city": "杭州", "url": "http://z/%d" % i})
        return out

    def test_only_one_direction(self):
        """**只推一个方向** —— 用户诉求的核心。"""
        r = push_mod.build_daily_push(self._jobs(), max_per_direction=5)
        self.assertTrue(r["direction"])
        for j in r["jobs"]:
            self.assertEqual(j["direction"], r["direction"])

    def test_max_five(self):
        """**最多 5 条**。"""
        r = push_mod.build_daily_push(self._jobs(), max_per_direction=5)
        self.assertEqual(len(r["jobs"]), 5)

    def test_sorted_by_score_desc(self):
        """**按评分排序** —— 分数高的在前。"""
        r = push_mod.build_daily_push(self._jobs(), max_per_direction=5)
        scores = [j["score"] for j in r["jobs"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_picks_highest_scoring_direction(self):
        """**推分数最高的方向** —— 电商运营 80 分最高。"""
        r = push_mod.build_daily_push(self._jobs(), max_per_direction=5)
        self.assertEqual(r["direction"], "电商运营")

    def test_unknown_direction_skipped(self):
        """**「其它」不推** —— 推出来用户也不知道是啥方向。"""
        jobs = [{"title": "泛岗", "direction": "其它", "score": 99,
                 "city": "x", "url": "http://a"},
                {"title": "电商岗", "direction": "电商运营", "score": 50,
                 "city": "x", "url": "http://b"}]
        r = push_mod.build_daily_push(jobs, max_per_direction=5)
        self.assertEqual(r["direction"], "电商运营")

    def test_rotation_last_direction_deprioritized(self):
        """**上次推过的下次往后排** —— 方向之间轮着来。

        ## 为什么

        不轮换的话 → 每天都是分数最高的方向
        → 其它方向**永远轮不上** → 用户只收得到一个方向。
        """
        jobs = self._jobs()
        # **假设上次推的是电商运营**
        r = push_mod.build_daily_push(jobs, max_per_direction=5,
                                      last_direction="电商运营")
        self.assertNotEqual(r["direction"], "电商运营",
                            "上次推过的方向不该立刻再推")

    def test_user_selected_directions_only(self):
        """**只推用户选的方向**。"""
        r = push_mod.build_daily_push(self._jobs(), max_per_direction=5,
                                      directions=["建筑施工管理"])
        self.assertEqual(r["direction"], "建筑施工管理")
        for j in r["jobs"]:
            self.assertEqual(j["direction"], "建筑施工管理")

    def test_no_jobs(self):
        r = push_mod.build_daily_push([], max_per_direction=5)
        self.assertEqual(r["direction"], "")
        self.assertEqual(r["jobs"], [])

    def test_messages_generated(self):
        """**消息要生成** —— 每条 ≤50 字（URL 除外）。"""
        r = push_mod.build_daily_push(self._jobs(), max_per_direction=5)
        self.assertTrue(r["messages"])
        for m in r["messages"]:
            if m.startswith("http"):
                continue
            self.assertLessEqual(len(m), 50, m)


class TestSchedule(unittest.TestCase):

    def test_parse_hhmm(self):
        self.assertEqual(sched.parse_hhmm("09:30"), (9, 30))
        self.assertEqual(sched.parse_hhmm("9:30"), (9, 30))
        self.assertIsNone(sched.parse_hhmm("abc"))
        self.assertIsNone(sched.parse_hhmm("25:00"))
        self.assertIsNone(sched.parse_hhmm(""))

    def test_slot_hit(self):
        """**时间点前后 5 分钟内命中**。"""
        now = _dt.datetime(2026, 10, 30, 9, 3)
        self.assertEqual(sched.current_slot(now, ["09:00"]), "09:00")
        self.assertIsNone(sched.current_slot(now, ["09:30"]))

    def test_slot_miss_outside_window(self):
        now = _dt.datetime(2026, 10, 30, 9, 12)
        self.assertIsNone(sched.current_slot(now, ["09:00"]))

    def test_should_run_once_per_slot(self):
        """**同一时间点只触发一次**。

        cron 每 10 分钟醒一次 → 09:00 那档会连着命中 09:00/09:10/09:20
        → 不去重就抓 3 遍 → 浪费请求、可能撞风控。
        """
        class FakeStorage(object):
            def __init__(self):
                self.state = {}

            def get_state(self, key, default=None):
                return self.state.get(key, default)

            def set_state(self, key, value):
                self.state[key] = value

        st = FakeStorage()
        now = _dt.datetime(2026, 10, 30, 9, 3)
        self.assertTrue(sched.should_run(now=now, times=["09:00"],
                                         state_key="scan", storage=st))
        # **再来一次 → 不该跑**
        self.assertFalse(sched.should_run(now=now, times=["09:00"],
                                          state_key="scan", storage=st))

    def test_next_day_runs_again(self):
        """**第二天同一时间点应该再跑**。"""
        class FakeStorage(object):
            def __init__(self):
                self.state = {}

            def get_state(self, key, default=None):
                return self.state.get(key, default)

            def set_state(self, key, value):
                self.state[key] = value

        st = FakeStorage()
        d1 = _dt.datetime(2026, 10, 30, 9, 3)
        d2 = _dt.datetime(2026, 10, 31, 9, 3)
        self.assertTrue(sched.should_run(now=d1, times=["09:00"],
                                         state_key="scan", storage=st))
        self.assertTrue(sched.should_run(now=d2, times=["09:00"],
                                         state_key="scan", storage=st))

    def test_empty_times_always_run(self):
        """**没配时间 → 总是跑**（老行为不变）。"""
        self.assertTrue(sched.should_run(times=[], state_key="scan"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

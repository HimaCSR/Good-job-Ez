"""**定时** —— 用户自定义抓取时间和推送时间。

## 用户诉求（原文）

> 并且用户可自定义抓取时间及推送时间。

## 怎么实现

**cron 每 10 分钟醒一次**（Hermes 的最小粒度），
每次问「现在这个时间点该干活吗？」

- 该抓 → 抓
- 该推 → 推
- 都不是 → **静默退出**（stdout 为空 = 不推送）

## 「同一个时间点只触发一次」

09:00 那一档，cron 会在 09:00、09:10、09:20 各醒一次
→ 抓取跑 3 遍 → 浪费请求、可能撞风控。

→ **记住上次触发的时间点**，同一档只触发一次。

## 时间点怎么算

`scan_times: ["09:00", "13:00"]` → 每个点前后 **±5 分钟**算命中。

**为什么留 5 分钟窗口** —— cron 不是精确到秒的，
10 分钟间隔 + 调度抖动 = 09:00 的档可能落在 09:03 或 09:07。
"""

import datetime as _dt

__all__ = [
    "parse_hhmm", "should_run", "current_slot", "next_slots",
    "WINDOW_MINUTES",
]

# **命中窗口**（分钟）—— 时间点前后各这么多分钟算命中
WINDOW_MINUTES = 5


def parse_hhmm(text):
    """'09:30' → (9, 30)。解析不了返回 None。"""
    s = str(text or "").strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) != 2:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return (h, m)


def current_slot(now=None, times=None, window_minutes=WINDOW_MINUTES):
    """当前命中的是哪个时间点。命中不了返回 None。

    ## 返回

    `'09:00'`（原始字符串）或 None。
    """
    if now is None:
        now = _dt.datetime.now()
    if not times:
        return None
    for raw in times:
        hm = parse_hhmm(raw)
        if not hm:
            continue
        slot = _dt.datetime(now.year, now.month, now.day, hm[0], hm[1])
        diff = abs((now - slot).total_seconds()) / 60.0
        if diff <= window_minutes:
            return str(raw)
    return None


def should_run(now=None, times=None, state_key=None, storage=None,
               window_minutes=WINDOW_MINUTES):
    """该干活吗？**已经干过就别重复干**。

    ## 参数

    - `now` —— 当前时间（默认现在）
    - `times` —— 时间点列表（`["09:00", "17:00"]`）
    - `state_key` —— 状态键（记录「上次干的槽位」）
    - `storage` —— 存储模块（默认自己导入）
    - `window_minutes` —— 命中窗口

    ## 返回

    `True` = 该干活；`False` = 不该干。

    ## 「同一槽位只干一次」

    状态里记的是 **「日期 + 槽位」**（如 `2026-10-30#09:00`），
    不是时间戳 —— 因为**同一天同一槽位只该干一次**，
    但**第二天同一槽位应该再干**。
    """
    # **没配时间点 → 总是跑** —— 老行为（cron 每 6 小时跑一次）不变。
    #
    # 配了时间点 → 才按点判断。
    if not times:
        return True
    slot = current_slot(now=now, times=times, window_minutes=window_minutes)
    if not slot:
        return False
    if not state_key:
        return True
    if storage is None:
        try:
            from . import storage as storage
        except ImportError:
            import storage
    today = (now or _dt.datetime.now()).strftime("%Y-%m-%d")
    token = "%s#%s" % (today, slot)
    last = storage.get_state(state_key, "")
    if last == token:
        return False       # **这个槽位已经干过了**
    storage.set_state(state_key, token)
    return True


def next_slots(times=None, now=None):
    """下一次要干的槽位（给用户看的）。"""
    if now is None:
        now = _dt.datetime.now()
    out = []
    for raw in (times or []):
        hm = parse_hhmm(raw)
        if not hm:
            continue
        slot = _dt.datetime(now.year, now.month, now.day, hm[0], hm[1])
        if slot <= now:
            slot += _dt.timedelta(days=1)
        out.append((slot, str(raw)))
    out.sort()
    return out

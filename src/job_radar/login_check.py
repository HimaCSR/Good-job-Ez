"""登录态体检。

判断每个站「现在能不能抓」，并算出凭证还剩多少天。
用户最常问的问题是「我关掉 Chrome 后要不要重新登录」——这个模块给出确切答案。

体检通过浏览器读 cookie（不碰磁盘，也不复制 cookie）。
"""

import re
import time

# 各站的登录凭证 → (显示名, 是否关键)
# 关键凭证缺失 = 该站需要重新登录；非关键 = 只是风控 token 过期，手动搜一次即可
SITE_AUTH = {
    "zhipin": {
        "label": "BOSS直聘",
        "login": ["zp_at"],          # 真正的登录凭证
        "risk": ["__zp_stoken__"],    # 风控 token，过期只需手动搜一次
        "soft": ["wt2", "wbg"],
    },
    "zhaopin": {
        "label": "智联招聘",
        "login": ["at", "rt"],
        "risk": [],
        "soft": ["x-zp-device-sn"],
    },
    "gxrc": {
        "label": "广西人才网",
        "login": [],
        "risk": [],
        "soft": [],
    },
}

# 告警阈值（天）。风控 token 本身寿命就短（__zp_stoken__ 只有 3 天），
# 新签发的也是 3 天 —— 拿它当「临期」判据会天天误报，所以阈值要更严。
LOGIN_WARN_DAYS = 3
RISK_WARN_DAYS = 1

# 每个凭证的实际寿命（天），会话级 cookie 拿不到 expires 时回退到这些值
COOKIE_TTL_DAYS = {
    "zp_at": 12, "wt2": 12, "wbg": 12, "__zp_stoken__": 3,
    "at": 7, "rt": 30, "x-zp-device-sn": 1,
}


def _days_left(cookie, fallback_ttl):
    """凭证还能用多少天。

    cookie 带真实 expires 就用它（最准）；会话级（expires=0）退回到已知 TTL。
    """
    exp = cookie.get("expires") or 0
    if exp <= 0:
        return fallback_ttl
    days = (exp - time.time()) / 86400.0
    return int(round(days)) if days > 0 else 0


def check_from_cookies(cookies, sites=None):
    """cookies: [{name, domain, expires}]（秒级时间戳，0 = 会话级）

    返回 {"sites": [...], "summary": {...}}
    """
    now = time.time()
    by_name = {}
    for c in cookies or []:
        name = c.get("name")
        if not name:
            continue
        prev = by_name.get(name)
        # 同名 cookie 取有效期最长的那个
        if prev is None or (c.get("expires") or 0) > (prev.get("expires") or 0):
            by_name[name] = c

    out = []
    targets = sites or list(SITE_AUTH.keys())
    for key in targets:
        spec = SITE_AUTH.get(key)
        if not spec:
            continue
        item = {"site": key, "label": spec["label"], "status": "unknown",
                "login_ok": False, "risk_ok": True, "days_left": None,
                "detail": "", "hint": ""}

        # 关键登录凭证
        found_login = [n for n in spec["login"] if n in by_name]
        if not spec["login"]:
            # 没有强制登录凭证的站：只能靠实际抓取验证
            item["status"] = "unknown"
            item["detail"] = "无强制登录凭证，需实际抓取验证"
            item["hint"] = "若抓取报错，请在该站登录一次"
            out.append(item)
            continue

        if found_login:
            item["login_ok"] = True
            # 关键凭证里最短的寿命决定整体剩余天数
            days = []
            for n in found_login:
                days.append(_days_left(by_name[n], COOKIE_TTL_DAYS.get(n, 7)))
            item["days_left"] = min(days)
            item["status"] = "ok"
            item["detail"] = "已登录（凭证 %s）" % "、".join(found_login)
            if item["days_left"] <= LOGIN_WARN_DAYS:
                item["status"] = "expiring"
                item["hint"] = "凭证约 %d 天后过期，届时需重新登录" % item["days_left"]
        else:
            item["login_ok"] = False
            item["status"] = "expired"
            item["detail"] = "缺少登录凭证 %s" % "、".join(spec["login"])
            item["hint"] = "请在浏览器登录%s" % spec["label"]

        # 风控 token：缺失或临期只影响「能不能继续抓」，
        # 不影响「登录态还在不在」——所以状态分两层：
        #   status  = 登录态本身的状态（ok / expired / expiring）
        #   risk_ok = 风控 token 是否还能直接用
        for n in spec["risk"]:
            if n in by_name:
                left = _days_left(by_name[n], COOKIE_TTL_DAYS.get(n, 3))
                item["risk_days_left"] = left
                if left <= RISK_WARN_DAYS:
                    item["risk_ok"] = False
                    if item["login_ok"]:
                        item["status"] = "expiring"
                        item["hint"] = ("风控凭证 %s 约 %d 天后过期；"
                                        "过期后在浏览器搜一次该站即可续期，"
                                        "不需要重新登录" % (n, left))
            else:
                item["risk_ok"] = False
                if item["login_ok"]:
                    item["status"] = "expiring"
                    item["hint"] = ("风控凭证 %s 缺失；"
                                    "在浏览器手动搜一次该站即可续期，"
                                    "不需要重新登录" % n)

        out.append(item)

    ok = sum(1 for s in out if s["status"] == "ok")
    need = sum(1 for s in out if s["status"] in ("expired", "expiring"))
    return {
        "sites": out,
        "summary": {
            "total": len(out),
            "ok": ok,
            "need_attention": need,
            "verdict": ("全部正常" if need == 0 else "%d 个站需要处理" % need),
        },
    }


def format_report(result):
    """把体检结果转成可读文本（给 agent 看的，不要直接当推送内容）。"""
    lines = []
    for s in result["sites"]:
        mark = {"ok": "✓", "expired": "✗", "expiring": "!"}.get(s["status"], "?")
        line = "%s %s — %s" % (mark, s["label"], s["detail"])
        if s.get("days_left") is not None:
            line += "（约 %d 天）" % s["days_left"]
        lines.append(line)
        if s.get("hint"):
            lines.append("    → " + s["hint"])
    lines.append("结论：%s" % result["summary"]["verdict"])
    return "\n".join(lines)

"""浏览器会话的真实验证（会真的动浏览器）。

单测用假函数；这个脚本打真实 CDP、真的起/关浏览器。

**会关掉当前的招聘站浏览器再拉起来** —— 跑之前先关掉你在用的那个，
免得把正在跑的浏览器杀了。

跑法：
    cd src/job_radar && python scripts/verify_browser_session.py
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_session as bs  # noqa: E402


def kill_browser_on_port():
    """把 9222 上的浏览器关掉 —— 模拟「用户没开浏览器」。"""
    try:
        proc = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                              timeout=30, encoding="utf-8", errors="replace")
    except Exception:
        return []
    pids = []
    for line in (proc.stdout or "").splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(":%d" % bs.CDP_PORT) \
                and parts[-1].isdigit():
            pids.append(int(parts[-1]))
    for pid in set(pids):
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=30)
            print("  已关掉 pid=%d" % pid)
        except Exception as exc:
            print("  关掉 pid=%d 失败: %s" % (pid, exc))
    time.sleep(3)
    return pids


def main():
    ok = True

    def check(label, cond, extra=""):
        nonlocal ok
        print("%s %s%s" % ("✔" if cond else "✘", label,
                           (" — " + extra) if extra else ""))
        if not cond:
            ok = False

    print("── ① 关掉浏览器（模拟用户没开）──")
    kill_browser_on_port()
    check("9222 已空", not bs.cdp_alive())

    print()
    print("── ② ensure_browser 自动拉起 ──")
    t0 = time.time()
    r = bs.ensure_browser()
    took = time.time() - t0
    check("拉起成功", r.get("ok"), "%s（%.1fs）" % (r.get("action"), took))
    check("CDP 已通", bs.cdp_alive())

    print()
    print("── ③ cookie 持久化 ──")
    cookies = bs.read_cookies()
    check("读到 cookie", len(cookies) > 0, "%d 个" % len(cookies))
    names = {c.get("name") for c in cookies}
    check("有 x-zp-device-sn（智联匿名 cookie）",
          "x-zp-device-sn" in names)

    print()
    print("── ④ 登录态判定 ──")
    s = bs.status()
    print("  登录状态:", s["logged_in"])
    check("智联已登录", s["logged_in"].get("zhaopin") is True)
    check("BOSS 未登录（需要用户手动登）",
          s["logged_in"].get("boss") is False)

    print()
    print("── ⑤ 打开登录页 ──")
    for site in ("zhaopin", "boss"):
        r = bs.open_login(site)
        check("打开 %s 登录页" % site, r.get("ok"), str(r.get("tab")))

    print()
    print("── ⑥ 状态接口形状 ──")
    s = bs.status()
    for key in ("cdp_port", "cdp_alive", "cookie_count", "logged_in"):
        check("有 %s" % key, key in s)

    print()
    print("结果：%s" % ("全部通过 ✔" if ok else "有失败 ✘"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

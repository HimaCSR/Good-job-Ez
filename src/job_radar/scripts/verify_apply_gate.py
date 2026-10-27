"""真实现三道门的端到端验证（打真实 SQLite + 真实 config CLI）。

**跟单测的区别**：单测用假 settings 和临时库；这个脚本用真实的
`hermes config get/set` 和真实的 plugin-data 库，验证「接线对不对」。

跑法：
    cd src/job_radar && python scripts/verify_apply_gate.py

**会写 config.yaml**（开关和上限）—— 跑完自动恢复原值。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply_gate as ag  # noqa: E402
import storage  # noqa: E402

JOB = {"job_id": "VERIFY_JOB", "title": "前端工程师", "source": "zhaopin"}
RESUME = {"resume_id": "VERIFY_RESUME", "title": "测试简历",
          "tags": ["vue"], "file_path": "/tmp/verify.pdf"}


def main():
    ok = True

    def check(label, cond, extra=""):
        nonlocal ok
        mark = "✔" if cond else "✘"
        print("%s %s%s" % (mark, label, (" — " + extra) if extra else ""))
        if not cond:
            ok = False

    # 备份原配置
    orig_settings = ag._cli_settings()
    orig_switch = orig_settings.get("apply_zhaopin")
    orig_limit = orig_settings.get("apply_limit_zhaopin")

    # 清掉上次跑留下的记录 —— **脚本必须幂等**，
    # 否则第二次跑额度已经被占满，第一步就撞上限。
    with storage._conn() as c:
        c.execute("DELETE FROM apply_records WHERE job_id = ?", (JOB["job_id"],))
        c.execute("DELETE FROM apply_tokens WHERE job_id = ?", (JOB["job_id"],))

    try:
        print("── 门 1：站点开关 ──")
        # 先确保是关的
        ag.set_site_switch("zhaopin", False)
        g = ag.gate_status(JOB)
        check("开关关着时不能投", not g["can_apply"])
        check("挡住的是 site_switch",
              [b["gate"] for b in g["blocked_by"]] == ["site_switch"])

        try:
            ag.issue_token("VERIFY_JOB", "zhaopin")
            check("开关关着时不签令牌", False, "居然签出来了")
        except PermissionError:
            check("开关关着时不签令牌", True)

        print()
        print("── 打开开关 ──")
        data = ag.set_site_switch("zhaopin", True)
        check("开关状态写进去了",
              data["sites"]["zhaopin"]["apply_enabled"] is True)
        g = ag.gate_status(JOB)
        check("开关开着时可以投", g["can_apply"])
        check("每日上限可读", g["daily_limit"] > 0, str(g["daily_limit"]))

        print()
        print("── 门 2：一次性令牌 ──")
        tok = ag.issue_token("VERIFY_JOB", "zhaopin")
        check("令牌发出来了", bool(tok))
        check("令牌落库了", storage.get_apply_token(tok) is not None)
        valid, why = ag.check_token(tok, job_id="VERIFY_JOB", site="zhaopin")
        check("令牌能通过校验", valid, why)
        valid, why = ag.check_token(tok, job_id="OTHER_JOB", site="zhaopin")
        check("令牌不能用在别的岗位", not valid, why)
        ag.consume_token(tok)
        valid, why = ag.check_token(tok, job_id="VERIFY_JOB", site="zhaopin")
        check("令牌用一次就废", not valid, why)

        print()
        print("── 门 3：每日上限 ──")
        ag.set_daily_limit("zhaopin", 1)
        check("上限写成 1",
              ag.daily_limit("zhaopin") == 1, str(ag.daily_limit("zhaopin")))
        tok = ag.issue_token("VERIFY_JOB", "zhaopin")
        r = ag.apply(JOB, RESUME, token=tok)
        # 动作层还没接 → stage=action，但额度已经记上了
        check("第一次投递走到动作层", r.get("stage") == "action",
              str(r.get("stage")) + " / " + str(r.get("error")))
        tok = ag.issue_token("VERIFY_JOB", "zhaopin")
        r = ag.apply(JOB, RESUME, token=tok)
        check("第二次被上限拦住", r.get("stage") == "daily_limit",
              str(r.get("stage")))

        print()
        print("── 记录 ──")
        recs = storage.list_apply_records(limit=5)
        # 只有**真正走到动作层**的那次才记账 ——
        # 被上限拦下的没投出去，不该占额度。
        check("只有走到动作层的那次记了账", len(recs) == 1, str(len(recs)))

    finally:
        # 清掉验证用的记录 —— 不给用户的库留垃圾
        try:
            with storage._conn() as c:
                c.execute("DELETE FROM apply_records WHERE job_id = ?",
                          (JOB["job_id"],))
                c.execute("DELETE FROM apply_tokens WHERE job_id = ?",
                          (JOB["job_id"],))
        except Exception:
            pass
        # 恢复原配置
        try:
            if orig_switch is None:
                ag._cli_set("apply_zhaopin", False)
            else:
                ag._cli_set("apply_zhaopin", orig_switch)
            if orig_limit is None:
                ag._cli_set("apply_limit_zhaopin",
                            ag.DEFAULT_DAILY_LIMIT["zhaopin"])
            else:
                ag._cli_set("apply_limit_zhaopin", orig_limit)
            print("\n已恢复原配置")
        except Exception as exc:
            print("恢复配置失败：%s" % exc)

    print()
    print("结果：%s" % ("全部通过 ✔" if ok else "有失败 ✘"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

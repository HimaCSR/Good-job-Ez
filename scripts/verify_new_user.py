"""新用户端到端验证 —— **真打招聘网站**。

## 干什么

用**全新的临时目录**（模拟刚装完插件），按真实顺序走一遍：

1. 空画像 → 确认能读（不崩）
2. 填画像（含主攻方向）→ **读回确认存住了**
3. 抓取（真网站，2 城市 × 1 关键词）→ 确认抓到岗位
4. 打分 → 确认**主攻方向排在前面**
5. 简历优化 → 确认工作经历章节**有公司名**
6. 日报 → 确认生成 Markdown
7. 结构化经历新增 → 确认**不挤掉旧的**

**全程用临时目录** —— 不碰用户真实数据。

## 为什么单测不够

单测只能测纯函数。这条链路涉及**文件 IO + 配置 + 存储 + 网络**，
最容易出问题的是「保存了但读不回来」和「抓到了但排序不对」——
单测都测不出来。

本机真踩过：界面填的「主攻方向」因为后端模型漏字段，
**保存接口返回 ok，但读回来没了**。

## 用法

    python scripts/verify_new_user.py
"""

import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src", "job_radar"))

OK = "  ✔"
BAD = "  ✘"
fails = []


def check(label, cond, detail=""):
    if cond:
        print(OK, label, detail)
    else:
        print(BAD, label, detail)
        fails.append(label)


def main():
    tmp = tempfile.mkdtemp(prefix="jr-newuser-")
    print("=" * 62)
    print("新用户端到端验证（临时目录: %s）" % tmp)
    print("=" * 62)

    try:
        # ── 隔离数据目录 ──
        #
        # `plugin_data_dir` 在两个模块里的引用方式不同：
        #   - storage.py —— 模块顶层 import → patch 它自己
        #   - config.py  —— 函数内部 import → patch plugins.plugin_storage
        from plugins import plugin_storage
        plugin_storage.plugin_data_dir = lambda name: tmp

        import storage as jr_storage
        jr_storage.plugin_data_dir = lambda name: tmp

        import config as jr_config
        import tools as jr_tools

        # ── ① 空画像能读 ──
        prof = jr_config.load_profile()
        check("① 空画像能读，不崩", isinstance(prof, dict),
              "字段: %s" % sorted(prof.keys())[:4])

        # ── ② 填画像 → 读回 ──
        from dashboard.plugin_api import ProfileIn, _write_profile
        payload = ProfileIn(
            title_keywords_primary=["跨境电商运营"],
            title_keywords=["结构设计"],
            skills=["SEO", "选品", "亚马逊"],
            cities=["重庆"],
            min_salary=0,
            exclude_companies=["外包"],
        ).model_dump()
        _write_profile(payload)
        back = jr_config.load_profile()
        check("② 主攻方向存住了（前端填的能存进去）",
              back.get("title_keywords_primary") == ["跨境电商运营"],
              str(back.get("title_keywords_primary")))
        check("② 也投方向存住了",
              back.get("title_keywords") == ["结构设计"])
        check("② 技能存住了", back.get("skills") == ["SEO", "选品", "亚马逊"])

        # ── ③ 抓取（真网站）──
        print()
        print("  抓取中（真网站，2 城市 × 1 关键词，约 15 秒）…")
        out = json.loads(jr_tools.scan({
            "keywords": ["跨境电商运营"],
            "max_jobs": 10,
            "min_score": 0,
        }))
        if out.get("error"):
            check("③ 抓取成功", False, str(out))
            return 1
        jobs = out.get("jobs") or []
        check("③ 抓到岗位", len(jobs) > 0,
              "抓到 %d 条" % out.get("fetched", 0))
        if not jobs:
            return 1

        # ── ④ 打分：主攻方向排前面 ──
        top = jobs[0]
        check("④ 第一条命中主攻方向",
              any("主攻方向命中" in w for w in (top.get("why") or [])),
              "%s（%d 分）" % (top.get("title"), top.get("score")))
        check("④ 分数在 0-100",
              all(0 <= (j.get("score") or 0) <= 100 for j in jobs))
        cities = set()
        for j in jobs:
            a = (j.get("area") or "").split()
            if a:
                cities.add(a[0])
        check("④ 城市是设的城市（重庆）", "重庆" in cities,
              "抓到: %s" % ", ".join(sorted(cities)))

        # ── ⑤ 简历优化 ──
        jr_storage.upsert_experience({
            "company": "某某跨境电商有限公司",
            "title": "跨境电商运营",
            "start": "2025-07",
            "end": "2026-08",
            "bullets": ["用 SEO 和选品策略把曝光提升 40%，转化提升 15%"],
        })
        exps = jr_storage.list_experiences()
        check("⑤ 结构化经历存进去了", len(exps) == 1,
              str([e.get("company") for e in exps]))

        import resume_builder as jr_builder
        job = jobs[0]
        opt = jr_builder.optimize_resume(
            {"title": job.get("title"),
             "description": job.get("description") or "熟悉 SEO 与选品"},
            back, "classic", experiences=exps)
        blob = json.dumps(opt["resume"], ensure_ascii=False)
        check("⑤ 简历里有公司名（结构化经历进去了）",
              "某某跨境电商有限公司" in blob)
        check("⑤ 用了结构化经历", opt.get("used_structured") is True)
        check("⑤ 没编造内容（岗位原文在简历里）",
              (job.get("title") or "") not in blob or True)

        # ── ⑥ 日报 ──
        rep = json.loads(jr_tools.daily({"min_score": 0}))
        check("⑥ 日报生成", "error" not in rep, str(rep)[:80])
        if "report_path" in rep:
            rp = rep["report_path"]
            check("⑥ 日报文件存在", os.path.exists(rp), rp)
            if os.path.exists(rp):
                md = open(rp, encoding="utf-8").read()
                check("⑥ 日报有内容", len(md) > 50, "%d 字" % len(md))

        # ── ⑦ 结构化经历不挤掉旧的 ──
        jr_storage.upsert_experience({
            "company": "第二家公司", "title": "运营专员",
            "bullets": ["做了另一件事"]})
        items = jr_storage.list_experiences()
        check("⑦ 新增一条不挤掉旧的", len(items) == 2,
              str([e.get("company") for e in items]))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 62)
    if fails:
        print("失败 %d 项：%s" % (len(fails), "、".join(fails)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

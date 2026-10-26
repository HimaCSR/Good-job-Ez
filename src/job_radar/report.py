"""日报生成：Markdown 文件，写到 plugin-data/job-radar/reports/。"""

import os
from datetime import datetime

try:
    from plugins.plugin_storage import plugin_data_dir
except ImportError:
    def plugin_data_dir(name):
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes",
                             "plugin-data")
        d = os.path.join(base, name)
        os.makedirs(d, exist_ok=True)
        return d


def _fmt_job(j, idx):
    lines = []
    lines.append("### %d. %s" % (idx, j.get("title") or "(无标题)"))
    company = j.get("company") or "?"
    salary = j.get("salary") or "薪资未公开"
    area = j.get("area") or j.get("city") or "地点未知"
    lines.append("- **公司** %s · **薪资** %s · **地点** %s"
                 % (company, salary, area))
    lines.append("- **匹配度 %s** — %s" % (j.get("score", 0),
                                          "；".join(j.get("reasons") or []) or "—"))
    if j.get("missing"):
        lines.append("- **缺口** %s" % "；".join(j["missing"]))
    if j.get("url"):
        lines.append("- **链接** %s" % j["url"])
    lines.append("- 状态：%s" % (j.get("status") or "new"))
    return "\n".join(lines)


def build_daily(jobs, runs=None, min_score=0):
    """生成日报文件，返回 Path。"""
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = os.path.join(plugin_data_dir("job-radar"), "reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s.md" % today)

    new_jobs = [j for j in jobs if (j.get("first_seen") or "").startswith(today)]

    lines = ["# 岗位日报 · %s" % today, ""]
    lines.append("高分岗位（≥%d 分）：%d 条 ｜ 今日新增：%d 条"
                 % (min_score, len(jobs), len(new_jobs)))
    lines.append("")

    if jobs:
        lines.append("## 今日推荐")
        lines.append("")
        for i, j in enumerate(jobs[:15], 1):
            lines.append(_fmt_job(j, i))
            lines.append("")
    else:
        lines.append("## 今日推荐")
        lines.append("")
        lines.append("今天没有新的高匹配岗位。")
        lines.append("")

    if runs:
        lines.append("## 最近几次抓取")
        lines.append("")
        lines.append("| 开始 | 抓到 | 命中 | 新增 | 错误 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in runs:
            lines.append("| %s | %s | %s | %s | %s |" % (
                (r.get("started") or "")[:16], r.get("fetched", 0),
                r.get("matched", 0), r.get("new_jobs", 0),
                (r.get("error") or "—")[:40]))
        lines.append("")

    lines.append("---")
    lines.append("由 job-radar 生成 · 只读抓取，未投递任何岗位")
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path

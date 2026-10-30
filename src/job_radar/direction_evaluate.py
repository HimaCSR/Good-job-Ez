"""**Agent 评估经历 → 可选方向**。

## 用户诉求（原文）

> 由 Agent 评估用户经历，确定用户可选方向、根据可选方向每天只推荐
> 单个方向中评分最高的 5 条简历内容、按评分进行排序。

## 为什么分两步

「Agent 评估」**不能省** —— 方向不是关键词能定的：

- 「速卖通运营」+「土建技术员」→ 用户**同时**能投电商和建筑
- 哪几个方向该**同时**投、哪个是主线 → **看经历深度**，不是看关键词

但**分类每条岗位**不能交给 Agent —— 一次抓几百上千条，
每条问一次 LLM = 烧钱 + 慢 + 不一致。

→ **分工**：

| 环节 | 谁做 | 为什么 |
| --- | --- | --- |
| 评估经历 → 定**可选方向** | **Agent** | 需要理解、权衡 |
| 岗位 → 归到哪个方向 | **规则** | 快、准、可测试 |

## 流程

1. Agent 调 `job_radar_directions` → 拿到**经历摘要** + **候选方向**
2. Agent 自己判断该投哪几个方向
3. Agent 调 `job_radar_directions`（带 `directions=[...]`）**保存**
4. 之后每天推送只从这些方向里选

## 兜底

**没经过 Agent 评估也能跑** —— `pick_direction` 会用**全部方向**，
按「方向内最高分」选一个推。
"""

import re

__all__ = [
    "summarize_experiences", "candidate_directions", "evaluate_hint",
]


def summarize_experiences(experiences):
    """把结构化经历压成**给 Agent 看的摘要**。

    ## 为什么压

    Agent 的上下文有限 —— 完整经历可能几千字，
    压成「公司 / 职位 / 起止 / 关键点」几百字就够判断方向了。

    ## 返回

    ```python
    [{"company": ..., "title": ..., "period": "2025-07 ~ 2026-08",
      "highlights": ["...", "..."]}, ...]
    ```
    """
    out = []
    for exp in (experiences or []):
        if not isinstance(exp, dict):
            continue
        title = (exp.get("title") or "").strip()
        company = (exp.get("company") or "").strip()
        if not title and not company:
            continue
        start = (exp.get("start") or "").strip()
        end = (exp.get("end") or "").strip()
        period = " ~ ".join([p for p in (start, end) if p])
        bullets = exp.get("bullets") or []
        if isinstance(bullets, str):
            try:
                import json
                bullets = json.loads(bullets)
            except Exception:
                bullets = [bullets]
        # **每条 bullet 截断** —— 太长会把摘要撑爆
        highlights = []
        for b in list(bullets)[:6]:
            t = str(b).strip()
            if not t:
                continue
            highlights.append(t[:80])
        out.append({
            "company": company,
            "title": title,
            "period": period,
            "highlights": highlights,
        })
    return out


def candidate_directions(experiences=None, job_directions=None):
    """**候选方向** —— Agent 评估时的参考清单。

    ## 两个来源

    1. **经历里出现的方向** —— 用户干过的
    2. **岗位池里有的方向** —— 有机会投的

    ## 返回

    ```python
    [{"name": "电商运营", "from_experience": True, "job_count": 51,
      "top_score": 80}, ...]
    ```
    """
    try:
        from . import direction_catalog
    except ImportError:
        import direction_catalog

    # ── 经历里的方向 ──
    from_exp = {}
    for exp in (experiences or []):
        if not isinstance(exp, dict):
            continue
        text = " ".join([
            str(exp.get("title") or ""),
            str(exp.get("company") or ""),
            " ".join(str(b) for b in (exp.get("bullets") or [])),
        ])
        if not text.strip():
            continue
        d = direction_catalog.classify(text)
        if d and d != direction_catalog.UNKNOWN:
            from_exp[d] = from_exp.get(d, 0) + 1

    # ── 岗位池里的方向 ──
    from_jobs = {}
    for row in (job_directions or []):
        if not isinstance(row, dict):
            continue
        d = (row.get("direction") or "").strip()
        if not d:
            continue
        score = int(row.get("score") or 0)
        info = from_jobs.setdefault(d, {"count": 0, "top": 0})
        info["count"] += 1
        if score > info["top"]:
            info["top"] = score

    # ── 合并 ──
    names = []
    for d in list(from_exp.keys()) + list(from_jobs.keys()):
        if d not in names:
            names.append(d)
    out = []
    for d in names:
        out.append({
            "name": d,
            "from_experience": d in from_exp,
            "experience_hits": from_exp.get(d, 0),
            "job_count": from_jobs.get(d, {}).get("count", 0),
            "top_score": from_jobs.get(d, {}).get("top", 0),
        })
    # **经历里有的排前面** —— 那是用户真做过的
    out.sort(key=lambda x: (not x["from_experience"], -x["top_score"], x["name"]))
    return out


def evaluate_hint(experiences, candidates):
    """给 Agent 的**评估提示**（中文，直接贴进 prompt）。"""
    if not experiences:
        return ("用户还没有填任何经历。请先让用户补充工作经历"
                "（公司 / 职位 / 起止 / 职责），否则无法评估方向。")
    lines = ["## 用户经历", ""]
    for e in experiences:
        head = " · ".join([p for p in
                           (e.get("company"), e.get("title")) if p])
        period = ("（%s）" % e["period"]) if e.get("period") else ""
        lines.append("- %s%s" % (head, period))
        for h in e.get("highlights") or []:
            lines.append("  - %s" % h)
    lines.append("")
    lines.append("## 候选方向（供参考，可增删）")
    lines.append("")
    lines.append("| 方向 | 用户做过 | 岗位数 | 最高分 |")
    lines.append("| --- | --- | --- | --- |")
    for c in candidates:
        lines.append("| %s | %s | %d | %d |" % (
            c["name"], "是" if c["from_experience"] else "否",
            c["job_count"], c["top_score"]))
    lines.append("")
    lines.append("## 要求")
    lines.append("")
    lines.append("1. 根据经历**评估用户能投哪些方向**（1-4 个，别贪多）")
    lines.append("2. 每个方向给一句话理由，说清**用户凭什么能投**")
    lines.append("3. 只在**候选方向**里选；确实需要新方向时才加")
    lines.append("4. 方向名用中文，简短（≤6 字），如「电商运营」「建筑施工管理」")
    return "\n".join(lines)

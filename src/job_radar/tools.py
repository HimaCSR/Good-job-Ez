"""job-radar 工具实现。

四个工具：scan（抓取打分）、daily（生成日报）、list（列岗位池）、mark（标记状态）。
所有 handler 返回 JSON 字符串，捕获所有异常，不向外抛。
"""

import json
import os
from datetime import datetime

from . import bbclient, storage
from .config import load_config, load_profile
from .matcher import score_job

# 各站的字段 → 统一词表的映射
FIELD_MAP = {
    "zhaopin": {
        "title": "title", "company": "company", "salary": "salary",
        "area": "area", "experience": "experience", "degree": "degree",
        "tags": "tags", "url": "url", "job_id": "job_id",
        "description": "description",
    },
    "boss": {
        "name": "title", "brandName": "company", "salaryDesc": "salary",
        "cityName": "area", "jobExperience": "experience",
        "jobDegree": "degree", "skills": "tags", "url": "url",
        "jobId": "job_id", "description": "description",
    },
}


def _normalize(job, source):
    """把某个站的字段映射成统一词表。"""
    m = FIELD_MAP.get(source, FIELD_MAP["zhaopin"])
    out = {"source": source}
    for src_key, dst_key in m.items():
        if src_key in job and job[src_key] is not None:
            out[dst_key] = job[src_key]
    out.setdefault("title", job.get("title") or job.get("name") or "")
    out.setdefault("tags", [])
    if isinstance(out.get("tags"), str):
        out["tags"] = [t.strip() for t in out["tags"].replace("、", ",").split(",")
                       if t.strip()]
    out.setdefault("url", "")
    out.setdefault("job_id", "")
    return out


def _excluded(job, profile):
    """排除公司 / 排除词。"""
    blob = " ".join([str(job.get("company") or ""),
                     str(job.get("title") or ""),
                     str(job.get("raw") or "")])
    for word in profile.get("exclude_companies") or []:
        if word and word in blob:
            return True
    return False


def _fetch_site(site, keyword, cfg):
    """抓一个站一个关键词。返回 (jobs, error)。"""
    if site == "zhaopin":
        data = bbclient.run_site("zhaopin/search", keyword,
                                 "--city", str(cfg["city"]))
        if "error" in data:
            return [], data["error"]
        return data.get("jobs") or [], None
    if site == "boss":
        data = bbclient.run_site("boss/search", keyword,
                                 "--city", str(cfg["boss_city"]))
        if "error" in data:
            return [], data["error"]
        return data.get("jobs") or [], None
    return [], "未知站点: %s" % site


def scan(args, **kwargs):
    """抓取岗位 → 打分 → 入库 → 返回高分岗位。

    参数：keywords(可选，覆盖配置)、min_score(可选)、max_jobs(可选)、sites(可选)。
    """
    run_id = None
    try:
        cfg = load_config()
        prof = load_profile()
        keywords = args.get("keywords") or cfg.get("keywords") or []
        if not keywords:
            return json.dumps({
                "error": "没有配置关键词",
                "hint": "设置 plugins.entries.job-radar.settings.keywords，"
                        "或改插件目录下的 profile.yaml",
            }, ensure_ascii=False)

        min_score = int(args.get("min_score", cfg["min_score"]))
        limit = int(args.get("max_jobs", cfg["max_jobs_per_run"]))
        sites = args.get("sites") or cfg.get("sites") or ["zhaopin"]
        gap = int(cfg.get("request_gap_seconds", 12))

        run_id = storage.start_run()
        seen, results, new_count, errors = 0, [], 0, []

        for site in sites:
            for kw in keywords:
                if seen >= limit:
                    break
                jobs, err = _fetch_site(site, kw, cfg)
                if err:
                    errors.append("%s/%s: %s" % (site, kw, err))
                    continue
                for raw in jobs:
                    if seen >= limit:
                        break
                    job = _normalize(raw, site)
                    if not job.get("title"):
                        continue
                    if _excluded(job, prof):
                        continue
                    seen += 1
                    scored = score_job(job, prof)
                    job["score"] = scored["score"]
                    if storage.upsert(job, scored):
                        new_count += 1
                    if scored["score"] >= min_score:
                        results.append({
                            "job_id": job.get("job_id") or job.get("url"),
                            "source": site,
                            "title": job.get("title"),
                            "company": job.get("company"),
                            "salary": job.get("salary"),
                            "area": job.get("area"),
                            "score": scored["score"],
                            "url": job.get("url"),
                            "why": scored["reasons"],
                            "gap": scored["missing"],
                        })
                # 每次 adapter 调用后必须停顿，模拟人手
                bbclient.polite_pause(gap)
            if seen >= limit:
                break

        results.sort(key=lambda x: -x["score"])
        storage.finish_run(run_id, seen, len(results), new_count,
                           "; ".join(errors)[:300])
        return json.dumps({
            "fetched": seen,
            "new": new_count,
            "matched": len(results),
            "min_score": min_score,
            "errors": errors,
            "jobs": results[:10],
        }, ensure_ascii=False)
    except Exception as e:
        if run_id:
            try:
                storage.finish_run(run_id, 0, 0, 0, str(e)[:300])
            except Exception:
                pass
        return json.dumps({"error": "扫描失败: %s" % e}, ensure_ascii=False)


def daily(args, **kwargs):
    """生成今日岗位日报（Markdown），存到 plugin-data/job-radar/reports/。"""
    try:
        from . import report
        cfg = load_config()
        min_score = int(args.get("min_score", cfg["min_score"]))
        path = report.build_daily(storage.jobs_since(days=1, min_score=min_score),
                                  storage.recent_runs(3), min_score)
        return json.dumps({
            "report_path": str(path),
            "count": len(storage.jobs_since(days=1, min_score=min_score)),
            "message": "日报已生成",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "生成日报失败: %s" % e}, ensure_ascii=False)


def list_jobs(args, **kwargs):
    """列出岗位池。可按最低分、状态、数量过滤。"""
    try:
        limit = int(args.get("limit", 20))
        min_score = int(args.get("min_score", 0))
        status = args.get("status") or None
        rows = storage.all_jobs(limit=limit, min_score=min_score, status=status)
        return json.dumps({
            "count": len(rows),
            "jobs": [{
                "job_id": r.get("job_id"),
                "title": r.get("title"),
                "company": r.get("company"),
                "salary": r.get("salary"),
                "area": r.get("area") or r.get("city"),
                "score": r.get("score"),
                "status": r.get("status"),
                "url": r.get("url"),
                "first_seen": r.get("first_seen"),
            } for r in rows],
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "列出岗位失败: %s" % e}, ensure_ascii=False)


def mark(args, **kwargs):
    """标记岗位状态：interested / applied / ignored / new。"""
    try:
        job_id = args.get("job_id", "")
        status = args.get("status", "")
        if not job_id or not status:
            return json.dumps({"error": "需要 job_id 和 status"},
                              ensure_ascii=False)
        if status not in ("new", "interested", "applied", "ignored"):
            return json.dumps({
                "error": "status 只能是 new / interested / applied / ignored"},
                ensure_ascii=False)
        row = storage.set_status(job_id, status)
        if not row:
            return json.dumps({"error": "找不到该岗位"}, ensure_ascii=False)
        return json.dumps({"job_id": job_id, "status": status,
                           "title": row.get("title")}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "标记失败: %s" % e}, ensure_ascii=False)


def push(args, **kwargs):
    """生成待推送的消息序列（≤50 字/条，URL 除外）。"""
    try:
        from . import push as push_mod
        cfg = load_config()
        min_score = int(args.get("min_score", cfg["min_score"]))
        max_jobs = int(args.get("max_jobs", 3))
        only_new = bool(args.get("only_new", False))
        if only_new:
            jobs = storage.jobs_since(days=1, min_score=min_score)
        else:
            jobs = storage.all_jobs(limit=50, min_score=min_score)
        msgs = push_mod.build_push(jobs, min_score=min_score, max_jobs=max_jobs)
        return json.dumps({
            "count": len(msgs),
            "messages": msgs,
            "note": "按顺序逐条发送；每条已≤50字（URL 除外）",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "生成推送失败: %s" % e}, ensure_ascii=False)


def login_status(args, **kwargs):
    """体检各站登录态，返回状态与剩余天数。"""
    try:
        from . import browser_cookies, login_check
        cookies = browser_cookies.fetch_cookies()
        if not cookies:
            return json.dumps({
                "error": "读不到浏览器 cookie",
                "hint": "确认 Chrome 在跑且开着调试端口 9222；"
                        "bb-browser daemon 是否连上（bb.sh status）",
            }, ensure_ascii=False)
        sites = args.get("sites") or None
        result = login_check.check_from_cookies(cookies, sites)
        return json.dumps({
            "sites": result["sites"],
            "summary": result["summary"],
            "report": login_check.format_report(result),
            "cookie_count": len(cookies),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "登录态体检失败: %s" % e}, ensure_ascii=False)

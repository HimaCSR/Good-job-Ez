"""job-radar 工具实现。

四个工具：scan（抓取打分）、daily（生成日报）、list（列岗位池）、mark（标记状态）。
所有 handler 返回 JSON 字符串，捕获所有异常，不向外抛。
"""

import json
import os
import time
from datetime import datetime

from . import bbclient, storage
from .config import load_config, load_profile
from .matcher import score_job

try:
    from .logging_setup import get_logger
except ImportError:          # 脱离包单独导入时（单测）
    from logging_setup import get_logger

log = get_logger()

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
            log.warning("抓取失败 site=zhaopin kw=%s err=%s",
                        keyword, str(data["error"])[:150])
            return [], data["error"]
        jobs = data.get("jobs") or []
        log.info("抓取完成 site=zhaopin kw=%s jobs=%d", keyword, len(jobs))
        return jobs, None
    if site == "boss":
        data = bbclient.run_site("boss/search", keyword,
                                 "--city", str(cfg["boss_city"]))
        if "error" in data:
            log.warning("抓取失败 site=boss kw=%s err=%s",
                        keyword, str(data["error"])[:150])
            return [], data["error"]
        jobs = data.get("jobs") or []
        log.info("抓取完成 site=boss kw=%s jobs=%d", keyword, len(jobs))
        return jobs, None
    log.error("未知站点: %s", site)
    return [], "未知站点: %s" % site


def scan(args, **kwargs):
    """抓取岗位 → 打分 → 入库 → 返回高分岗位。

    参数：keywords(可选，覆盖配置)、min_score(可选)、max_jobs(可选)、sites(可选)。
    """
    run_id = None
    started = time.time()
    try:
        cfg = load_config()
        prof = load_profile()
        keywords = args.get("keywords") or cfg.get("keywords") or []
        if not keywords:
            log.warning("扫描中止：没有配置关键词")
            return json.dumps({
                "error": "没有配置关键词",
                "hint": "设置 plugins.entries.job-radar.settings.keywords，"
                        "或改插件目录下的 profile.yaml",
            }, ensure_ascii=False)

        min_score = int(args.get("min_score", cfg["min_score"]))
        limit = int(args.get("max_jobs", cfg["max_jobs_per_run"]))
        sites = args.get("sites") or cfg.get("sites") or ["zhaopin"]
        gap = int(cfg.get("request_gap_seconds", 12))
        log.info("扫描开始 sites=%s keywords=%s limit=%d min_score=%d gap=%ds",
                 sites, keywords, limit, min_score, gap)
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
        log.info("扫描完成 耗时=%.1fs 抓到=%d 新增=%d 命中=%d 错误=%d",
                 time.time() - started, seen, new_count, len(results), len(errors))
        return json.dumps({
            "fetched": seen,
            "new": new_count,
            "matched": len(results),
            "min_score": min_score,
            "errors": errors,
            "jobs": results[:10],
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("扫描异常 耗时=%.1fs", time.time() - started)
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
        jobs = storage.jobs_since(days=1, min_score=min_score)
        path = report.build_daily(jobs, storage.recent_runs(3), min_score)
        log.info("日报生成 jobs=%d path=%s", len(jobs), path)
        return json.dumps({
            "report_path": str(path),
            "count": len(jobs),
            "message": "日报已生成",
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("生成日报失败")
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
    """生成待推送的消息序列（≤50 字/条，URL 除外）。

    only_new=true（默认）→ 只给**还没推过**的岗位生成消息，
    并在生成后标记为已推送 —— 这样同一个岗位不会重复推。
    `pushed_at` 存在 jobs 表里，跟用户自己标记的 status 分开。
    """
    try:
        from . import push as push_mod
        cfg = load_config()
        min_score = int(args.get("min_score", cfg["min_score"]))
        max_jobs = int(args.get("max_jobs", 3))
        only_new = bool(args.get("only_new", True))
        days = int(args.get("days", 1))
        if only_new:
            jobs = storage.unpushed_jobs(days=days, min_score=min_score, limit=50)
        else:
            jobs = storage.all_jobs(limit=50, min_score=min_score)
        msgs = push_mod.build_push(jobs, min_score=min_score, max_jobs=max_jobs)
        # 标记已推送 —— 放在生成之后，投递由 cron 负责
        pushed = []
        if only_new:
            picked = [j for j in jobs if (j.get("score") or 0) >= min_score][:max_jobs]
            pushed = [j.get("job_id") for j in picked if j.get("job_id")]
            storage.mark_pushed(pushed)
        log.info("推送内容生成 jobs=%d msgs=%d only_new=%s 已标记=%d",
                 len(jobs), len(msgs), only_new, len(pushed))
        return json.dumps({
            "count": len(msgs),
            "messages": msgs,
            "job_ids": pushed,
            "note": "按顺序逐条发送；每条已≤50字（URL 除外）",
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("生成推送失败")
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
        log.info("登录态体检完成 cookie数=%d 结论=%s",
                 len(cookies), result["summary"]["verdict"])
        return json.dumps({
            "sites": result["sites"],
            "summary": result["summary"],
            "report": login_check.format_report(result),
            "cookie_count": len(cookies),
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("登录态体检失败")
        return json.dumps({"error": "登录态体检失败: %s" % e}, ensure_ascii=False)


def resume_optimize(args, **kwargs):
    """针对某个岗位做简历匹配优化（四步流程）。

    **不投递** —— 只生成草稿。save=True 才存进档案。
    """
    try:
        from . import resume_builder, resume_store, resume_template
        job_id = args.get("job_id", "")
        template_id = args.get("template_id") or "classic"
        want_save = bool(args.get("save", False))
        if not job_id:
            return json.dumps({"error": "需要 job_id"}, ensure_ascii=False)

        job = storage.get_job(job_id)
        if not job:
            return json.dumps({"error": "找不到岗位 %s" % job_id}, ensure_ascii=False)
        # JD 只在详情页 —— 没有就按需抓一次
        if not (job.get("description") or "").strip():
            site = job.get("source") or "zhaopin"
            log.info("岗位 %s 没有 JD，按需抓详情页", job_id)
            detail = bbclient.fetch_detail(site, job_id)
            if "error" in detail:
                return json.dumps({
                    "error": "抓不到该岗位的 JD",
                    "detail": str(detail["error"])[:150],
                    "hint": "详情页抓取失败，换个岗位或稍后重试",
                }, ensure_ascii=False)
            job = dict(job)
            job.update({k: v for k, v in detail.items() if v})
            storage.upsert(job, {"score": job.get("score", 0),
                                  "reasons": job.get("reasons") or [],
                                  "missing": job.get("missing") or []})

        prof = load_profile()
        if not (prof.get("experience_text") or "").strip():
            return json.dumps({
                "error": "还没有填真实经历",
                "hint": "设置页 → 用户简历 → 填「真实经历」，"
                        "没有它就无法生成简历（也不该编造）",
            }, ensure_ascii=False)

        out = resume_builder.optimize_resume(job, prof, template_id)
        sections = resume_builder.build_sections(out["resume"])
        ctx = {"title": "%s - 简历" % (prof.get("identity") or {}).get("name", ""),
               "identity": out["resume"]["identity"],
               "sections": sections}
        html_preview = resume_template.render_html(
            template_id, dict(ctx, show_basis=True))
        html_final = resume_template.render_html(
            template_id, dict(ctx, show_basis=False))

        saved = None
        if want_save:
            saved = resume_store.save_resume(
                job, out["matched"], html_final, template_id=template_id)
            log.info("简历已存档 id=%s pdf=%s", saved["resume_id"], saved["pdf"])

        log.info("简历优化完成 job=%s 命中=%d 缺口=%d 模板=%s 保存=%s",
                 job_id, len(out["matched"]["covered"]),
                 len(out["matched"]["gaps"]), template_id, bool(saved))

        return json.dumps({
            "job_id": job_id,
            "job_title": job.get("title"),
            "template_id": template_id,
            "requirements": {
                "skills": [{"name": s["name"], "hits": s["hits"],
                            "you_have": s["user_has"]}
                           for s in out["requirements"]["skills"][:12]],
                "degree": out["requirements"]["degree"],
                "min_years": out["requirements"]["min_years"],
                "keywords": out["requirements"]["keywords"][:10],
            },
            "matched_bullets": [
                {"text": c["text"], "basis": c["basis"], "skills": c["matched"]}
                for c in out["matched"]["covered"]],
            "gaps": out["matched"]["gaps"],
            "strengths": out["matched"]["strengths"],
            "html_preview": html_preview,
            "html": html_final,
            "saved": saved,
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("简历优化失败")
        return json.dumps({"error": "简历优化失败: %s" % e}, ensure_ascii=False)


def resume_list(args, **kwargs):
    """简历档案列表（可带某岗位的匹配分排序）。"""
    try:
        from . import resume_store
        limit = int(args.get("limit", 20))
        job_id = args.get("with_score_for") or ""
        items = resume_store.list_resumes(limit=limit)

        if job_id:
            job = storage.get_job(job_id)
            if not job:
                return json.dumps({"error": "找不到岗位 %s" % job_id},
                                  ensure_ascii=False)
            for it in items:
                it["match_score"] = resume_store.resume_matches(job, it)
            items.sort(key=lambda x: -x.get("match_score", 0))
            return json.dumps({"job_id": job_id, "resumes": items},
                              ensure_ascii=False)

        return json.dumps({"resumes": items}, ensure_ascii=False)
    except Exception as e:
        log.exception("读取简历档案失败")
        return json.dumps({"error": "读取简历档案失败: %s" % e}, ensure_ascii=False)

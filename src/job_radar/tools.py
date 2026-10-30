"""job-radar 工具实现。

四个工具：scan（抓取打分）、daily（生成日报）、list（列岗位池）、mark（标记状态）。
所有 handler 返回 JSON 字符串，捕获所有异常，不向外抛。
"""

import json
import os
import time
from datetime import datetime

try:
    from . import bbclient, storage
    from .config import load_config, load_profile
    from .matcher import score_job
except ImportError:          # 脱离包单独导入时（单测 / 独立脚本）
    import bbclient, storage
    from config import load_config, load_profile
    from matcher import score_job

try:
    from .logging_setup import get_logger
except ImportError:          # 脱离包单独导入时（单测）
    from logging_setup import get_logger

try:
    from . import city_codes
    from . import boss_city_codes
except ImportError:          # 脱离包单独导入时（单测）
    import city_codes
    import boss_city_codes

log = get_logger()

# 各站的字段 → 统一词表的映射
FIELD_MAP = {
    "zhaopin": {
        "title": "title", "company": "company", "salary": "salary",
        "area": "area", "experience": "experience", "degree": "degree",
        "tags": "tags", "url": "url", "job_id": "job_id",
        "description": "description",
    },
    # BOSS 的 adapter（社区版 / 本地版）字段名**不完全一样**：
    #   - 原始 API 名：name / brandName / salaryDesc / cityName / jobId
    #   - 统一词表名：title / company / salary / area / job_id
    # 两套都列上 —— **不管 adapter 返哪套都能正确归一**。
    #
    # 社区版只返统一名，本地版两套都返 —— 这里两套都认，最稳。
    # **顺序有意义** —— `_normalize` 按插入顺序取，**后面的覆盖前面的**。
    # 所以**统一词表名放后面**（优先），原始 API 名放前面（兜底）。
    #
    # 本地 adapter 两套都返；社区 adapter 只返统一名。
    # 不管返哪套，最后落到同一个统一字段上。
    "boss": {
        # ── 原始 API 名（兜底）──
        "name": "title", "brandName": "company",
        "salaryDesc": "salary",
        # **cityName 只给「城市」** —— BOSS 的 area 是「城市·区县·商圈」，
        # 直接把 cityName 映射成 area 会**把区县信息冲掉**。
        "cityName": "city",
        "jobExperience": "experience", "jobDegree": "degree",
        "skills": "tags", "jobId": "job_id",
        # **securityId** —— BOSS 详情页要用它（不是 job_id）。
        # 不存的话抓不到 JD → 简历优化只能靠标题猜要求。
        "securityId": "security_id",
        # ── 统一词表名（优先，覆盖上面的）──
        "title": "title", "company": "company", "salary": "salary",
        "area": "area", "experience": "experience", "degree": "degree",
        "tags": "tags", "url": "url", "job_id": "job_id",
        "description": "description",
    },
}


def _write_config(patch):
    """把配置写回 Hermes config.yaml（走 CLI，不手写 YAML）。

    ## 为什么走 CLI

    手改 config.yaml 容易缩进错位 —— 写坏一个缩进，
    整个 `plugins.entries.job-radar` 节点就废了。
    CLI 会自己建嵌套块、保证缩进正确。

    ## 参数

    `patch` —— `{"directions": ["电商运营"], ...}`（只写这几个键）

    ## 失败怎么办

    **不抛异常** —— 保存方向失败不该让整次评估挂掉。
    记日志，返回 False，调用方自己决定要不要报错。
    """
    import subprocess
    try:
        local = os.environ.get("LOCALAPPDATA", "")
        home = os.path.join(local, "hermes", "hermes-agent")
        # **CLI 在 .hermes/bin 下**
        cli = os.path.join(home, ".hermes", "bin",
                           "hermes.exe" if os.name == "nt" else "hermes")
        if not os.path.exists(cli):
            cli = os.path.join(home, ".hermes", "bin", "hermes")
        if not os.path.exists(cli):
            log.warning("找不到 hermes CLI，跳过写配置")
            return False
        base = "plugins.entries.job-radar.settings."
        for key, val in (patch or {}).items():
            if isinstance(val, (list, tuple)):
                arg = ",".join(str(v) for v in val)
            elif isinstance(val, bool):
                arg = "true" if val else "false"
            else:
                arg = str(val)
            cmd = [cli, "config", "set", base + key, arg]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=60, cwd=home)
            if proc.returncode != 0:
                log.warning("写配置 %s 失败: %s", key,
                            (proc.stderr or proc.stdout or "").strip())
                return False
        return True
    except Exception as exc:
        log.warning("写配置失败: %s", exc)
        return False


def _classify_direction(job):
    """岗位 → 方向名（电商运营 / 建筑施工管理 / AI产品开发…）。

    ## 为什么用规则而不是 Agent

    - **可预测** —— 同一个岗位永远同一个方向
    - **可测试** —— 有单测
    - **不烧 token** —— 抓几千条岗位不能每条都问 LLM

    Agent 只在**评估用户经历 → 定可选方向**那一步用。

    ## 失败也不致命

    分不出来就返回 "其它" —— 岗位照样入库、照样打分。
    """
    try:
        try:
            from . import direction_catalog
        except ImportError:      # 脱离包单独导入时（单测）
            import direction_catalog
        text = " ".join(str(job.get(k) or "") for k in
                        ("title", "description", "jd_text", "company"))
        return direction_catalog.classify(text)
    except Exception:
        return "其它"


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


def _fetch_site(site, keyword, cfg, city_code=None):
    """抓一个站一个关键词。返回 (jobs, error)。

    city_code: 智联的城市码（jl）。**不传就用配置里的**。
    """
    city = city_code if city_code is not None else cfg.get("city")
    if site == "zhaopin":
        data = bbclient.run_site("zhaopin/search", keyword,
                                 "--city", str(city))
        if "error" in data:
            log.warning("抓取失败 site=zhaopin kw=%s err=%s",
                        keyword, str(data["error"])[:150])
            return [], data["error"]
        jobs = data.get("jobs") or []
        log.info("抓取完成 site=zhaopin kw=%s jobs=%d", keyword, len(jobs))
        return jobs, None
    if site == "boss":
        # **BOSS 必须先有页面上下文** ——
        # 它的 joblist API 要靠页面里的 anti-content token，
        # 没有 zhipin 页面就 `Daemon request timed out`（实测过）。
        #
        # `city` 这里传的是 **BOSS 的 9 位城市码**（101040100=重庆），
        # **不是智联的 jl 码**（551）—— 两个码表完全不是一个体系。
        boss_city = city_code or cfg.get("boss_city") or "101040100"
        ready = bbclient.ensure_boss_context(city_code=boss_city)
        if not ready.get("ok"):
            log.warning("BOSS 页面没打开 site=boss err=%s", ready.get("detail"))
            return [], "BOSS 页面没打开：%s" % ready.get("detail")

        data = bbclient.run_site("boss/search", keyword,
                                 "--city", str(boss_city))
        if "error" in data:
            log.warning("抓取失败 site=boss kw=%s err=%s",
                        keyword, str(data["error"])[:150])
            return [], data["error"]
        jobs = data.get("jobs") or []
        log.info("抓取完成 site=boss kw=%s city=%s jobs=%d",
                 keyword, boss_city, len(jobs))
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

        # **结构化经历** —— 用来给「方向匹配」加分（干过的职位名）。
        # **提前取一次**，别在循环里反复查库。
        try:
            experiences = storage.list_experiences()
        except Exception:
            experiences = []

        # **先用当前画像重算所有老岗位的分数** ——
        #
        # 改了画像（方向/技能/城市）之后，**没被抓到的老岗位**分数还是旧的。
        # 实测踩到：方向从「web 前端」改成「跨境电商运营」后，
        # 杭州的 web 前端老岗位还留着 78 分，比新抓的运营岗（76）还高
        # → **老岗位全挤在前面**。
        #
        # `upsert()` 只在被重新抓到时更新分数，所以这里要单独重算一遍。
        try:
            rescored = storage.rescore_all(prof, experiences=experiences)
            if rescored:
                log.info("按新画像重算了 %d 条老岗位的分数", rescored)
        except Exception as exc:
            log.warning("重算老岗位分数失败（不影响本次抓取）: %s", exc)

        # **多个城市**（可选）——
        # 只有 `cfg["city"]`（单值）时行为跟以前一样。
        #
        # 为什么要逐个城市抓：智联的 `--city` **只认一个城市码**，
        # 传逗号分隔（"551,763"）会**静默退化成全国** —— 实测过，
        # 返回的是北京/保定/上海，根本没有限定城市。
        #
        # `cfg["cities"]` 存的是**城市名**（用户在设置页选的），
        # 这里翻译成智联码 —— 用户不该看到「南宁 = 3150」这种天书。
        city_list = []
        try:
            city_list = city_codes.cities_to_codes(cfg.get("cities") or [])
        except Exception:
            city_list = []
        city_codes_list = city_list
        if not city_codes_list:
            city_codes_list = [str(cfg.get("city") or "").strip() or "489"]

        # **每个站用自己那套城市码** ——
        # 智联是 3~4 位 jl 码（重庆=551），BOSS 是 9 位 city 码（重庆=101040100）。
        # **混用会静默抓到别的城市** —— 所以这里分开翻译。
        try:
            boss_city_codes_list = boss_city_codes.cities_to_codes(
                cfg.get("cities") or [])
        except Exception:
            boss_city_codes_list = []
        if not boss_city_codes_list:
            boss_city_codes_list = [str(cfg.get("boss_city") or "").strip()
                                    or "101040100"]

        for site in sites:
            # 选这个站该用的码表
            if site == "boss":
                site_city_codes = boss_city_codes_list
            else:
                site_city_codes = city_codes_list
            for city_code in site_city_codes:
                for kw in keywords:
                    if seen >= limit:
                        break
                    jobs, err = _fetch_site(site, kw, cfg, city_code)
                    if err:
                        errors.append("%s/%s/%s: %s" % (site, city_code, kw, err))
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
                        scored = score_job(job, prof, experiences=experiences)
                        job["score"] = scored["score"]
                        # **分类到方向** —— 电商运营 / 建筑施工管理 / AI产品开发…
                        #
                        # 用户诉求：「电商运营（速卖通、ozon、虾皮等国际电商
                        # 平台相关的运营工作归为一类）、建筑施工管理等方向
                        # 归为一类、AI产品开发等方向归为一类」
                        #
                        # → **推荐单位是「方向」**，不是标题字面。
                        # → 每天推**单个方向**里评分最高的 5 条。
                        job["direction"] = _classify_direction(job)
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
        try:
            from . import report
        except ImportError:          # 脱离包单独导入时（单测）
            import report
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


def directions(args, **kwargs):
    """**方向评估** —— Agent 用它确定「用户可选方向」。

    ## 两种用法

    **① 评估（不带 directions 参数）**

    返回：经历摘要 + 候选方向表 + 评估提示。
    Agent 读完自己判断该投哪几个方向。

    **② 保存（带 directions 参数）**

    把选好的方向写进配置，之后**每天只推这些方向**。

    ## 为什么需要它

    用户诉求：「由 Agent 评估用户经历，确定用户可选方向、
    根据可选方向每天只推荐单个方向中评分最高的 5 条」。

    ## 为什么岗位分类不用 Agent

    一次抓几百上千条岗位 → 每条问一次 LLM = 慢 + 烧钱 + 不一致。
    → 岗位分类走**规则**（`direction_catalog`），Agent 只评**方向**。
    """
    try:
        try:
            from . import direction_evaluate, storage as _st
        except ImportError:
            import direction_evaluate
            import storage as _st

        experiences = _st.list_experiences()
        # **岗位池里的方向分布** —— 有机会投的方向
        rows = []
        try:
            with _st._conn() as conn:
                rows = conn.execute(
                    """SELECT direction, COUNT(*) AS c, MAX(score) AS top
                       FROM jobs WHERE direction IS NOT NULL
                         AND direction != ''
                       GROUP BY direction""").fetchall()
        except Exception:
            rows = []
        job_dirs = [{"direction": r["direction"], "score": r["top"],
                     "count": r["c"]} for r in rows]

        candidates = direction_evaluate.candidate_directions(
            experiences, job_dirs)

        # ── ② 保存模式 ──
        if "directions" in args and args.get("directions") is not None:
            chosen = [str(d).strip() for d in (args.get("directions") or [])
                      if str(d).strip()]
            # **去重 + 保序**
            seen = set()
            uniq = []
            for d in chosen:
                if d not in seen:
                    seen.add(d)
                    uniq.append(d)
            cfg = load_config()
            cfg["directions"] = uniq
            _write_config(cfg)
            return json.dumps({
                "ok": True,
                "saved": uniq,
                "count": len(uniq),
                "note": "已保存可选方向；之后每天只推这些方向里评分最高的 %s 条"
                        % (args.get("max_per_direction") or 5),
            }, ensure_ascii=False)

        # ── ① 评估模式 ──
        summary = direction_evaluate.summarize_experiences(experiences)
        hint = direction_evaluate.evaluate_hint(summary, candidates)
        cur = (load_config() or {}).get("directions") or []
        return json.dumps({
            "experiences": summary,
            "candidates": candidates,
            "current_directions": cur,
            "hint": hint,
            "note": "读 hint 评估后，用 directions 参数调一次保存",
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("方向评估失败")
        return json.dumps({"error": "方向评估失败: %s" % e}, ensure_ascii=False)


def push(args, **kwargs):
    """生成待推送的消息序列（≤50 字/条，URL 除外）。

    only_new=true（默认）→ 只给**还没推过**的岗位生成消息，
    并在生成后标记为已推送 —— 这样同一个岗位不会重复推。
    `pushed_at` 存在 jobs 表里，跟用户自己标记的 status 分开。
    """
    try:
        try:
            from . import push as push_mod
        except ImportError:          # 脱离包单独导入时（单测）
            import push as push_mod
        cfg = load_config()
        min_score = int(args.get("min_score", cfg["min_score"]))
        max_jobs = int(args.get("max_jobs", 3))
        only_new = bool(args.get("only_new", True))
        days = int(args.get("days", 1))
        if only_new:
            jobs = storage.unpushed_jobs(days=days, min_score=min_score, limit=50)
        else:
            jobs = storage.all_jobs(limit=50, min_score=min_score)

        # ── **单个方向**里评分最高的 N 条 ──
        #
        # 用户诉求：「根据可选方向每天只推荐**单个方向**中评分最高的 5 条」
        #
        # ## 为什么不是所有方向混着推
        #
        # 一天 30 条（多方向混推）→ 用户看不过来 → 等于没推。
        # 一天 5 条（一个方向）→ 看得完，且**明天换另一个方向**。
        #
        # `max_jobs` 现在是**每个方向**的条数（默认 5）。
        #
        # **用户选定的方向**（`cfg["directions"]`）优先 ——
        # 用户说投啥就投啥，别推他没选的方向。
        # **用户选定的方向** —— profile 优先，settings 兜底
        #
        # 方向存**画像**（跟经历、方向权重一起）→ 这里读 profile。
        # settings 里也允许写（方便老配置）。
        cfg_directions = []
        try:
            prof_now = load_profile()
            cfg_directions = list(prof_now.get("directions") or [])
        except Exception:
            pass
        if not cfg_directions:
            cfg_directions = list(cfg.get("directions") or [])
        last = storage.last_direction_pushed()
        picked = push_mod.build_daily_push(
            jobs, max_per_direction=max_jobs, directions=cfg_directions,
            last_direction=last.get("direction") or "")

        msgs = picked["messages"]
        direction = picked["direction"]
        top_jobs = picked["jobs"]

        # 标记已推送 —— 放在生成之后，投递由 cron 负责
        pushed = []
        if only_new:
            pushed = [j.get("job_id") for j in top_jobs if j.get("job_id")]
            storage.mark_pushed(pushed)
        # **记下这次推了哪个方向** —— 下次轮换到别的方向
        if direction:
            storage.mark_direction_pushed(
                direction, max((j.get("score") or 0) for j in top_jobs)
                if top_jobs else 0)
        log.info("推送内容生成 jobs=%d msgs=%d only_new=%s 方向=%s 已标记=%d",
                 len(jobs), len(msgs), only_new, direction, len(pushed))
        return json.dumps({
            "count": len(msgs),
            "messages": msgs,
            "job_ids": pushed,
            "direction": direction,
            "ranking": picked.get("ranking") or [],
            "note": "按顺序逐条发送；每条已≤50字（URL 除外）",
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("生成推送失败")
        return json.dumps({"error": "生成推送失败: %s" % e}, ensure_ascii=False)


def login_status(args, **kwargs):
    """体检各站登录态，返回状态与剩余天数。"""
    try:
        try:
            from . import browser_cookies, login_check
        except ImportError:          # 脱离包单独导入时（单测）
            import browser_cookies, login_check
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
        try:
            from . import resume_builder, resume_store, resume_template
        except ImportError:          # 脱离包单独导入时（单测）
            import resume_builder, resume_store, resume_template
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
        # **结构化经历优先** —— 它有公司/职位/起止，
        # 是简历「工作经历」章节真正需要的东西；自由文本只是兜底。
        experiences = storage.list_experiences()
        has_text = bool((prof.get("experience_text") or "").strip())
        if not experiences and not has_text:
            return json.dumps({
                "error": "还没有填经历",
                "hint": "设置页 → 用户简历 → 填「结构化经历」"
                        "（推荐，有公司/职位/起止）或「真实经历」文本。"
                        "没有它无法生成简历（也不该编造）",
            }, ensure_ascii=False)

        out = resume_builder.optimize_resume(job, prof, template_id,
                                             experiences=experiences)
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
        try:
            from . import resume_store
        except ImportError:          # 脱离包单独导入时（单测）
            import resume_store
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

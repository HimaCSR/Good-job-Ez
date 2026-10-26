"""岗位匹配度打分。纯函数，无 IO —— 这是唯一需要认真写单测的部分。"""

import re


def score_job(job: dict, profile: dict) -> dict:
    """返回 {"score": 0-100, "reasons": [...], "missing": [...]}"""
    score = 0
    reasons, missing = [], []

    title = (job.get("title") or job.get("name") or "").lower()

    # 1) 职位名关键词命中（30 分）
    # 命中判定要宽松：岗位名常写「web前端」「前端开发工程师」，
    # 关键词在标题里出现即算命中；找不到再退到 tags + 公司描述里找。
    haystack = " ".join([
        title,
        str(job.get("tags") or ""),
        str(job.get("raw") or ""),
    ]).lower()
    hits = [k for k in profile.get("title_keywords", []) if k.lower() in haystack]
    if hits:
        score += min(30, 10 * len(hits))
        reasons.append("职位名命中: " + "、".join(hits))
    else:
        missing.append("职位名未命中期望岗位词")

    # 2) 技能覆盖（30 分）
    jd = " ".join([
        title,
        str(job.get("tags") or ""),
        str(job.get("description") or ""),
        str(job.get("raw") or ""),
    ]).lower()
    skills = profile.get("skills") or []
    if skills:
        covered = [s for s in skills if s.lower() in jd]
        score += int(30 * len(covered) / len(skills))
        if covered:
            reasons.append("技能覆盖 %d/%d: %s" % (
                len(covered), len(skills), "、".join(covered)))
        miss_sk = [s for s in skills if s.lower() not in jd]
        if miss_sk:
            missing.append("技能未提及: " + "、".join(miss_sk))

    # 3) 城市（15 分）
    want_city = profile.get("city", "")
    job_city = (job.get("area") or job.get("city") or "")
    if want_city and want_city in job_city:
        score += 15
        reasons.append("城市符合: " + job_city)
    elif want_city:
        missing.append("城市不符（期望 %s，实际 %s）" % (want_city, job_city or "未知"))

    # 4) 经验（15 分）
    score += _experience_score(job.get("experience") or "",
                               profile.get("min_experience_years", 0))

    # 5) 薪资（10 分）
    score += _salary_score(job.get("salary") or "", profile.get("min_salary", 0))

    return {"score": max(0, min(100, score)), "reasons": reasons, "missing": missing}


def _experience_score(text: str, min_years: int) -> int:
    """经验匹配。min_years=0 表示不要求，给满分 15。"""
    if not min_years:
        return 15
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*年", text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(\d+)\s*年以上", text)
        if m:
            lo, hi = int(m.group(1)), int(m.group(1))
        elif "经验不限" in text or "应届" in text or "在校" in text:
            return 0
        else:
            return 5
    if lo >= min_years:
        return 15
    if hi >= min_years:
        return 10
    return 5


def _salary_score(text: str, min_k: int) -> int:
    """薪资匹配。min_k=0 表示不要求，给满分 10。"""
    if not min_k:
        return 10
    if not text or "*" in text:
        return 5          # 薪资被遮罩，给中性分
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*[kK]", text)
    if m:
        hi = float(m.group(2))
    else:
        m = re.search(r"(\d+)\s*[kK]", text)
        if not m:
            return 5
        hi = float(m.group(1))
    if hi >= min_k:
        return 10
    if hi >= min_k * 0.8:
        return 6
    return 2

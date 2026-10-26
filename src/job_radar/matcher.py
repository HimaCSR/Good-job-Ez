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

    # 3) 城市（20 分）—— 多选，命中任一即算符合
    want_cities = _wanted_cities(profile)
    job_city = (job.get("area") or job.get("city") or "")
    if want_cities:
        matched = [c for c in want_cities if c and c in job_city]
        if matched:
            score += 20
            reasons.append("城市符合 %s: %s" % ("、".join(matched), job_city))
        else:
            missing.append("城市不符（期望 %s，实际 %s）" % (
                "、".join(want_cities), job_city or "未知"))

    # 4) 薪资（20 分）
    score += _salary_score(job.get("salary") or "", profile.get("min_salary", 0))

    # 经验项：2026-10-26 起暂不纳入评分（字段保留，等评分模型稳定再启用）

    return {"score": max(0, min(100, score)), "reasons": reasons, "missing": missing}


def _wanted_cities(profile: dict) -> list:
    """期望城市列表。兼容旧的单城市字段 city。"""
    cities = profile.get("cities") or []
    if isinstance(cities, str):
        cities = [cities] if cities else []
    if not cities:
        legacy = profile.get("city") or ""
        cities = [legacy] if legacy else []
    return [str(c).strip() for c in cities if str(c).strip()]


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
    """薪资匹配。min_k=0 表示不要求，给满分 20。"""
    if not min_k:
        return 20
    if not text or "*" in text:
        return 10         # 薪资被遮罩，给中性分
    # 支持四种写法：「15-25K」「1.5-1.8万」「5-6千」「8000-12000」
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*([kK万千])", text)
    if m:
        hi = float(m.group(2))
        unit = m.group(3)
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*([kK万千])", text)
        if m:
            hi = float(m.group(1))
            unit = m.group(2)
        else:
            # 「8000-12000」这种不带单位的，按元/月的常见写法当成 K
            m = re.search(r"(\d{4,})\s*-\s*(\d{4,})", text)
            if m:
                hi = float(m.group(2)) / 1000.0
                unit = "K"
            else:
                return 10         # 完全读不懂薪资，给中性分
    if unit == "万":
        hi *= 10                # 1.8万 = 18K
    elif unit == "千":
        hi /= 10                # 6千 = 0.6K
    if hi >= min_k:
        return 20
    if hi >= min_k * 0.8:
        return 12      # 略低于期望，但接近
    if hi >= min_k * 0.5:
        return 6       # 明显低于期望
    return 0           # 完全够不着

"""岗位池存储。位置：plugin_data_dir('job-radar')/jobs.db"""

import json
import uuid
import os
import sqlite3
from datetime import datetime

try:
    from plugins.plugin_storage import plugin_data_dir
except ImportError:                                    # 脱离 Hermes 单跑时
    def plugin_data_dir(name):
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes",
                             "plugin-data")
        d = os.path.join(base, name)
        os.makedirs(d, exist_ok=True)
        return d

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  source TEXT, title TEXT, company TEXT, salary TEXT, city TEXT,
  experience TEXT, degree TEXT, skills TEXT, url TEXT,
  description TEXT,
  score INTEGER, reasons TEXT, missing TEXT,
  first_seen TEXT, last_seen TEXT,
  status TEXT DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS resumes (
  resume_id TEXT PRIMARY KEY,
  title TEXT,
  file_path TEXT,
  format TEXT,          -- pdf / docx / html
  tags TEXT,            -- JSON 数组
  source TEXT,          -- applied / manual / optimized
  job_id TEXT,          -- 投递时的岗位
  created TEXT,
  updated TEXT
);

CREATE TABLE IF NOT EXISTS resume_templates (
  template_id TEXT PRIMARY KEY,
  name TEXT,
  description TEXT,
  format TEXT,          -- builtin / docx / pdf / image
  source_path TEXT,
  preview_path TEXT,
  builtin INTEGER DEFAULT 0,
  created TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started TEXT, finished TEXT,
  fetched INTEGER, matched INTEGER, new_jobs INTEGER, error TEXT
);
"""


def _conn():
    d = plugin_data_dir("job-radar")
    os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(os.path.join(d, "jobs.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert(job, scored):
    """插入或更新一条岗位。返回 True 表示是新岗位。"""
    now = datetime.now().isoformat(timespec="seconds")
    jid = job.get("job_id") or job.get("url") or \
        "%s|%s|%s" % (job.get("title", ""), job.get("company", ""), job.get("area", ""))
    with _conn() as conn:
        cur = conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (jid,))
        is_new = cur.fetchone() is None
        conn.execute(
            """INSERT OR REPLACE INTO jobs
               (job_id, source, title, company, salary, city, experience, degree,
                skills, url, description, score, reasons, missing,
                first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, job.get("source", ""), job.get("title", ""),
             job.get("company", ""), job.get("salary", ""),
             job.get("area") or job.get("city", ""),
             job.get("experience", ""), job.get("degree", ""),
             json.dumps(job.get("tags") or [], ensure_ascii=False),
             job.get("url", ""), job.get("description", ""),
             scored["score"],
             json.dumps(scored.get("reasons") or [], ensure_ascii=False),
             json.dumps(scored.get("missing") or [], ensure_ascii=False),
             now, now))
    return is_new


def jobs_since(days=1, min_score=0):
    """最近 days 天首次出现的岗位，按分数倒序。"""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM jobs
               WHERE first_seen >= datetime('now', ?)
                 AND score >= ?
               ORDER BY score DESC, first_seen DESC""",
            ("-%d days" % days, min_score)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d.get("skills") or "[]")
        d["reasons"] = json.loads(d.get("reasons") or "[]")
        d["missing"] = json.loads(d.get("missing") or "[]")
        d.setdefault("area", d.get("city", ""))
        out.append(d)
    return out


def all_jobs(limit=50, min_score=0, status=None):
    with _conn() as conn:
        sql = "SELECT * FROM jobs WHERE score >= ?"
        args = [min_score]
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY score DESC, last_seen DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d.get("skills") or "[]")
        d["reasons"] = json.loads(d.get("reasons") or "[]")
        d["missing"] = json.loads(d.get("missing") or "[]")
        d.setdefault("area", d.get("city", ""))
        out.append(d)
    return out


def get_job(job_id):
    with _conn() as conn:
        r = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["tags"] = json.loads(d.get("skills") or "[]")
    d["reasons"] = json.loads(d.get("reasons") or "[]")
    d["missing"] = json.loads(d.get("missing") or "[]")
    d.setdefault("area", d.get("city", ""))
    return d


def set_status(job_id, status):
    with _conn() as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
    return get_job(job_id)


def start_run():
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started, fetched, matched, new_jobs) VALUES (?,0,0,0)",
            (datetime.now().isoformat(timespec="seconds"),))
        return cur.lastrowid


def finish_run(run_id, fetched, matched, new_jobs, error=""):
    with _conn() as conn:
        conn.execute(
            """UPDATE runs SET finished=?, fetched=?, matched=?, new_jobs=?, error=?
               WHERE id=?""",
            (datetime.now().isoformat(timespec="seconds"),
             fetched, matched, new_jobs, error, run_id))


def recent_runs(limit=5):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── 简历与模板 ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def upsert_resume(resume: dict) -> None:
    """存一份简历档案（投递成功或手动上传）。"""
    with _conn() as c:
        c.execute(
            """INSERT INTO resumes
               (resume_id, title, file_path, format, tags, source, job_id, created, updated)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(resume_id) DO UPDATE SET
                 title=excluded.title, file_path=excluded.file_path,
                 format=excluded.format, tags=excluded.tags,
                 source=excluded.source, job_id=excluded.job_id,
                 updated=excluded.updated""",
            (
                resume.get("resume_id") or uuid.uuid4().hex[:12],
                resume.get("title") or "未命名简历",
                resume.get("file_path") or "",
                resume.get("format") or "pdf",
                json.dumps(resume.get("tags") or [], ensure_ascii=False),
                resume.get("source") or "manual",
                resume.get("job_id") or "",
                resume.get("created") or _now(),
                _now(),
            ))


def list_resumes(limit: int = 50) -> List[dict]:
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM resumes ORDER BY updated DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = _load_list(d.get("tags"))
        out.append(d)
    return out


def upsert_template(tpl: dict) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO resume_templates
               (template_id, name, description, format, source_path, preview_path, builtin, created)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(template_id) DO UPDATE SET
                 name=excluded.name, description=excluded.description,
                 format=excluded.format, source_path=excluded.source_path,
                 preview_path=excluded.preview_path,
                 builtin=excluded.builtin""",
            (
                tpl.get("template_id") or uuid.uuid4().hex[:12],
                tpl.get("name") or "未命名模板",
                tpl.get("description") or "",
                tpl.get("format") or "builtin",
                tpl.get("source_path") or "",
                tpl.get("preview_path") or "",
                1 if tpl.get("builtin") else 0,
                tpl.get("created") or _now(),
            ))


def list_templates() -> List[dict]:
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM resume_templates ORDER BY builtin DESC, created ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_template(template_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM resume_templates WHERE template_id=?", (template_id,))
    return cur.rowcount > 0


def _load_list(raw) -> List:
    """把 JSON 字符串列还原成列表；不是 JSON 就当单元素。"""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else [v]
    except (ValueError, TypeError):
        return [str(raw)]

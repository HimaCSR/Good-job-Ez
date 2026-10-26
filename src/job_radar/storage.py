"""岗位池存储。位置：plugin_data_dir('job-radar')/jobs.db"""

import json
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

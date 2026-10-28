"""岗位池存储。位置：plugin_data_dir('job-radar')/jobs.db"""

import json
import uuid
import os
import sqlite3
from datetime import datetime
from typing import List

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

-- 结构化经历（公司 / 职位 / 起止 / 分条描述）
--
-- **必须落库**，不能放内存 ——
-- 放内存的话：进程重启全丢，而且多条记录会共用同一个 id，
-- 新增一条就把旧的挤掉（前端新增时传的 id 是空字符串）。
CREATE TABLE IF NOT EXISTS experiences (
  id TEXT PRIMARY KEY,
  company TEXT,
  title TEXT,
  start TEXT,
  end TEXT,
  bullets TEXT,          -- JSON 数组
  tags TEXT,             -- JSON 数组
  created TEXT
);

-- 投递三道门：一次性确认令牌
CREATE TABLE IF NOT EXISTS apply_tokens (
  token TEXT PRIMARY KEY,
  job_id TEXT,
  site TEXT,
  resume_id TEXT,
  issued_at TEXT,
  expires_at TEXT,
  used_at TEXT
);

-- 投递记录（过了三道门 + 动作层有回应就记一条）
CREATE TABLE IF NOT EXISTS apply_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site TEXT,
  job_id TEXT,
  resume_id TEXT,
  ok INTEGER,
  detail TEXT,
  applied_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_apply_records_site_time
  ON apply_records(site, applied_at);
"""


def _ensure_columns(conn):
    """给老库补列（schema 改了但库是旧的）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "pushed_at" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN pushed_at TEXT")


class _Conn(sqlite3.Connection):
    """`with` 退出时自动关连接。

    **为什么需要**：`sqlite3.Connection` 自己的 `__exit__` 只提交/回滚事务，
    **不关连接**。所以 `with _conn() as conn:` 写完了，连接还开着 ——
    24 个调用点，每个都漏一个句柄。抓取跑一轮就是几十个，
    跑久了文件句柄吃紧（Windows 上尤其明显）。

    用子类覆盖 `__exit__`：先提交/回滚，再关。
    """
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def _conn():
    d = plugin_data_dir("job-radar")
    os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(os.path.join(d, "jobs.db"), factory=_Conn)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_columns(conn)
    return conn


def rescore_all(profile, experiences=None, score_fn=None):
    """用**当前画像**重算所有岗位的分数。

    ## 为什么需要

    改了画像（方向、技能、城市）之后，**没被抓到的老岗位**分数还是旧的。

    实测踩到：把方向从「web 前端」改成「跨境电商运营」后，
    岗位池里杭州的 web 前端老岗位还留着 **78 分**，
    比新抓的运营岗（76 分）还高 → **老岗位全挤在前面**。

    `upsert()` 只在岗位**被重新抓到**时更新分数 ——
    没抓到的就一直是旧值。

    ## 怎么做

    读出所有岗位 → 用新画像重新打分 → 写回。
    **不动 first_seen / pushed_at**（那是投递状态，跟分数无关）。

    score_fn: 打分函数（默认用 matcher.score_job）。
    """
    if score_fn is None:
        try:
            from .matcher import score_job as score_fn
        except ImportError:      # 脱离包单独导入时（单测）
            from matcher import score_job as score_fn

    jobs = all_jobs(limit=100000, min_score=0)
    if not jobs:
        return 0

    now = datetime.now().isoformat(timespec="seconds")
    changed = 0
    with _conn() as conn:
        for j in jobs:
            scored = score_fn(j, profile, experiences=experiences)
            conn.execute(
                "UPDATE jobs SET score=?, reasons=?, missing=? WHERE job_id=?",
                (scored["score"],
                 json.dumps(scored.get("reasons") or [], ensure_ascii=False),
                 json.dumps(scored.get("missing") or [], ensure_ascii=False),
                 j.get("job_id")),
            )
            changed += 1
    return changed


def upsert(job, scored):
    """插入或更新一条岗位。返回 True 表示是新岗位。"""
    now = datetime.now().isoformat(timespec="seconds")
    jid = job.get("job_id") or job.get("url") or \
        "%s|%s|%s" % (job.get("title", ""), job.get("company", ""), job.get("area", ""))
    with _conn() as conn:
        cur = conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (jid,))
        is_new = cur.fetchone() is None
        # **不能用 INSERT OR REPLACE** —— 它先删旧行再插入，
        # first_seen 和 pushed_at 会被重置：
        #   · first_seen 每次抓取都变 → 「今日新增」永远等于全部
        #   · pushed_at 每次清空 → 同一个岗位被反复推
        # 用 ON CONFLICT DO UPDATE：只更新变化的字段，保留首次出现时间和推送标记。
        conn.execute(
            """INSERT INTO jobs
               (job_id, source, title, company, salary, city, experience, degree,
                skills, url, description, score, reasons, missing,
                first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET
                 source=excluded.source, title=excluded.title,
                 company=excluded.company, salary=excluded.salary,
                 city=excluded.city, experience=excluded.experience,
                 degree=excluded.degree, skills=excluded.skills,
                 url=excluded.url, description=excluded.description,
                 score=excluded.score, reasons=excluded.reasons,
                 missing=excluded.missing, last_seen=excluded.last_seen""",
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


def unpushed_jobs(days=1, min_score=0, limit=50):
    """还没推过的岗位（pushed_at 为空），按分数倒序。

    这是「只推新岗位」的判据 —— 不能靠 status 字段，
    那是用户自己标记 interested/applied/ignored 用的。
    """
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM jobs
               WHERE pushed_at IS NULL
                 AND first_seen >= datetime('now', ?)
                 AND score >= ?
               ORDER BY score DESC, first_seen DESC
               LIMIT ?""",
            ("-%d days" % days, min_score, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d.get("skills") or "[]")
        d["reasons"] = json.loads(d.get("reasons") or "[]")
        d["missing"] = json.loads(d.get("missing") or "[]")
        d.setdefault("area", d.get("city", ""))
        out.append(d)
    return out


def mark_pushed(job_ids):
    """标记这些岗位已推送。返回标记了几条。"""
    if not job_ids:
        return 0
    now = _now()
    with _conn() as conn:
        conn.executemany(
            "UPDATE jobs SET pushed_at = ? WHERE job_id = ?",
            [(now, jid) for jid in job_ids])
    return len(job_ids)


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


def list_experiences() -> List[dict]:
    """全部结构化经历（按创建时间倒序 —— 新的在前）。"""
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM experiences ORDER BY created DESC, rowid DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["bullets"] = _load_list(d.get("bullets"))
        d["tags"] = _load_list(d.get("tags"))
        out.append(d)
    return out


def upsert_experience(exp: dict) -> dict:
    """新增或更新一条经历。

    ## id 怎么来的

    **空 id 一律生成新的** —— 前端新增时传的是 `id: ''`（空字符串），
    而 `dict.setdefault("id", ...)` **在 key 存在时不会覆盖**，
    于是空字符串被当成真 id 用：
    `[e for e in list if e["id"] != exp["id"]]` 把所有空 id 的都删掉
    → **新增一条就把旧的挤掉**。

    所以这里**不用 setdefault**，而是显式判断「id 为空就生成」。

    生成方式用 uuid 而不是 `exp-N` —— 序号在删除后会撞
    （删掉一条，长度不变 → 下次生成的 id 和之前一样）。
    """
    import json

    exp = dict(exp or {})
    exp_id = str(exp.get("id") or "").strip()
    if not exp_id:
        exp_id = "exp-" + uuid.uuid4().hex[:12]

    bullets = exp.get("bullets") or []
    tags = exp.get("tags") or []

    with _conn() as c:
        # 有这个 id → 更新；没有 → 插入。
        # **不能**用 ON CONFLICT DO UPDATE 吗？可以，但要先判断存在，
        # 因为 created 要保持原值（更新不该改创建时间）。
        row = c.execute(
            "SELECT created FROM experiences WHERE id = ?", (exp_id,)
        ).fetchone()
        created = row[0] if row else (exp.get("created") or _now())
        c.execute(
            """INSERT INTO experiences
               (id, company, title, start, end, bullets, tags, created)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 company=excluded.company, title=excluded.title,
                 start=excluded.start, end=excluded.end,
                 bullets=excluded.bullets, tags=excluded.tags""",
            (
                exp_id,
                exp.get("company") or "",
                exp.get("title") or "",
                exp.get("start") or "",
                exp.get("end") or "",
                json.dumps(list(bullets), ensure_ascii=False),
                json.dumps(list(tags), ensure_ascii=False),
                created,
            ),
        )
    out = dict(exp)
    out["id"] = exp_id
    out["bullets"] = list(bullets)
    out["tags"] = list(tags)
    out["created"] = created
    return out


def delete_experience(exp_id: str) -> bool:
    """删一条经历。返回是否真的删掉了。"""
    with _conn() as c:
        cur = c.execute("DELETE FROM experiences WHERE id = ?", (exp_id,))
        return cur.rowcount > 0


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


# ── 投递三道门：令牌与投递记录 ─────────────────────────────────────────────
#
# 令牌落库而不是放内存 —— 内存版重启进程就丢，
# 而且 cron 脚本和网关 API 是两个进程，内存不共享。

def insert_apply_token(token, job_id, site, resume_id, issued_at, expires_at):
    """落一条令牌。"""
    with _conn() as c:
        c.execute(
            """INSERT INTO apply_tokens
               (token, job_id, site, resume_id, issued_at, expires_at, used_at)
               VALUES (?,?,?,?,?,?,NULL)""",
            (token, job_id or "", site or "", resume_id or "",
             issued_at, expires_at))


def get_apply_token(token):
    """取一条令牌。取不到返回 None。"""
    with _conn() as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM apply_tokens WHERE token = ?",
                      (token or "",)).fetchone()
    return dict(r) if r else None


def delete_apply_token(token):
    """删掉一条令牌（过期清理用）。"""
    with _conn() as c:
        c.execute("DELETE FROM apply_tokens WHERE token = ?", (token or "",))


def mark_apply_token_used(token):
    """把令牌标记成已用 —— 一次性。"""
    with _conn() as c:
        c.execute("UPDATE apply_tokens SET used_at = ? WHERE token = ?",
                  (_now(), token or ""))


def count_applies(site, day):
    """某站某天**尝试**投递了几次。

    **失败的也算** —— 每条记录代表「三道门都过了、动作层已经动手」。
    如果只算成功的，动作层一坏（比如 adapter 没写好）就变成无限重试，
    每日上限形同虚设 —— 上限是防失控的，不是防失败的。

    `ok` 列只用来审计（成功还是失败），不参与计数。
    """
    with _conn() as c:
        r = c.execute(
            """SELECT COUNT(*) FROM apply_records
               WHERE site = ? AND applied_at LIKE ?""",
            (site or "", str(day) + "%")).fetchone()
    return int(r[0]) if r else 0


def insert_apply_record(site, job_id, resume_id, ok, detail, applied_at):
    """记一条投递。"""
    with _conn() as c:
        c.execute(
            """INSERT INTO apply_records
               (site, job_id, resume_id, ok, detail, applied_at)
               VALUES (?,?,?,?,?,?)""",
            (site or "", job_id or "", resume_id or "",
             1 if ok else 0, detail or "", applied_at))


def list_apply_records(limit=20):
    """最近的投递记录。"""
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM apply_records ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    return [dict(r) for r in rows]


def update_resume_after_apply(resume_id, tags=None, source=None, job_id=None):
    """投递后更新简历档案：打标签、标记来源、关联岗位。"""
    with _conn() as c:
        if tags is not None:
            c.execute("UPDATE resumes SET tags = ? WHERE resume_id = ?",
                      (json.dumps(tags, ensure_ascii=False), resume_id))
        if source is not None:
            c.execute("UPDATE resumes SET source = ? WHERE resume_id = ?",
                      (source, resume_id))
        if job_id is not None:
            c.execute("UPDATE resumes SET job_id = ? WHERE resume_id = ?",
                      (job_id, resume_id))
        c.execute("UPDATE resumes SET updated = ? WHERE resume_id = ?",
                  (_now(), resume_id))

"""直接调 `/resume/optimize` 端点 —— 看真实返回。

用法：python src/job_radar/scripts/probe_resume_optimize.py
"""
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
sys.path.insert(0, PLUGIN_DIR)
os.environ["JOB_RADAR_HOT_RELOAD"] = "1"


def _load_api():
    if "job_radar" not in sys.modules:
        pkg = types.ModuleType("job_radar")
        pkg.__path__ = [PLUGIN_DIR]
        pkg.__package__ = "job_radar"
        sys.modules["job_radar"] = pkg
    path = os.path.join(PLUGIN_DIR, "dashboard", "plugin_api.py")
    spec = importlib.util.spec_from_file_location("plugin_api_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


api = _load_api()
storage = api._sibling("storage")

jobs = storage.all_jobs(limit=5, min_score=0)
print("=" * 62)
print("/resume/optimize 端点 —— 真实调用")
print("=" * 62)
print()

for job in jobs[:3]:
    jid = job.get("job_id")
    print("--- 岗位:", job.get("title"), "|", job.get("company"), "---")
    r = api.resume_optimize({"job_id": jid, "template_id": "classic", "save": False})
    print("  ok:", r.get("ok"), "| error:", r.get("error"), "| hint:", (r.get("hint") or "")[:60])
    if not r.get("ok"):
        print()
        continue
    reqs = r.get("requirements") or []
    matched = r.get("matched") or {}
    covered = matched.get("covered") or []
    gaps = matched.get("gaps") or []
    print("  JD 要求:", len(reqs), "条 →", [x.get("name") if isinstance(x, dict) else x for x in reqs][:6])
    print("  命中经历:", len(covered), "条")
    for m in covered[:5]:
        if isinstance(m, dict):
            print("    -", m.get("title") or m.get("text") or m.get("name"),
                  "| 依据:", m.get("basis") or m.get("basis_text"))
    print("  缺口:", len(gaps), "→", [x.get("name") if isinstance(x, dict) else x for x in gaps][:6])
    html = r.get("html") or ""
    print("  html 长度:", len(html))
    # 看「工作经历」章节有没有内容
    import re
    for sec in (r.get("resume") or {}).get("sections") or []:
        if sec.get("title") == "工作经历":
            entries = sec.get("entries") or []
            print("  工作经历章节:", len(entries), "条")
            for e in entries[:3]:
                print("    -", e.get("title"), "|", e.get("meta"), "|", e.get("subtitle"))
            bullets = [b for e in entries for b in (e.get("bullets") or [])]
            print("  bullet 总数:", len(bullets))
            for b in bullets[:3]:
                print("    •", (b.get("text") or "")[:60], "| 依据:", b.get("basis"))
    print()

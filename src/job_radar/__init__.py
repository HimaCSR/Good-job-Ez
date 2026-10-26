"""job-radar — 招聘岗位雷达。

定时抓取招聘网站岗位，按个人画像算匹配度，生成日报并推送到聊天窗口。
只读：不投递简历，不联系招聘方。
"""

import logging
import os

from . import config, schemas, tools

logger = logging.getLogger(__name__)


def register(ctx):
    config.set_context(ctx)

    ctx.register_tool(name="job_radar_scan", toolset="job_radar",
                      schema=schemas.SCAN, handler=tools.scan)
    ctx.register_tool(name="job_radar_daily", toolset="job_radar",
                      schema=schemas.DAILY, handler=tools.daily)
    ctx.register_tool(name="job_radar_list", toolset="job_radar",
                      schema=schemas.LIST, handler=tools.list_jobs)
    ctx.register_tool(name="job_radar_mark", toolset="job_radar",
                      schema=schemas.MARK, handler=tools.mark)
    ctx.register_tool(name="job_radar_push", toolset="job_radar",
                      schema=schemas.PUSH, handler=tools.push)
    ctx.register_tool(name="job_radar_login", toolset="job_radar",
                      schema=schemas.LOGIN, handler=tools.login_status)
    ctx.register_tool(name="job_radar_resume_optimize", toolset="job_radar",
                      schema=schemas.RESUME_OPTIMIZE, handler=tools.resume_optimize)
    ctx.register_tool(name="job_radar_resume_list", toolset="job_radar",
                      schema=schemas.RESUME_LIST, handler=tools.resume_list)

    # 插件自带的技能文件，agent 可以 skill_view("job-radar:usage") 载入
    skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
    if os.path.isdir(skills_dir):
        for child in sorted(os.listdir(skills_dir)):
            skill_md = os.path.join(skills_dir, child, "SKILL.md")
            if os.path.isdir(os.path.join(skills_dir, child)) and os.path.exists(skill_md):
                ctx.register_skill(child, skill_md)

    logger.info("job-radar 已注册：8 个工具")

"""工具 schemas —— 这是 LLM 看到的部分。描述写具体，模型才知道什么时候调。"""

SCAN = {
    "name": "job_radar_scan",
    "description": (
        "抓取招聘网站岗位，按用户的个人画像算匹配度，存入本地岗位池。"
        "返回高分岗位列表（职位名、公司、薪资、地点、匹配分、匹配理由、缺口、链接）。"
        "只读操作，不会投递简历、不会联系招聘方。"
        "关键词没配好时返回 error 并提示去改 settings.keywords。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选，覆盖配置里的搜索关键词列表，如 ['前端', 'three.js']",
            },
            "min_score": {
                "type": "integer",
                "description": "可选，匹配度分数线 0-100，默认取配置值 60",
            },
            "max_jobs": {
                "type": "integer",
                "description": "可选，本次最多抓多少条，默认 40",
            },
            "sites": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选，要抓的站：zhaopin(智联) / boss(BOSS直聘)，默认 ['zhaopin']",
            },
        },
    },
}

DAILY = {
    "name": "job_radar_daily",
    "description": (
        "生成今日岗位日报（Markdown 文件），包含高分岗位的匹配度、理由、缺口和链接。"
        "返回日报文件的绝对路径。内容适合放进聊天里给用户看，或作为附件发送。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "min_score": {
                "type": "integer",
                "description": "可选，日报收录的分数线 0-100，默认取配置值",
            },
        },
    },
}

LIST = {
    "name": "job_radar_list",
    "description": (
        "列出本地岗位池里已抓到的岗位（按匹配度倒序）。"
        "用于回顾历史岗位、查某个岗位的分数和状态。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "可选，返回条数，默认 20"},
            "min_score": {"type": "integer", "description": "可选，只看这个分以上的"},
            "status": {
                "type": "string",
                "description": "可选，只看某个状态：new / interested / applied / ignored",
            },
        },
    },
}

MARK = {
    "name": "job_radar_mark",
    "description": (
        "给岗位打标签：interested(感兴趣) / applied(已投递) / ignored(忽略) / new(重置)。"
        "用于在日报里标记用户的选择，方便后续筛选。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "岗位 ID"},
            "status": {
                "type": "string",
                "description": "new / interested / applied / ignored",
            },
        },
        "required": ["job_id", "status"],
    },
}


PUSH = {
    "name": "job_radar_push",
    "description": (
        "从岗位池生成待推送的消息序列。每条消息都不超过 50 字（URL 除外，URL 不能拆），"
        "适合直接依次发送到聊天窗口。返回 messages 数组，按顺序发即可。"
        "只读操作，不会投递简历。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "min_score": {
                "type": "integer",
                "description": "可选，只推送这个分以上的岗位，默认取配置值",
            },
            "max_jobs": {
                "type": "integer",
                "description": "可选，最多推送几条岗位，默认 3",
            },
            "only_new": {
                "type": "boolean",
                "description": "可选，只推今天新出现的岗位，默认 false",
            },
        },
    },
}


LOGIN = {
    "name": "job_radar_login",
    "description": (
        "体检各招聘网站的登录态是否还有效，并算出凭证还能用多少天。"
        "返回每个站的状态（正常 / 风控 token 即将过期 / 需要重新登录）和具体提示。"
        "什么时候用：抓取报 code 37 / 401 / 薪资变成 **-**元 时；"
        "或者用户问“我要不要重新登录”。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sites": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选，要检查的站：zhipin / zhaopin / gxrc，默认全查",
            },
        },
    },
}


RESUME_OPTIMIZE = {
    "name": "job_radar_resume_optimize",
    "description": (
        "针对某个岗位做简历匹配优化：读该岗 JD → 挑出核心要求 → "
        "对照用户真实经历 → 按模板生成一份定向简历。"
        "每条 bullet 都带「← 依据：经历第 N 条」的来源标注，**不编造经历**。"
        "结果先给预览（draft），用户确认后才存成正式简历。"
        "这是只读/生成操作，不会投递任何简历。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "岗位 ID（从 job_radar_list 拿）",
            },
            "template_id": {
                "type": "string",
                "description": (
                    "可选，模板：classic / modern / tech / acad，"
                    "默认 classic。也可以用用户上传转换出来的模板 id。"
                ),
            },
            "save": {
                "type": "boolean",
                "description": (
                    "可选，是否存进简历档案（生成 PDF + 打标签）。"
                    "默认 false —— 先预览，用户认可再存。"
                ),
            },
        },
        "required": ["job_id"],
    },
}


RESUME_LIST = {
    "name": "job_radar_resume_list",
    "description": (
        "列出用户简历档案：投递/优化成功的简历，带标签。"
        "标签是后续岗位简历评分推荐的依据。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "可选，最多返回几条，默认 20",
            },
            "with_score_for": {
                "type": "string",
                "description": (
                    "可选，给一个岗位 ID，顺便算出每份历史简历对该岗位的匹配分，"
                    "按分排序 —— 投递时的「历史简历推荐」用的就是这个。"
                ),
            },
        },
    },
}

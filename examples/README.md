# 配置示例

这个目录放**可以直接抄的配置样例**。真实配置不进仓库。

---

## `config.example.yaml`

Hermes 主配置（`$HERMES_HOME/config.yaml`）里跟本插件相关的部分：

```yaml
plugins:
  enabled:
    - job-radar

  entries:
    job-radar:
      settings:
        # 搜索关键词 —— 出现在岗位名/标签里就加分
        keywords:
          - 前端
          - web前端

        # 智联城市 jl 代码
        city: "653"        # 653=杭州 530=北京 538=上海 489=全国

        # BOSS 城市代码
        boss_city: "101210100"   # 101210100=杭州

        # 日报/推送的入选分数线 0-100
        min_score: 50

        # 单次运行最多抓多少条
        max_jobs_per_run: 30

        # 启用哪些站
        sites:
          - zhaopin       # zhaopin / boss

        # 两次请求之间的基准间隔（秒）—— 别调太小，会被风控
        request_gap_seconds: 12

        # 每天自动抓取几次
        rounds_per_day: 4

        # 每次最多推几条岗位到 QQ
        push_max: 3

        # 只推当天新岗位，不重复推旧的
        push_new_only: true

        # 抓取失败时也通知我
        notify_on_failure: true

        # 只在这个时段内抓取
        active_hours: "09:00 - 22:00"
```

---

## `profile.example.yaml`

个人画像。**真实的那份在** `<plugin-data>/job-radar/profile.yaml`，
不在仓库里（`.gitignore` 挡着）。

```yaml
# 格式是 JSON（去掉注释后的纯 JSON）。改的时候注意：
#   - 字符串用双引号
#   - 数组用 ["a", "b"]
#   - 最后一项后面不要加逗号
{
  # 期望的岗位方向关键词，出现在岗位名里就加分（每个 +10，最多 30）
  "title_keywords": ["前端", "web", "three.js"],

  # 你的技能，JD 里提到就加分（按覆盖率折算 30 分）
  "skills": ["vue", "typescript", "three.js", "webgl"],

  # 期望城市（多选），命中任一即算符合城市项
  "cities": ["杭州"],

  # 期望最低月薪（K），0 表示不要求
  "min_salary": 15,

  # 期望最少年限（当前不计入评分，字段保留）
  "min_experience_years": 3,

  # 出现这些词就跳过（外包、劳务派遣…）
  "exclude_companies": ["外包", "劳务派遣"],

  # 身份信息 —— 不参与打分，只填简历抬头
  "identity": {
    "name": "张三",
    "phone": "138-0000-0000",
    "email": "user@example.com",
    "education": "本科"
  },

  # 真实经历原文 —— 简历生成的唯一依据，绝不编造
  "experience_text": ""
}
```

---

## 城市代码速查

### 智联招聘（`city`）

| 代码 | 城市 |
| --- | --- |
| 653 | 杭州 |
| 530 | 北京 |
| 538 | 上海 |
| 489 | 全国 |
| 538 | 上海 |
| 765 | 深圳 |
| 763 | 广州 |

### BOSS 直聘（`boss_city`）

| 代码 | 城市 |
| --- | --- |
| 101210100 | 杭州 |
| 101280100 | 杭州（旧版，**别用这个**） |
| 101010100 | 北京 |
| 101020100 | 上海 |
| 101280600 | 深圳 |
| 101280100 | 广州 |

> BOSS 的城市码容易记混，**以插件配置里的为准**。
> 抓出来的地点不对，先核对这一项。

---

## 日报推送内容长什么样

每条消息 = 一份岗位，只含岗位名 · 城市 + 链接：

```
web前端开发工程师 · 杭州拱墅
https://www.zhaopin.com/jobdetail/CC3985.htm
```

**不带分数、不带命中理由。** 完整明细在日报 Markdown 文件里：

```markdown
# 岗位日报 · 2026-10-26

高分岗位（≥50 分）：16 条 ｜ 今日新增：16 条

## 今日推荐

### 1. web前端开发工程师
- **公司** 某人力资源有限公司 · **薪资** 15-25K · **地点** 杭州 拱墅
- **匹配度 73** — 职位名命中: 前端、web；技能覆盖 5/8: vue、typescript
- **缺口** 技能未提及: three.js、webgl
- **链接** https://www.zhaopin.com/jobdetail/CC3985.htm
```

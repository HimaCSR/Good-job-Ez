/**
 * 好岗好找 Good-job-Ez —— Hermes 桌面端设置页。
 *
 * 位置：$HERMES_HOME/plugins/job-radar/desktop/plugin.js
 * 纯 ESM，未编译 —— UI 用 jsx() 调用，不能写 JSX 语法。
 * 只允许 import '@hermes/plugin-sdk'、'react'、'react/jsx-runtime'。
 *
 * 后端：dashboard/plugin_api.py（挂在 /api/plugins/job-radar/）
 * 调法：ctx.rest('/config')、ctx.rest('/profile', { method:'POST', body:{...} })
 *
 * 配色：全部用 --ui-* 主题变量，跟着 Hermes 皮肤走，绝不硬编码颜色。
 */

import {
  Button, Input, Textarea, Badge,
  GlyphSpinner, EmptyState, ErrorState,
  ROUTES_AREA, SIDEBAR_NAV_AREA,
  cn, host, useQuery, useMutation, useQueryClient,
} from '@hermes/plugin-sdk'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'
import * as React from 'react'

const ID = 'job-radar'

// ── 小工具 ──────────────────────────────────────────────────────────────────

function Field({ label, hint, children, wide }) {
  return jsxs('div', {
    className: cn('flex flex-col gap-1.5', wide && 'col-span-2'),
    children: [
      jsx('label', {
        className: 'text-xs font-medium text-(--ui-text-secondary)',
        children: label,
      }),
      children,
      hint && jsx('span', {
        className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
        children: hint,
      }),
    ],
  })
}

function Panel({ title, hint, actions, children, bodyClass }) {
  return jsxs('div', {
    className: 'flex flex-col overflow-hidden rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-card)',
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2 border-b border-(--ui-stroke-secondary) px-4 py-2.5',
        children: [
          jsx('h2', { className: 'text-sm font-semibold', children: title }),
          hint && jsx('span', {
            className: 'text-xs text-(--ui-text-tertiary)',
            children: hint,
          }),
          jsx('div', { className: 'ml-auto flex items-center gap-2', children: actions }),
        ],
      }),
      jsx('div', {
        className: cn('p-4', bodyClass),
        children,
      }),
    ],
  })
}

// 标签编辑器：可增删的 chips
function ChipEditor({ value, onChange, placeholder, addLabel }) {
  const list = Array.isArray(value) ? value : []
  return jsxs('div', {
    className: 'flex flex-wrap items-center gap-1.5',
    children: [
      ...list.map((item, i) => jsxs('span', {
        key: item + '-' + i,
        className: 'inline-flex items-center gap-1 rounded-full border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-2.5 py-0.5 text-xs',
        children: [
          jsx('span', { children: item }),
          jsx('button', {
            type: 'button',
            className: 'text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
            onClick: () => onChange(list.filter((_, j) => j !== i)),
            children: '×',
          }),
        ],
      })),
      jsx('button', {
        type: 'button',
        className: 'rounded-full border border-dashed border-(--ui-stroke-secondary) px-2.5 py-0.5 text-xs text-(--ui-text-tertiary) hover:border-(--ui-accent) hover:text-(--ui-accent)',
        onClick: () => {
          const v = globalThis.prompt(addLabel || '输入内容')
          if (v && v.trim()) onChange([...list, v.trim()])
        },
        children: '＋ ' + (addLabel || '添加'),
      }),
    ],
  })
}

// ── 数据层 ──────────────────────────────────────────────────────────────────

function useConfig(ctx) {
  return useQuery({
    queryKey: ['job-radar', 'config'],
    queryFn: async () => ctx.rest('/config'),
  })
}

function useJobs(ctx, minScore) {
  return useQuery({
    queryKey: ['job-radar', 'jobs', minScore],
    queryFn: async () => ctx.rest('/jobs?limit=30&min_score=' + (minScore || 0)),
    refetchInterval: 30000,
  })
}

function useRuns(ctx) {
  return useQuery({
    queryKey: ['job-radar', 'runs'],
    queryFn: async () => ctx.rest('/runs'),
    refetchInterval: 60000,
  })
}

function useLogin(ctx) {
  return useQuery({
    queryKey: ['job-radar', 'login'],
    queryFn: async () => ctx.rest('/login'),
    staleTime: 60000,
  })
}

// ── 个人信息 ────────────────────────────────────────────────────────────────

function ProfileView({ ctx, cfg, onSaved }) {
  const qc = useQueryClient()
  const profile = (cfg && cfg.profile) || {}

  const save = useMutation({
    mutationFn: async (next) => ctx.rest('/profile', { method: 'POST', body: next }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job-radar', 'config'] })
      host.notify({ kind: 'success', message: '个人信息已保存' })
      onSaved && onSaved()
    },
    onError: (e) => host.notify({ kind: 'error', message: String(e && e.message || e) }),
  })

  const [local, setLocal] = React.useState(profile)
  React.useEffect(() => { setLocal(profile) }, [profile])

  const set = (k, v) => setLocal((s) => ({ ...s, [k]: v }))
  const identity = local.identity || {}
  const setIdentity = (k, v) => set((s) => ({ ...s, identity: { ...(s.identity || {}), [k]: v } }))

  if (!profile || !Object.keys(profile).length) {
    return jsx(ErrorState, { message: '读不到个人画像' })
  }

  return jsxs(Fragment, {
    children: [
      jsx(Panel, {
        title: '身份信息',
        hint: '仅用于简历生成表单',
        children: jsxs('div', {
          className: 'grid grid-cols-2 gap-4',
          children: [
            jsx(Field, {
              label: '姓名',
              children: jsx(Input, {
                value: identity.name || '',
                onChange: (e) => setIdentity('name', e.target.value),
                placeholder: '张三',
              }),
            }),
            jsx(Field, {
              label: '电话',
              children: jsx(Input, {
                value: identity.phone || '',
                onChange: (e) => setIdentity('phone', e.target.value),
                placeholder: '138****0000',
              }),
            }),
            jsx(Field, {
              label: '邮箱',
              children: jsx(Input, {
                value: identity.email || '',
                onChange: (e) => setIdentity('email', e.target.value),
                placeholder: 'you@example.com',
              }),
            }),
            jsx(Field, {
              label: '最高学历',
              children: jsx('select', {
                className: 'h-8 w-full rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-input) px-2 text-sm outline-none focus:border-(--ui-accent)',
                value: identity.degree || '本科',
                onChange: (e) => setIdentity('degree', e.target.value),
                children: ['大专', '本科', '硕士', '博士'].map((deg) =>
                  jsx('option', { key: deg, value: deg, children: deg })),
              }),
            }),
            jsx(Field, {
              label: '毕业院校',
              children: jsx(Input, {
                value: identity.school || '',
                onChange: (e) => setIdentity('school', e.target.value),
                placeholder: 'XX 大学',
              }),
            }),
            jsx(Field, {
              label: '专业',
              children: jsx(Input, {
                value: identity.major || '',
                onChange: (e) => setIdentity('major', e.target.value),
                placeholder: '软件工程',
              }),
            }),
          ],
        }),
      }),
      jsx('div', { className: 'h-3' }),
      jsx(Panel, {
        title: '期望条件',
        hint: '参与打分',
        children: jsxs('div', {
          className: 'grid grid-cols-2 gap-4',
          children: [
            jsx(Field, {
              label: '期望城市（可多选）',
              wide: true,
              hint: '岗位地点命中任一城市即算符合城市项（20 分）',
              children: jsx(ChipEditor, {
                value: local.cities || [],
                onChange: (v) => set('cities', v),
                addLabel: '添加城市',
              }),
            }),
            jsx(Field, {
              label: '岗位方向',
              wide: true,
              hint: '出现在岗位名里就加分，每命中一个 +10，最多 30 分',
              children: jsx(ChipEditor, {
                value: local.title_keywords || [],
                onChange: (v) => set('title_keywords', v),
                addLabel: '添加方向',
              }),
            }),
            jsx(Field, {
              label: '我的技能',
              wide: true,
              hint: '按覆盖率折算 30 分。只写你真会的。',
              children: jsx(ChipEditor, {
                value: local.skills || [],
                onChange: (v) => set('skills', v),
                addLabel: '添加技能',
              }),
            }),
            jsx(Field, {
              label: '期望最低月薪（K）',
              hint: '0 表示不要求',
              children: jsx(Input, {
                type: 'number',
                value: String(local.min_salary ?? 0),
                onChange: (e) => set('min_salary', Number(e.target.value) || 0),
              }),
            }),
            jsx(Field, {
              label: '期望最少年限',
              hint: '⚠ 暂不纳入评分，字段先留着',
              children: jsx(Input, {
                type: 'number',
                disabled: true,
                value: String(local.min_experience_years ?? 0),
                onChange: () => {},
              }),
            }),
          ],
        }),
      }),
      jsx('div', { className: 'h-3' }),
      jsx(Panel, {
        title: '真实经历',
        hint: '简历定向优化的唯一原料',
        actions: jsx(Button, {
          size: 'sm',
          variant: 'primary',
          disabled: save.isPending,
          onClick: () => save.mutate(local),
          children: save.isPending ? '保存中…' : '保存',
        }),
        children: jsxs('div', {
          className: 'flex flex-col gap-1.5',
          children: [
            jsx(Textarea, {
              rows: 10,
              value: local.experience_text || '',
              onChange: (e) => set('experience_text', e.target.value),
              placeholder: '按时间倒序写你真做过的事',
            }),
            jsx('span', {
              className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
              children: 'AI 只能重组这里的文字，不会编造没出现过的内容',
            }),
          ],
        }),
      }),
    ],
  })
}

// ── 岗位推荐 ────────────────────────────────────────────────────────────────

function JobCard({ job }) {
  const [open, setOpen] = React.useState(false)
  const score = job.score ?? 0
  const tone = score >= 70 ? 'success' : score >= 50 ? 'warn' : 'muted'
  return jsxs('div', {
    className: 'border-b border-(--ui-stroke-secondary) last:border-b-0',
    children: [
      jsxs('div', {
        className: 'flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-(--ui-row-hover-background)',
        onClick: () => setOpen(!open),
        children: [
          jsx('span', {
            className: cn('mt-1 text-[0.625rem] text-(--ui-text-tertiary) transition-transform',
              open && 'rotate-90'),
            children: '▶',
          }),
          jsxs('div', { className: 'min-w-0 flex-1', children: [
            jsx('div', { className: 'text-sm font-medium', children: job.title || '' }),
            jsx('div', { className: 'mt-0.5 text-xs text-(--ui-text-tertiary)', children: job.company || '' }),
            jsxs('div', {
              className: 'mt-1.5 flex flex-wrap gap-2 text-xs text-(--ui-text-secondary)',
              children: [
                job.salary && jsx('span', { children: '💰 ' + job.salary }),
                job.area && jsx('span', { children: '📍 ' + job.area }),
                job.experience && jsx('span', { children: '💼 ' + job.experience }),
              ],
            }),
          ]}),
          jsx(Badge, {
            variant: tone,
            children: String(score),
          }),
        ],
      }),
      open && jsxs('div', { className: 'flex flex-col gap-1.5 px-4 pb-3', children: [
        jsx('div', {
          className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
          children: (job.reasons || []).join('　'),
        }),
        job.missing && job.missing.length
          ? jsx('div', {
              className: 'text-[0.6875rem] text-(--ui-text-quaternary)',
              children: '缺口：' + job.missing.join('、'),
            })
          : null,
      ]}),
    ],
  })
}

function RecommendView({ ctx, cfg }) {
  const settings = (cfg && cfg.settings) || {}
  const jobsQ = useJobs(ctx, 0)
  const runsQ = useRuns(ctx)
  const jobs = (jobsQ.data && jobsQ.data.jobs) || []
  const runs = (runsQ.data && runsQ.data.runs) || []

  return jsxs(Fragment, {
    children: [
      jsx(Panel, {
        title: '今日候选',
        hint: jobsQ.isLoading ? '加载中…' : ('命中 ' + jobs.length + ' 条'),
        bodyClass: 'p-0',
        children: jobsQ.isLoading
          ? jsx(GlyphSpinner, { className: 'p-6' })
          : jobsQ.isError
            ? jsx(ErrorState, { message: String(jobsQ.error) })
            : jobs.length === 0
              ? jsx(EmptyState, { title: '还没有岗位', description: '跑一次抓取就会出现' })
              : jsxs('div', {}, jobs.map((j, i) => jsx(JobCard, { key: j.job_id || i, job: j }))),
      }),
      jsx('div', { className: 'h-3' }),
      jsx(Panel, {
        title: '最近抓取',
        hint: '共 ' + runs.length + ' 条',
        children: runs.length === 0
          ? jsx(EmptyState, { title: '还没有运行记录' })
          : jsxs('div', { className: 'flex flex-col gap-1 text-xs', children:
              runs.map((r, i) => jsxs('div', {
                key: i,
                className: 'flex gap-3 text-(--ui-text-secondary)',
                children: [
                  jsx('span', { className: 'font-mono', children: r.started_at || '' }),
                  jsx('span', { children: '抓到 ' + (r.fetched ?? 0) }),
                  jsx('span', { children: '命中 ' + (r.matched ?? 0) }),
                  jsx('span', { children: '新增 ' + (r.new_jobs ?? 0) }),
                  r.error ? jsx('span', { className: 'text-(--ui-red)', children: r.error }) : null,
                ],
              })),
            }),
      }),
    ],
  })
}

// ── 平台接入 ────────────────────────────────────────────────────────────────

const SITE_META = {
  zhipin: { label: 'BOSS直聘', color: '#00B4B4', creds: ['zp_at', '__zp_stoken__'] },
  zhaopin: { label: '智联招聘', color: '#E4361E', creds: ['at', 'rt'] },
  huibo: { label: '汇博招聘网', color: '#0A5CA8', creds: [] },
}


/** 插件运行日志。默认不拉 —— 用户点开才请求。 */
function useLogs(ctx, enabled) {
  return useQuery({
    queryKey: ['job-radar', 'logs'],
    queryFn: async () => ctx.rest('/logs?lines=300'),
    enabled: !!enabled,
    staleTime: 5000,
  })
}

function PlatformView({ ctx, cfg }) {
  const loginQ = useLogin(ctx)
  const sites = (loginQ.data && loginQ.data.sites) || []
  const summary = (loginQ.data && loginQ.data.summary) || {}
  const settings = (cfg && cfg.settings) || {}
  const [showLogs, setShowLogs] = React.useState(false)
  const logsQ = useLogs(ctx, showLogs)

  return jsxs(Fragment, {
    children: [
      jsx(Panel, {
        title: '登录态体检',
        hint: summary.verdict || '',
        actions: jsx(Button, {
          size: 'sm',
          onClick: () => loginQ.refetch(),
          children: '重新体检',
        }),
        children: loginQ.isLoading
          ? jsx(GlyphSpinner, { className: 'p-4' })
          : jsx('div', { className: 'flex flex-col gap-2', children:
              sites.map((s, i) => jsxs('div', {
                key: s.site || i,
                className: 'flex items-center gap-3 rounded-md border border-(--ui-stroke-secondary) px-3 py-2',
                children: [
                  jsx('span', {
                    className: cn('text-xs font-semibold',
                      s.status === 'ok' ? 'text-(--ui-green)' :
                      s.status === 'expiring' ? 'text-(--ui-orange)' : 'text-(--ui-text-tertiary)'),
                    children: s.status === 'ok' ? '✓' : s.status === 'expiring' ? '!' : '·',
                  }),
                  jsxs('div', { className: 'min-w-0 flex-1', children: [
                    jsx('div', { className: 'text-sm font-medium', children: s.label }),
                    jsx('div', { className: 'mt-0.5 text-xs text-(--ui-text-tertiary)', children: s.detail }),
                    s.hint ? jsx('div', {
                      className: 'mt-0.5 text-xs text-(--ui-orange)',
                      children: s.hint,
                    }) : null,
                  ]}),
                ],
              })),
            }),
      }),

      // 运行日志 —— 默认收起，点开才拉
      jsx(Panel, {
        title: '运行日志',
        hint: showLogs
          ? (logsQ.data && logsQ.data.lines ? logsQ.data.lines + ' 行' : '')
          : '排查问题时打开',
        actions: jsxs('div', { className: 'flex items-center gap-2', children: [
          showLogs ? jsx(Button, {
            size: 'sm',
            variant: 'ghost',
            onClick: () => logsQ.refetch(),
            children: '刷新',
          }) : null,
          jsx(Button, {
            size: 'sm',
            variant: 'ghost',
            onClick: () => setShowLogs((v) => !v),
            children: showLogs ? '收起' : '查看',
          }),
        ]}),
        children: !showLogs
          ? jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children:
              '日志只记录状态、计数和耗时，不含任何凭证值。' })
          : logsQ.isLoading
            ? jsx(GlyphSpinner, { className: 'p-4' })
            : jsx('div', { className: 'flex flex-col gap-2', children: [
                jsx('pre', {
                  className: 'max-h-80 overflow-auto rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3 text-[0.6875rem] leading-relaxed',
                  children: (logsQ.data && logsQ.data.text) || '（还没有日志）',
                }),
                jsx('div', {
                  className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
                  children: (logsQ.data && logsQ.data.file) || '',
                }),
              ] }),
      }),
    ],
  })
}

// ── 日报 ────────────────────────────────────────────────────────────────────

function ReportView({ ctx }) {
  const q = useQuery({
    queryKey: ['job-radar', 'report'],
    queryFn: async () => ctx.rest('/report'),
    refetchInterval: 60000,
  })
  const md = (q.data && q.data.markdown) || ''

  return jsx(Panel, {
    title: '今日日报',
    hint: q.isLoading ? '加载中…' : 'plugin-data/job-radar/reports/',
    children: q.isLoading
      ? jsx(GlyphSpinner, { className: 'p-4' })
      : q.isError
        ? jsx(ErrorState, { message: String(q.error) })
        : jsx('pre', {
            className: 'max-h-[60vh] overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed',
            children: md || '（今天还没有日报）',
          }),
  })
}

// ── 设置 ────────────────────────────────────────────────────────────────────

function SettingsView({ ctx, cfg }) {
  const qc = useQueryClient()
  const settings = (cfg && cfg.settings) || {}
  const [local, setLocal] = React.useState(settings)
  React.useEffect(() => { setLocal(settings) }, [settings])

  const save = useMutation({
    mutationFn: async (next) => ctx.rest('/settings', { method: 'POST', body: { settings: next } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job-radar', 'config'] })
      host.notify({ kind: 'success', message: '设置已保存' })
    },
    onError: (e) => host.notify({ kind: 'error', message: String(e && e.message || e) }),
  })

  const set = (k, v) => setLocal((s) => ({ ...s, [k]: v }))

  return jsxs(Fragment, {
    children: [
      jsx(Panel, {
        title: '筛选条件',
        hint: '改动立即生效',
        actions: jsx(Button, {
          size: 'sm',
          variant: 'primary',
          disabled: save.isPending,
          onClick: () => save.mutate(local),
          children: save.isPending ? '保存中…' : '保存',
        }),
        children: jsxs('div', {
          className: 'grid grid-cols-2 gap-4',
          children: [
            jsx(Field, {
              label: '搜索关键词',
              wide: true,
              children: jsx(ChipEditor, {
                value: local.keywords || [],
                onChange: (v) => set('keywords', v),
                addLabel: '添加关键词',
              }),
            }),
            jsx(Field, {
              label: '推送分数线',
              hint: '低于这个分不进日报，也不推送',
              children: jsx(Input, {
                type: 'number',
                value: String(local.min_score ?? 50),
                onChange: (e) => set('min_score', Number(e.target.value) || 0),
              }),
            }),
            jsx(Field, {
              label: '单次最多抓取',
              children: jsx(Input, {
                type: 'number',
                value: String(local.max_jobs_per_run ?? 30),
                onChange: (e) => set('max_jobs_per_run', Number(e.target.value) || 0),
              }),
            }),
            jsx(Field, {
              label: '请求间隔（秒）',
              hint: '实际间隔 = 基准 + 0~20 秒随机',
              children: jsx(Input, {
                type: 'number',
                value: String(local.request_gap_seconds ?? 12),
                onChange: (e) => set('request_gap_seconds', Number(e.target.value) || 0),
              }),
            }),
            jsx(Field, {
              label: '每天抓取次数',
              children: jsx(Input, {
                type: 'number',
                value: String(local.rounds_per_day ?? 4),
                onChange: (e) => set('rounds_per_day', Number(e.target.value) || 0),
              }),
            }),
          ],
        }),
      }),
    ],
  })
}

// ── 主视图 ──────────────────────────────────────────────────────────────────

function SettingsPage({ ctx }) {
  const cfgQ = useConfig(ctx)
  const cfg = cfgQ.data

  const tabs = [
    { id: 'profile', label: '个人信息' },
    { id: 'recommend', label: '岗位推荐' },
    { id: 'platform', label: '平台接入' },
    { id: 'report', label: '日报' },
  ]

  if (cfgQ.isLoading) {
    return jsx('div', {
      className: 'flex h-full items-center justify-center',
      children: jsx(GlyphSpinner, {}),
    })
  }
  if (cfgQ.isError) {
    return jsx('div', {
      className: 'flex h-full items-center justify-center p-6',
      children: jsx(ErrorState, { message: String(cfgQ.error) }),
    })
  }

  const [tab, setTab] = React.useState('profile')
  const body = {
    profile: jsx(ProfileView, { ctx, cfg }),
    recommend: jsx(RecommendView, { ctx, cfg }),
    platform: jsx(PlatformView, { ctx, cfg }),
    report: jsx(ReportView, { ctx }),
  }[tab]

  return jsxs('div', {
    className: 'mx-auto flex h-full max-w-4xl flex-col gap-4 overflow-y-auto p-6',
    children: [
      jsxs('div', { className: 'flex items-start gap-3', children: [
        jsxs('div', { children: [
          jsx('h1', { className: 'text-lg font-semibold', children: '好岗好找' }),
          jsx('p', {
            className: 'mt-0.5 text-xs text-(--ui-text-tertiary)',
            children: '定时抓取招聘网站岗位，按个人画像打分，生成日报并推送到 QQ',
          }),
        ]}),
        jsx('div', { className: 'ml-auto' },
          jsx(Segmented, { tabs, active: tab, onChange: setTab })),
      ]}),
      body,
    ],
  })
}

// 自实现的分段控件 —— SDK 只导出 Tabs/TabsList/TabsTrigger，没有 TabsContent，
// 自己渲染内容区更省事，也避免引用未导出的组件。
function Segmented({ tabs, active, onChange }) {
  return jsx('div', {
    className: 'inline-flex gap-1 rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-1',
    children: tabs.map((t) => jsx('button', {
      key: t.id,
      type: 'button',
      onClick: () => onChange(t.id),
      className: cn(
        'rounded-md px-3 py-1 text-xs font-medium transition-colors',
        active === t.id
          ? 'bg-(--ui-bg-card) text-(--ui-text-primary) shadow-sm'
          : 'text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'
      ),
      children: t.label,
    })),
  })
}

// ── 注册 ────────────────────────────────────────────────────────────────────
//
// 三条入口，缺一不可：
//   1. registerSettingsPage —— Settings ▸ Plugins 里的条目（带 5 个子页）
//   2. sidebar.nav        —— 左侧栏一行，直接跳到设置页
//   3. routes             —— /job-radar 路由
//
// panes 那条是「右侧停靠面板」，但它要求 data.dock 且默认会遮挡会话，
// 设置页这种体量不适合停靠 —— 主入口用 Settings ▸ Plugins。

/** 用户简历 —— 上面是模板库，下面是自己的简历档案。 */
function ResumeView({ ctx }) {
  const tplQ = useQuery({
    queryKey: ['job-radar', 'templates'],
    queryFn: async () => ctx.rest('/templates'),
  })
  const resQ = useQuery({
    queryKey: ['job-radar', 'resumes'],
    queryFn: async () => ctx.rest('/resumes'),
  })
  const qc = useQueryClient()
  const [picked, setPicked] = React.useState(['classic', 'modern'])
  const [helpOpen, setHelpOpen] = React.useState(false)

  const templates = (tplQ.data && tplQ.data.templates) || []
  const resumes = (resQ.data && resQ.data.resumes) || []

  const toggle = (id) => setPicked((prev) =>
    prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])

  return jsxs('div', { className: 'flex flex-col gap-4', children: [
    // ── 简历模板 ──
    jsx(Panel, {
      title: '简历模板',
      hint: picked.length ? '已选 ' + picked.length + ' 套' : '未选择',
      actions: jsxs('div', { className: 'flex items-center gap-2', children: [
        jsx('button', {
          type: 'button',
          onClick: () => setHelpOpen((v) => !v),
          className: cn(
            'flex h-6 w-6 items-center justify-center rounded-full border text-xs',
            helpOpen
              ? 'border-(--ui-stroke-strong) bg-(--ui-bg-secondary)'
              : 'border-(--ui-stroke-secondary) hover:bg-(--ui-bg-secondary)'
          ),
          title: '上传模板说明',
          children: '?',
        }),
      ]}),
      children: jsxs('div', { className: 'flex flex-col gap-3', children: [
        helpOpen && jsx('div', {
          className: 'rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3 text-xs leading-relaxed text-(--ui-text-secondary)',
          children: jsxs('div', { children: [
            jsx('b', { children: '上传自己的模板' }),
            jsx('span', { children: '：在模板库右下角点「＋ 上传模板」，选一个 ' }),
            jsx('b', { children: 'Word（.docx）' }),
            jsx('span', { children: '、' }),
            jsx('b', { children: 'PDF' }),
            jsx('span', { children: ' 或 ' }),
            jsx('b', { children: '图片（.png / .jpg）' }),
            jsx('span', { children: '，再点「转换并加入模板库」。' }),
            jsx('br', {}),
            jsx('span', { children: '转换在本机完成，文件不会离开这台电脑。Word 走版式参数抽取，PDF 和图片按视觉还原成「底图 + 文字层」。' }),
          ]}),
        }),
        jsxs('div', { className: 'grid grid-cols-2 gap-3 sm:grid-cols-3', children:
          templates.map((tpl) => jsx(TemplateCard, {
            key: tpl.template_id,
            tpl,
            active: picked.includes(tpl.template_id),
            onToggle: () => toggle(tpl.template_id),
          })).concat([
            jsx('button', {
              key: '__upload',
              type: 'button',
              className: 'flex min-h-40 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-(--ui-stroke-strong) p-4 text-xs text-(--ui-text-tertiary) transition-colors hover:border-(--ui-stroke-focus) hover:text-(--ui-text-secondary)',
              children: [
                jsx('span', { className: 'text-lg', children: '＋' }),
                jsx('span', { children: '上传模板' }),
              ],
            }),
          ])
        }),
      ]}),
    }),

    // ── 用户简历 ──
    jsx(Panel, {
      title: '用户简历',
      hint: '投递成功的简历会自动存进这里并打标签',
      children: resumes.length
        ? jsxs('div', { className: 'flex flex-col divide-y divide-(--ui-stroke-secondary)', children:
            resumes.map((r) => jsx(ResumeRow, { key: r.resume_id, resume: r }))
          })
        : jsx(EmptyState, {
            title: '还没有简历档案',
            description: '在「岗位推荐」里对某个岗位做「简历匹配优化」并投递成功后，简历会自动存到这里。',
          }),
    }),
  ]})
}

/** 模板卡 —— 内置模板画一个迷你预览缩略图，上传模板用文件名。 */
function TemplateCard({ tpl, active, onToggle }) {
  const builtin = tpl.builtin || tpl.format === 'builtin'
  return jsxs('button', {
    type: 'button',
    onClick: onToggle,
    className: cn(
      'flex flex-col overflow-hidden rounded-lg border text-left transition-colors',
      active
        ? 'border-(--ui-stroke-focus) ring-1 ring-(--ui-stroke-focus)'
        : 'border-(--ui-stroke-secondary) hover:border-(--ui-stroke-strong)'
    ),
    children: [
      jsx('div', {
        className: cn(
          'relative flex h-24 items-center justify-center bg-(--ui-bg-secondary)',
          !active && 'opacity-60'
        ),
        children: [
          builtin
            ? jsx('div', {
                className: 'w-16 rounded-sm border border-(--ui-stroke-secondary) bg-(--ui-bg-card) p-1.5',
                children: [
                  jsx('div', { className: 'h-1.5 w-8 rounded-sm bg-(--ui-text-primary) opacity-70' }),
                  jsx('div', { className: 'mt-1 h-1 w-full rounded-sm bg-(--ui-stroke-strong)' }),
                  jsx('div', { className: 'mt-0.5 h-1 w-3/4 rounded-sm bg-(--ui-stroke-strong)' }),
                  jsx('div', { className: 'mt-1.5 h-1 w-full rounded-sm bg-(--ui-stroke-strong)' }),
                  jsx('div', { className: 'mt-0.5 h-1 w-2/3 rounded-sm bg-(--ui-stroke-strong)' }),
                ],
              })
            : jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: tpl.format.toUpperCase() }),
          jsx('span', {
            className: cn(
              'absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full text-[0.625rem]',
              active
                ? 'bg-(--ui-accent) text-white'
                : 'border border-(--ui-stroke-secondary) bg-(--ui-bg-card) text-transparent'
            ),
            children: '✓',
          }),
        ],
      }),
      jsxs('div', { className: 'px-2.5 py-2', children: [
        jsx('div', { className: 'text-xs font-medium', children: tpl.name }),
        jsx('div', { className: 'mt-0.5 text-[0.6875rem] text-(--ui-text-tertiary)', children: tpl.description || '' }),
      ]}),
    ],
  })
}

/** 一份简历档案。 */
function ResumeRow({ resume }) {
  const tags = (resume.tags || []).filter(Boolean)
  return jsxs('div', { className: 'flex items-center gap-3 py-2.5', children: [
    jsxs('div', {
      className: 'flex h-16 w-12 flex-none items-center justify-center rounded border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) text-[0.5625rem] text-(--ui-text-tertiary)',
      children: (resume.format || 'pdf').toUpperCase(),
    }),
    jsxs('div', { className: 'min-w-0 flex-1', children: [
      jsx('div', { className: 'truncate text-xs font-medium', children: resume.title }),
      jsx('div', { className: 'mt-1 flex flex-wrap items-center gap-1.5', children:
        tags.map((tg) => jsx(Badge, { key: tg, variant: 'soft', children: tg }))
      }),
      jsx('div', { className: 'mt-1 text-[0.6875rem] text-(--ui-text-tertiary)', children:
        (resume.source === 'applied' ? '投递生成' : resume.source === 'optimized' ? '匹配优化' : '手动上传')
        + ' · ' + (resume.updated || '').slice(0, 10)
      }),
    ]}),
  ]})
}

const VIEWS = [
  { id: 'profile',   label: '个人信息' },
  { id: 'recommend', label: '岗位推荐' },
  { id: 'resume',    label: '用户简历' },
  { id: 'platform',  label: '平台接入' },
  { id: 'report',    label: '日报' },
]

function ViewBody({ ctx, view, cfg }) {
  switch (view) {
    case 'recommend': return jsx(RecommendView, { ctx, cfg })
    case 'resume':    return jsx(ResumeView, { ctx, cfg })
    case 'platform':  return jsx(PlatformView, { ctx, cfg })
    case 'report':    return jsx(ReportView, { ctx })
    default:          return jsx(ProfileView, { ctx, cfg })
  }
}

export default {
  id: ID,
  name: '好岗好找 Good-job-Ez',
  defaultEnabled: true,
  register(ctx) {
    // 1) Settings ▸ Plugins —— 主入口
    if (typeof ctx.registerSettingsPage === 'function') {
      ctx.registerSettingsPage({
        id: 'main',
        title: '好岗好找',
        icon: 'search',
        render: () => jsx(SettingsPage, { ctx }),
        children: VIEWS.map((v) => ({
          id: v.id,
          title: v.label,
          render: () => jsx(SubPage, { ctx, view: v.id }),
        })),
      })
    }

    // 2) 左侧栏入口
    ctx.register({
      id: ID + '-nav',
      area: SIDEBAR_NAV_AREA,
      data: { path: '/job-radar', label: '好岗好找', codicon: 'search' },
    })

    // 3) 路由
    ctx.register({
      id: ID + '-route',
      area: ROUTES_AREA,
      data: { path: '/job-radar' },
      render: () => jsx(SettingsPage, { ctx }),
    })
  },
}

/** Settings ▸ Plugins 下的子页 —— 单个模块，无顶部标签栏。 */
function SubPage({ ctx, view }) {
  const cfgQ = useConfig(ctx)
  if (cfgQ.isLoading) {
    return jsx('div', { className: 'flex h-full items-center justify-center', children: jsx(GlyphSpinner, {}) })
  }
  if (cfgQ.isError) {
    return jsx('div', { className: 'flex h-full items-center justify-center p-6', children: jsx(ErrorState, { message: String(cfgQ.error) }) })
  }
  return jsx('div', {
    className: 'mx-auto flex w-full max-w-3xl flex-col gap-4 p-6',
    children: jsx(ViewBody, { ctx, view, cfg: cfgQ.data }),
  })
}

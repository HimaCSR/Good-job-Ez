/**
 * 好岗好找 Good-job-Ez —— Hermes 桌面端设置页。
 *
 * 位置：$HERMES_HOME/desktop-plugins/job-radar/plugin.js
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
    className: 'flex flex-col overflow-hidden rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor)',
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2 border-b border-(--ui-stroke-tertiary) px-4 py-2.5',
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
  // **不用 window.prompt** ——
  // Electron 渲染进程里 `window.prompt()` 被禁用了（安全策略），
  // 调用它不会弹窗（或者直接抛错）→ 「＋ 添加技能」点了没反应。
  //
  // 改成**内联输入**：点「＋」出现一个小输入框，回车/点「添加」确认。
  const [adding, setAdding] = React.useState(false)
  const [draft, setDraft] = React.useState('')

  const commit = () => {
    const v = draft.trim()
    if (v) onChange([...list, v])
    setDraft('')
    setAdding(false)
  }

  const addBtn = jsx('button', {
    type: 'button',
    className: 'rounded-full border border-dashed border-(--ui-stroke-tertiary) px-2.5 py-0.5 text-xs text-(--ui-text-tertiary) hover:border-(--ui-accent) hover:text-(--ui-accent)',
    onClick: () => { setAdding(true); setDraft('') },
    children: '＋ ' + (addLabel || '添加'),
  })

  const input = adding ? jsxs('span', {
    className: 'inline-flex items-center gap-1',
    children: [
      jsx(Input, {
        value: draft,
        placeholder: placeholder || (addLabel || '输入内容'),
        onChange: (e) => setDraft(e.target.value),
        onKeyDown: (e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit() }
          if (e.key === 'Escape') { setDraft(''); setAdding(false) }
        },
        className: 'h-6 w-36 text-xs',
      }),
      jsx('button', {
        type: 'button',
        className: 'rounded border border-(--ui-stroke-tertiary) px-1.5 py-0.5 text-[0.625rem] text-(--ui-text-secondary)',
        onClick: commit,
        children: '添加',
      }),
      jsx('button', {
        type: 'button',
        className: 'rounded px-1.5 py-0.5 text-[0.625rem] text-(--ui-text-tertiary)',
        onClick: () => { setDraft(''); setAdding(false) },
        children: '取消',
      }),
    ],
  }) : null

  return jsxs('div', {
    className: 'flex flex-wrap items-center gap-1.5',
    children: [
      ...list.map((item, i) => jsxs('span', {
        key: item + '-' + i,
        className: 'inline-flex items-center gap-1 rounded-full border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) px-2.5 py-0.5 text-xs',
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
      input,
      adding ? null : addBtn,
    ],
  })
}

// ── 数据层 ──────────────────────────────────────────────────────────────────

function useConfig(ctx) {
  return useQuery({
    queryKey: ['job-radar', 'config'],
    queryFn: async () => ctx.rest('/config'),
    // **staleTime 不为 0** ——
    // 默认 0 意味着「每次窗口聚焦/重挂载都重新取数」，
    // 取回来的 data 是**新对象** → 下游 `profile` 引用变了 →
    // `useEffect` 重置本地编辑 → **用户输入被冲掉**。
    staleTime: 30_000,
  })
}

function useJobs(ctx, minScore) {
  return useQuery({
    queryKey: ['job-radar', 'jobs', minScore],
    // **取 120 条** —— 不是 30。
    //
    // 「同类型只推前 3」要**有别的类型可选**：
    // 池子顶部 30 条常常全是同一个方向（实测 30/30 都是跨境电商运营）
    // → 只取 30 条 → 去重后只剩 3 条 → 用户看不到别的机会。
    //
    // 取 120 条 → 去重后能覆盖多种类型。
    queryFn: async () => ctx.rest('/jobs?limit=120&min_score=' + (minScore || 0)),
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

/* 证件照上传。
 *
 * 照片存成**文件**（plugin-data/job-radar/photo/），后端只回 base64 用于预览 ——
 * profile.yaml 里不塞图片数据。
 */
function PhotoUpload({ ctx }) {
  const [photo, setPhoto] = React.useState(null)
  const [busy, setBusy] = React.useState(false)

  React.useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const r = await ctx.rest('/photo')
        if (alive) setPhoto((r && r.photo) || null)
      } catch (e) {
        /* 没照片就算了 */
      }
    })()
    return () => { alive = false }
  }, [ctx])

  const pick = async (e) => {
    const f = e.target.files && e.target.files[0]
    e.target.value = ''
    if (!f) return
    if (f.size > 5 * 1024 * 1024) {
      host.notify({ kind: 'error', message: '图片太大（上限 5 MB）' })
      return
    }
    setBusy(true)
    try {
      const buf = await f.arrayBuffer()
      let bin = ''
      const bytes = new Uint8Array(buf)
      const CHUNK = 0x8000
      for (let i = 0; i < bytes.length; i += CHUNK) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK))
      }
      const b64 = btoa(bin)
      await ctx.rest('/photo', {
        method: 'POST',
        body: { data_base64: b64, filename: f.name },
      })
      const r = await ctx.rest('/photo')
      setPhoto((r && r.photo) || null)
      host.notify({ kind: 'success', message: '证件照已保存' })
    } catch (err) {
      host.notify({ kind: 'error', message: String((err && err.message) || err) })
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    try {
      await ctx.rest('/photo', { method: 'DELETE' })
      setPhoto(null)
      host.notify({ kind: 'success', message: '证件照已删除' })
    } catch (err) {
      host.notify({ kind: 'error', message: String((err && err.message) || err) })
    } finally {
      setBusy(false)
    }
  }

  return jsxs('div', { className: 'flex items-start gap-3', children: [
    jsx('button', {
      type: 'button',
      onClick: photo ? remove : undefined,
      title: photo ? '点击删除' : '点击上传',
      className: cn(
        'flex h-24 w-16 shrink-0 flex-col items-center justify-center overflow-hidden',
        'rounded-md border border-dashed border-(--ui-stroke-tertiary) text-[0.625rem] text-(--ui-text-tertiary)',
        photo ? 'border-solid' : 'hover:border-(--ui-stroke-tertiary)'
      ),
      children: photo
        ? jsx('img', { src: photo, alt: '证件照', className: 'h-full w-full object-cover' })
        : [busy ? '处理中…' : '点击上传'],
    }),
    jsxs('div', { className: 'min-w-0 flex-1', children: [
      jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-secondary)', children: '证件照' }),
      jsx('div', { className: 'mt-1 text-[0.625rem] leading-relaxed text-(--ui-text-tertiary)',
        children: '2:3 比例，jpg/png/webp，5 MB 以内。会嵌进简历模板，文件只存在本机。' }),
      jsx('input', {
        type: 'file',
        accept: 'image/png,image/jpeg,image/webp',
        className: 'hidden',
        onChange: pick,
      }),
      jsx('button', {
        type: 'button',
        onClick: () => {
          const inp = document.querySelector('input[type=file][accept*="image/png"]')
          inp && inp.click()
        },
        className: 'mt-1.5 rounded-md border border-(--ui-stroke-tertiary) px-2 py-1 text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-elevated)',
        children: photo ? '换一张' : '选择图片',
      }),
    ]}),
  ] })
}

/* 结构化经历编辑器。
 *
 * 现在 profile.experience_text 是一坨自由文本 —— 简历里「工作经历」章节是空的，
 * 因为不知道公司名和时间。结构化之后每条经历有：
 *   公司 / 职位 / 起止 / 分条描述
 *
 * 描述只能从用户自己写的内容里来 —— 不给编造的入口。
 */
// 去掉对象里的 id 字段（返回新对象，不改原对象）。
//
// **不要用解构 `const { id, ...rest } = exp`** ——
// 那个写法在 JSX 编译产物里容易被静态检查误判成未定义标识符，
// 而且这里根本不需要那么绕。
function _without_id(obj) {
  const out = {}
  for (const k of Object.keys(obj || {})) {
    if (k !== 'id') out[k] = obj[k]
  }
  return out
}

function ExperienceEditor({ ctx }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['job-radar', 'experiences'],
    queryFn: async () => ctx.rest('/experiences'),
  })
  const [editing, setEditing] = React.useState(null)
  const [busy, setBusy] = React.useState(false)

  const items = (q.data && q.data.experiences) || []
  const isMock = q.data && q.data.mock

  const save = async (exp) => {
    setBusy(true)
    try {
      // **没有 id 就别把这个键带上去** ——
      // 空字符串会被当成真 id 用（详见 setEditing 那里的注释）。
      const payload = exp.id ? exp : _without_id(exp)
      const r = await ctx.rest('/experiences', { method: 'POST', body: { experience: payload } })
      if (!r || r.ok === false) {
        host.notify({ kind: 'error', message: (r && r.error) || '保存失败' })
        return
      }
      qc.invalidateQueries({ queryKey: ['job-radar', 'experiences'] })
      setEditing(null)
      host.notify({ kind: 'success', message: '经历已保存' })
    } catch (e) {
      host.notify({ kind: 'error', message: String((e && e.message) || e) })
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id) => {
    setBusy(true)
    try {
      await ctx.rest('/experiences/' + encodeURIComponent(id), { method: 'DELETE' })
      qc.invalidateQueries({ queryKey: ['job-radar', 'experiences'] })
    } catch (e) {
      host.notify({ kind: 'error', message: String((e && e.message) || e) })
    } finally {
      setBusy(false)
    }
  }

  const rows = items.map((e) => {
    const period = (e.start || '') + (e.end ? ' ~ ' + e.end : '')
    const head = jsxs('div', {
      className: 'flex items-start gap-3',
      children: [
        jsxs('div', { className: 'min-w-0 flex-1', children: [
          jsx('div', { className: 'text-xs font-medium', children: (e.company || '') + (e.title ? ' · ' + e.title : '') }),
          jsx('div', { className: 'mt-1 text-[0.6875rem] text-(--ui-text-tertiary)', children: period }),
          jsxs('div', { className: 'mt-1 flex flex-col gap-0.5', children:
            (e.bullets || []).map((b, i) => jsx('div', {
              key: i,
              className: 'text-[0.6875rem] leading-relaxed text-(--ui-text-secondary)',
              children: '· ' + b,
            })) }),
        ]}),
        jsxs('div', { className: 'flex shrink-0 gap-1', children: [
          jsx('button', {
            type: 'button',
            onClick: () => setEditing(e),
            className: 'rounded border border-(--ui-stroke-tertiary) px-2 py-0.5 text-[0.625rem] text-(--ui-text-secondary)',
            children: '编辑',
          }),
          jsx('button', {
            type: 'button',
            onClick: () => remove(e.id),
            className: 'rounded border border-(--ui-stroke-tertiary) px-2 py-0.5 text-[0.625rem] text-(--ui-text-tertiary)',
            children: '删除',
          }),
        ] }),
      ],
    })
    return jsx('div', {
      key: e.id,
      className: 'border-b border-(--ui-stroke-tertiary) py-2.5 last:border-b-0',
      children: head,
    })
  })

  const addBtn = jsx('button', {
    type: 'button',
    // **id 用 null，不空字符串** ——
    // 空字符串会被后端当成「一个真实的 id」，
    // 于是 upsert 把同 id 的旧记录顶掉 → **新增一条就把旧的挤掉**。
    onClick: () => setEditing({ id: null, company: '', title: '', start: '', end: '', bullets: [''] }),
    className: 'rounded-md border border-dashed border-(--ui-stroke-tertiary) px-3 py-1.5 text-[0.6875rem] text-(--ui-text-tertiary) hover:border-(--ui-stroke-tertiary)',
    children: '＋ 添加一段经历',
  })

  const editor = editing ? jsx(ExperienceForm, {
    exp: editing,
    busy,
    onCancel: () => setEditing(null),
    onSave: save,
  }) : null

  return jsxs('div', { className: 'flex flex-col gap-3', children: [
    isMock ? jsx('div', {
      className: 'rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) px-2.5 py-1.5 text-[0.6875rem] text-(--ui-text-tertiary)',
      children: '开发模式：下面显示的是 mock 数据',
    }) : null,
    rows.length ? jsxs('div', { children: rows }) : null,
    rows.length ? null : jsx('div', {
      className: 'rounded-md border border-(--ui-stroke-tertiary) p-3 text-[0.6875rem] leading-relaxed text-(--ui-text-tertiary)',
      children: '还没有结构化的经历。简历里的「工作经历」章节要靠它 —— 有公司名和时间才完整。',
    }),
    addBtn,
    editor,
  ] })
}

/* 一条经历的编辑表单。 */
function ExperienceForm({ exp, busy, onCancel, onSave }) {
  const [draft, setDraft] = React.useState(() => ({
    id: exp.id || '',
    company: exp.company || '',
    title: exp.title || '',
    start: exp.start || '',
    end: exp.end || '',
    bullets: (exp.bullets && exp.bullets.length ? exp.bullets : ['']).slice(),
  }))

  const set = (k, v) => setDraft((s) => ({ ...s, [k]: v }))
  const setBullet = (i, v) => setDraft((s) => {
    const b = s.bullets.slice()
    b[i] = v
    return { ...s, bullets: b }
  })
  const addBullet = () => setDraft((s) => ({ ...s, bullets: s.bullets.concat(['']) }))
  const delBullet = (i) => setDraft((s) => ({ ...s, bullets: s.bullets.filter((_, j) => j !== i) }))

  const bulletInputs = draft.bullets.map((b, i) => jsx('div', {
    key: i,
    className: 'flex items-start gap-1.5',
    children: [
      jsx('textarea', {
        value: b,
        onChange: (e) => setBullet(i, e.target.value),
        rows: 2,
        placeholder: '做过什么，有什么结果（数字最好）',
        className: 'min-h-14 flex-1 rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor) px-2 py-1 text-xs text-(--ui-text-primary)',
      }),
      jsx('button', {
        type: 'button',
        onClick: () => delBullet(i),
        className: 'mt-1 rounded px-1.5 py-0.5 text-[0.625rem] text-(--ui-text-tertiary)',
        children: '×',
      }),
    ],
  }))

  return jsxs('div', {
    className: 'flex flex-col gap-2.5 rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-3',
    children: [
      jsxs('div', { className: 'grid grid-cols-2 gap-2', children: [
        jsx(Field, { label: '公司', children: jsx(Input, {
          value: draft.company,
          onChange: (e) => set('company', e.target.value),
          placeholder: '某科技有限公司',
        }) }),
        jsx(Field, { label: '职位', children: jsx(Input, {
          value: draft.title,
          onChange: (e) => set('title', e.target.value),
          placeholder: '高级前端工程师',
        }) }),
        jsx(Field, { label: '开始', children: jsx(Input, {
          value: draft.start,
          onChange: (e) => set('start', e.target.value),
          placeholder: '2023-04',
        }) }),
        jsx(Field, { label: '结束', children: jsx(Input, {
          value: draft.end,
          onChange: (e) => set('end', e.target.value),
          placeholder: '至今',
        }) }),
      ] }),
      jsxs('div', { className: 'flex flex-col gap-1.5', children:
        [jsx('div', { className: 'text-xs font-medium text-(--ui-text-secondary)', children: '做过什么' })]
          .concat(bulletInputs)
          .concat([jsx('button', {
            type: 'button',
            onClick: addBullet,
            className: 'self-start rounded border border-(--ui-stroke-tertiary) px-2 py-0.5 text-[0.625rem] text-(--ui-text-secondary)',
            children: '＋ 加一条',
          })]) }),
      jsxs('div', { className: 'flex gap-2', children: [
        jsx('button', {
          type: 'button',
          disabled: busy || !draft.company.trim(),
          onClick: () => onSave(draft),
          className: cn('rounded-md border border-(--ui-accent) px-2.5 py-1 text-[0.6875rem]',
            'text-(--ui-text-primary) disabled:opacity-50'),
          children: busy ? '保存中…' : '保存',
        }),
        jsx('button', {
          type: 'button',
          onClick: onCancel,
          className: 'rounded-md border border-(--ui-stroke-tertiary) px-2.5 py-1 text-[0.6875rem] text-(--ui-text-secondary)',
          children: '取消',
        }),
      ] }),
    ],
  })
}

/* 示例画像 —— 给新用户一个「照着改」的起点。
 *
 * ## 为什么需要
 *
 * 新用户装完插件，画像是空的 → 方向、技能、城市全空 →
 * **所有岗位分数都低** → 分数线一卡就全军覆没 →
 * 看起来像「插件坏了」。
 *
 * 填一份示例，用户立刻能看懂每个字段是干什么的，
 * 然后照着改成自己的。
 *
 * 示例用前端/three.js 那套 —— 不是推荐给谁，
 * 只是**字段示例**，填完记得改。
 */
const SAMPLE_PROFILE = {
  title_keywords_primary: ['前端', 'web前端'],
  title_keywords: ['前端开发', '全栈'],
  skills: ['javascript', 'vue', 'css', 'html5'],
  cities: ['杭州'],
  min_salary: 10,
  min_experience_years: 1,
  exclude_companies: ['外包', '劳务派遣'],
}

function ProfileView({ ctx, cfg, onSaved }) {
  const qc = useQueryClient()
  const profile = (cfg && cfg.profile) || {}

  const save = useMutation({
    mutationFn: async (next) => ctx.rest('/profile', { method: 'POST', body: next }),
    // **后端会根据经历自动补方向词 + 重算岗位分数** ——
    //
    // 用户诉求：「每次保存个人信息，便重新根据经历内容更新期望内容标签，
    // 保证抓取的岗位更加契合用户」。
    //
    // → 后端返回 `note`（补了哪些方向词）和 `rescored`（重算了几个岗位），
    //   这里**告诉用户** —— 不说的话用户不知道画像变了。
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['job-radar', 'config'] })
      // **岗位分数变了 → 推荐列表也要重取**
      qc.invalidateQueries({ queryKey: ['job-radar', 'jobs'] })
      const note = (r && r.note) || ''
      const rescored = (r && r.rescored) || 0
      let msg = '个人信息已保存'
      if (note) {
        msg += ' · ' + note
        if (rescored) msg += '（已重算 ' + rescored + ' 个岗位分数）'
      }
      host.notify({ kind: 'success', message: msg })
      setDirty(false)
      onSaved && onSaved()
    },
    onError: (e) => host.notify({ kind: 'error', message: String(e && e.message || e) }),
  })

  // **profile 的引用必须稳定** ——
  //
  // `(cfg && cfg.profile) || {}` 在 profile 不存在时每次渲染都是**新对象**，
  // 而 useQuery 的 data 引用也可能随重新取数变化。
  // 后果：`React.useEffect(() => setLocal(profile), [profile])`
  // **每次渲染都跑** → 用户刚输入的值立刻被服务端旧值覆盖回去
  // → 表现就是「输入框里打不进字」。
  //
  // 修法：**用内容的字符串签名当依赖**，内容没变就不重置用户输入。
  const profileKey = React.useMemo(
    () => { try { return JSON.stringify(profile || {}) } catch (e) { return '' } },
    [profile]
  )
  const [local, setLocal] = React.useState(profile)
  const lastKey = React.useRef(profileKey)
  // **有未保存的改动吗** ——
  // 填了东西没保存，用户看不出来 → 以为没生效。
  // 按钮旁给一句提示（「有改动未保存」/「已保存」）。
  const [dirty, setDirty] = React.useState(false)
  React.useEffect(() => {
    // 只有**服务端数据真的变了**才重置本地编辑
    if (profileKey !== lastKey.current) {
      lastKey.current = profileKey
      setLocal(profile)
    }
  }, [profileKey, profile])

  const set = (k, v) => {
    setDirty(true)
    setLocal((s) => ({ ...s, [k]: v }))
  }
  const identity = local.identity || {}
  // **set 的第一个参数是键名** ——
  // 之前这里写的是 `set((s) => ...)`，把**函数**当成键名传进去了，
  // 于是 `local.identity` 根本没被改 → **姓名/电话/邮箱/学历/院校/专业
  // 六个字段全都打不进字**（症状：输入框里怎么敲都是空的）。
  const setIdentity = (k, v) => {
    setDirty(true)
    setLocal((s) => ({
      ...s,
      identity: { ...(s.identity || {}), [k]: v },
    }))
  }

  if (!profile || !Object.keys(profile).length) {
    return jsx(ErrorState, { message: '读不到个人画像' })
  }

  // **还没填方向和技能** —— 新用户装完就是这个状态。
  // 不引导的话，用户会看到「所有岗位分数都很低」，
  // 以为插件坏了。
  const isBlank = !((local.title_keywords_primary || []).length
                    || (local.title_keywords || []).length
                    || (local.skills || []).length)

  return jsxs(Fragment, {
    children: [
      isBlank ? jsxs('div', {
        className: 'rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-3',
        children: [
          jsx('div', {
            className: 'text-sm font-medium',
            children: '先填「主攻方向」和「我的技能」，才能开始匹配',
          }),
          jsx('div', {
            className: 'mt-1 text-[0.6875rem] leading-relaxed text-(--ui-text-tertiary)',
            children: '不知道填什么？点下面「填一份示例」，照着改成你自己的 —— ' +
              '方向是岗位名里的词（命中就加分），技能是 JD 里提到的词。',
          }),
          jsx('div', { className: 'mt-2 flex gap-2', children: [
            jsx(Button, {
              size: 'sm',
              variant: 'outline',
              onClick: () => {
                const next = {
                  ...local,
                  title_keywords_primary: SAMPLE_PROFILE.title_keywords_primary,
                  title_keywords: SAMPLE_PROFILE.title_keywords,
                  skills: SAMPLE_PROFILE.skills,
                  cities: (local.cities || []).length ? local.cities : SAMPLE_PROFILE.cities,
                  min_salary: local.min_salary || SAMPLE_PROFILE.min_salary,
                  exclude_companies: (local.exclude_companies || []).length
                    ? local.exclude_companies : SAMPLE_PROFILE.exclude_companies,
                }
                setLocal(next)
                setDirty(true)
                host.notify({ kind: 'info', message: '已填入示例 —— 记得改成你自己的' })
              },
              children: '填一份示例',
            }),
          ] }),
        ],
      }) : null,
      isBlank ? jsx('div', { className: 'h-3' }) : null,
      jsx(Panel, {
        title: '身份信息',
        hint: '仅用于简历生成表单',

        // **保存按钮放第一个面板** ——
        // 用户填完姓名/电话就找保存，找不到就会以为没生效。
        // （之前只在「真实经历」面板有 —— 用户填完上面三个面板，
        //   根本不知道要往下滚到哪去找保存。）
        actions: jsxs('div', {
          className: 'flex items-center gap-2',
          children: [
            // **未保存提示** —— 填了没保存要看得见，
            // 否则用户以为「填了没生效」。
            jsx('span', {
              className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
              children: dirty ? '有改动，未保存' : '',
            }),
            jsx(Button, {
              size: 'sm',
              variant: 'default',
              disabled: save.isPending,
              onClick: () => save.mutate(local),
              children: save.isPending ? '保存中…' : '保存个人信息',
            }),
          ],
        }),
        children: jsxs('div', {
          className: 'grid grid-cols-2 gap-4',
          children: [
            jsx(Field, {
              label: '证件照',
              wide: true,
              children: jsx(PhotoUpload, { ctx }),
            }),
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
            // ── 模板要用的字段 ──
            //
            // **为什么加这几个** —— 简历模板（尤其 WPS 系的）
            // 页眉上常有「意向岗位 / 意向城市 / 期望薪资 / 求职类型 /
            // 性别 / 年龄」。表单里没有 → **模板渲染时这些字段全空**
            // → 用户看到「模板上有位置，我的怎么没有」。
            //
            // 本机踩过：现场管理模板有 5 个页眉字段，用户画像一个都没有
            // → 页眉只剩姓名。
            // **意向岗位 / 意向城市 / 期望薪资 不在这里填** ——
            //
            // 用户原话：「意向岗位、及意向城市，根据岗位JD有的内容自动化填写」。
            //
            // → **每个岗位都不一样**（投重庆的岗位写「意向城市：重庆」，
            // 投广州的写「广州」）→ 手填的值**必然过期**。
            // → **简历优化时从 JD 自动取**（`resume_builder._build_identity`）。
            //
            // 保留手填反而坑：用户填了「广州」，投重庆的岗位时
            // 简历上写「广州」→ 投错地方。
            //
            // 这里的表单只留**跟岗位无关**的（姓名/电话/邮箱/性别/年龄/学历/学校/专业）。

            jsx(Field, {
              label: '期望薪资',
              hint: '留空就用岗位上写的',
              children: jsx(Input, {
                value: identity.salary || '',
                onChange: (e) => setIdentity('salary', e.target.value),
                placeholder: '9k-13k',
              }),
            }),
            jsx(Field, {
              label: '求职类型',
              children: jsx('select', {
                className: 'h-8 w-full rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) px-2 text-sm outline-none focus:border-(--ui-accent)',
                value: identity.job_type || '社招',
                onChange: (e) => setIdentity('job_type', e.target.value),
                children: ['社招', '校招', '实习', '应届'].map((t) =>
                  jsx('option', { key: t, value: t, children: t })),
              }),
            }),
            jsx(Field, {
              label: '性别',
              children: jsx('select', {
                className: 'h-8 w-full rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) px-2 text-sm outline-none focus:border-(--ui-accent)',
                value: identity.gender || '',
                onChange: (e) => setIdentity('gender', e.target.value),
                children: [
                  jsx('option', { key: '_', value: '', children: '不填' }),
                  jsx('option', { key: 'm', value: '男', children: '男' }),
                  jsx('option', { key: 'f', value: '女', children: '女' }),
                ],
              }),
            }),
            jsx(Field, {
              label: '年龄',
              children: jsx(Input, {
                value: identity.age || '',
                onChange: (e) => setIdentity('age', e.target.value),
                placeholder: '25',
              }),
            }),
            jsx(Field, {
              label: '最高学历',
              children: jsx('select', {
                className: 'h-8 w-full rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) px-2 text-sm outline-none focus:border-(--ui-accent)',
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
      // **说明各面板的保存方式** ——
      // 「保存个人信息」只管表单里的字段；
      // 证件照和结构化经历是**各自单独保存**的。
      jsx('p', {
        className: 'text-[0.6875rem] leading-relaxed text-(--ui-text-tertiary)',
        children: '「保存个人信息」保存的是姓名、联系方式、技能、城市、'
          + '期望薪资和「真实经历」里的文字。证件照和「结构化经历」'
          + '是各自单独保存的 —— 证件照上传即存，经历添加即存。',
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
              label: '主攻方向',
              wide: true,
              hint: '出现在岗位名里就命中，命中给满 30 分 —— 排最前面',
              children: jsx(ChipEditor, {
                value: local.title_keywords_primary || [],
                onChange: (v) => set('title_keywords_primary', v),
                addLabel: '添加主攻方向',
              }),
            }),
            jsx(Field, {
              label: '也投的方向',
              wide: true,
              hint: '也投，但命中只给 15 分 —— 排在主攻方向后面',
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
      jsx('div', { className: 'h-3' }),
      jsx(Panel, {
        title: '结构化经历',
        hint: '公司 / 职位 / 起止 —— 简历「工作经历」章节靠它',
        children: jsx(ExperienceEditor, { ctx }),
      }),
      // **末尾再放一个保存入口** ——
      // 用户填完「真实经历」「结构化经历」往下滚到底就能保存，
      // 不用再滚回顶部找按钮。
      jsx('div', { className: 'h-3' }),
      jsxs('div', {
        className: 'flex items-center justify-end gap-2',
        children: [
          jsx('span', {
            className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
            children: dirty ? '有改动，未保存' : '',
          }),
          jsx(Button, {
            size: 'sm',
            variant: 'default',
            disabled: save.isPending,
            onClick: () => save.mutate(local),
            children: save.isPending ? '保存中…' : '保存个人信息',
          }),
        ],
      }),
    ],
  })
}

// ── 岗位推荐 ────────────────────────────────────────────────────────────────

function JobCard({ job, ctx }) {
  const [open, setOpen] = React.useState(false)
  const [optOpen, setOptOpen] = React.useState(false)
  const [applyOpen, setApplyOpen] = React.useState(false)
  const score = job.score ?? 0
  const tone = score >= 70 ? 'success' : score >= 50 ? 'warn' : 'muted'
  return jsxs('div', {
    className: 'border-b border-(--ui-stroke-tertiary) last:border-b-0',
    children: [
      jsxs('div', {
        className: 'flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-(--ui-bg-elevated)',
        onClick: () => setOpen(!open),
        children: [
          jsx('span', {
            className: cn('mt-1 text-[0.625rem] text-(--ui-text-tertiary) transition-transform',
              open && 'rotate-90'),
            children: '▶',
          }),
          jsxs('div', { className: 'min-w-0 flex-1', children: [
            jsx('div', { className: 'text-sm font-medium', children: job.title || '' }),
            jsx('div', { className: 'mt-1 text-xs text-(--ui-text-tertiary)', children: job.company || '' }),
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
        jsxs('div', { className: 'mt-2 flex flex-wrap gap-2', children: [
          jsx('button', {
            type: 'button',
            className: cn(
              'rounded-md border border-(--ui-stroke-tertiary) px-2.5 py-1',
              'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-elevated)'
            ),
            onClick: (e) => { e.stopPropagation(); setOptOpen(true) },
            children: '简历匹配优化',
          }),
          jsx('button', {
            type: 'button',
            className: cn(
              'rounded-md border border-(--ui-stroke-tertiary) px-2.5 py-1',
              'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-elevated)'
            ),
            onClick: (e) => { e.stopPropagation(); setApplyOpen(true) },
            children: '投递简历',
          }),
          job.url ? jsx('a', {
            href: job.url,
            target: '_blank',
            rel: 'noreferrer',
            className: cn(
              'rounded-md border border-(--ui-stroke-tertiary) px-2.5 py-1',
              'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-elevated)'
            ),
            children: '打开岗位',
          }) : null,
        ]}),
      ]}),
      optOpen && jsx(ResumeOptimizeDialog, {
        job,
        ctx,
        onClose: () => setOptOpen(false),
      }),
      applyOpen && jsx(ApplyResumeDialog, {
        job,
        ctx,
        onClose: () => setApplyOpen(false),
      }),
    ],
  })
}

/* 投递简历 —— 三道门 + 历史简历推荐。
 *
 * 流程：
 *   ① 闸门体检（GET /apply/gate）—— 站点开关 / 每日上限
 *   ② 选简历（历史简历按匹配分排序，默认最高分）
 *   ③ 签发一次性令牌（POST /apply/token）
 *   ④ 确认投递（POST /apply/submit）
 *
 * **每一道门没过就停在那一步**，不往下走。
 * 选定简历 ≠ 授权投递 —— 最后还要再点一次带岗位链接的确认。
 */
function ApplyResumeDialog({ job, ctx, onClose }) {
  const [phase, setPhase] = React.useState('gate')   // gate | pick | confirm | done
  const [gate, setGate] = React.useState(null)
  const [items, setItems] = React.useState([])
  const [picked, setPicked] = React.useState(null)
  const [token, setToken] = React.useState(null)
  const [err, setErr] = React.useState('')
  const [busy, setBusy] = React.useState(false)

  // ① 闸门体检
  React.useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const g = await ctx.rest('/apply/gate?job_id=' + encodeURIComponent(job.job_id))
        if (!alive) return
        setGate(g)
        if (!g.can_apply) { setPhase('gate'); return }
        const r = await ctx.rest('/resume/list?job_id=' + encodeURIComponent(job.job_id))
        if (!alive) return
        const list = (r && r.resumes) || []
        setItems(list)
        if (list.length) {
          const best = list.reduce((a, b) =>
            (b.match_score || 0) > (a.match_score || 0) ? b : a)
          setPicked(best.resume_id)
        }
        setPhase('pick')
      } catch (e) {
        if (alive) { setErr(String((e && e.message) || e)); setPhase('gate') }
      }
    })()
    return () => { alive = false }
  }, [job.job_id, ctx])

  // ③ 签令牌
  const issueToken = async () => {
    setBusy(true); setErr('')
    try {
      const r = await ctx.rest('/apply/token', {
        method: 'POST',
        body: { job_id: job.job_id, resume_id: picked },
      })
      if (!r || r.ok === false) {
        setErr(r && r.error ? r.error : '拿不到确认令牌')
        if (r && r.stage === 'site_switch') {
          setGate((g) => g ? { ...g, can_apply: false,
            blocked_by: [{ gate: 'site_switch', label: r.error, hint: '' }] } : g)
          setPhase('gate')
        }
        return
      }
      setToken(r.token)
      setPhase('confirm')
    } catch (e) {
      setErr(String((e && e.message) || e))
    } finally {
      setBusy(false)
    }
  }

  // ④ 投递
  const submit = async () => {
    setBusy(true); setErr('')
    try {
      const r = await ctx.rest('/apply/submit', {
        method: 'POST',
        body: { job_id: job.job_id, resume_id: picked, token },
      })
      if (!r || r.ok === false) {
        setErr(r && r.error ? r.error : '投递失败')
        if (r && r.stage === 'daily_limit') {
          setGate((g) => g ? { ...g, can_apply: false,
            blocked_by: [{ gate: 'daily_limit', label: r.error, hint: '' }] } : g)
          setPhase('gate')
        }
        return
      }
      setPhase('done')
    } catch (e) {
      setErr(String((e && e.message) || e))
    } finally {
      setBusy(false)
    }
  }

  const chosen = items.find((r) => r.resume_id === picked)
  const blocked = (gate && gate.blocked_by) || []

  // 简历列表的每一项 —— 先算成变量，JSX 里只放引用，
  // 免得嵌套 map 里的括号数到眼花。
  const resumeRows = items.map((r) => {
    const score = r.match_score
    const tagEls = (r.tags || []).slice(0, 6).map((tag, i) => jsx('span', {
      key: tag + i,
      className: 'rounded bg-(--ui-bg-elevated) px-1.5 py-0.5 text-[0.625rem] text-(--ui-text-secondary)',
      children: tag,
    }))
    const main = jsxs('div', {
      className: 'min-w-0 flex-1',
      children: [
        jsx('div', { className: 'truncate text-xs font-medium', children: r.title || '' }),
        jsx('div', { className: 'mt-1 text-[0.6875rem] text-(--ui-text-tertiary)', children: (r.created || '').slice(0, 10) }),
        jsxs('div', { className: 'mt-1.5 flex flex-wrap gap-1', children: tagEls }),
      ],
    })
    const badge = jsx(Badge, {
      variant: score >= 70 ? 'success' : score >= 50 ? 'warn' : 'muted',
      children: String(score != null ? score : '—'),
    })
    return jsx('button', {
      key: r.resume_id,
      type: 'button',
      onClick: () => setPicked(r.resume_id),
      className: cn(
        'flex items-start gap-3 rounded-lg border p-3 text-left transition-colors',
        picked === r.resume_id
          ? 'border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated)'
          : 'border-(--ui-stroke-tertiary) hover:bg-(--ui-bg-elevated)'
      ),
      children: [main, badge],
    })
  })

  const emptyBox = jsx('div', {
    className: 'rounded-md border border-(--ui-stroke-tertiary) p-4 text-xs leading-relaxed',
    children: [
      jsx('div', { className: 'text-(--ui-text-primary)', children: '还没有可用的简历。' }),
      jsx('div', { className: 'mt-1 text-(--ui-text-tertiary)', children: '先去「简历匹配优化」生成一份并存进档案，投递时才有东西可选。' }),
    ],
  })

  const nextBtn = jsx('button', {
    type: 'button',
    disabled: !picked || busy,
    onClick: issueToken,
    className: cn('mt-1 self-end rounded-md border border-(--ui-accent) px-3 py-1.5', 'text-xs text-(--ui-text-primary) disabled:opacity-50'),
    children: busy ? '处理中…' : '下一步：确认投递',
  })

  const pickBody = items.length === 0
    ? [emptyBox]
    : resumeRows.concat([nextBtn])

  return jsx('div', {
    className: cn('fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-6'),
    onClick: onClose,
    children: jsxs('div', {
      className: cn(
        'flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden',
        'rounded-xl border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor)'
      ),
      onClick: (e) => e.stopPropagation(),
      children: [
        jsxs('div', {
          className: 'flex items-center justify-between border-b border-(--ui-stroke-tertiary) px-4 py-3',
          children: [
            jsxs('div', { children: [
              jsx('div', { className: 'text-sm font-medium', children: '投递简历' }),
              jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
                children: job.title || '' }),
            ]}),
            jsx('button', {
              type: 'button',
              onClick: onClose,
              className: 'text-xs text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
              children: '关闭',
            }),
          ],
        }),

        jsxs('div', { className: 'flex flex-col gap-3 overflow-auto p-4', children: [
          // 步骤条
          jsxs('div', { className: 'flex items-center gap-1 text-[0.625rem]', children:
            [['体检', 'gate'], ['选简历', 'pick'], ['确认', 'confirm']].map((s, i, arr) => {
              const order = { gate: 0, pick: 1, confirm: 2 }
              const cur = order[phase] != null ? order[phase] : 3
              const done = order[s[1]] < cur
              const active = order[s[1]] === cur
              return jsxs('div', { key: s[1], className: 'flex items-center gap-1', children: [
                jsx('span', {
                  className: cn('rounded px-1.5 py-0.5',
                    active ? 'bg-(--ui-accent) text-(--ui-text-primary)'
                      : done ? 'text-(--ui-text-secondary)' : 'text-(--ui-text-quaternary)'),
                  children: s[0],
                }),
                i < arr.length - 1 ? jsx('span', { className: 'text-(--ui-text-quaternary)', children: '›' }) : null,
              ]})
            })}),

          err ? jsx('div', {
            className: 'rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-2.5 text-[0.6875rem] text-(--ui-text-secondary)',
            children: err,
          }) : null,

          // ① 闸门没过
          phase === 'gate' && blocked.length
            ? jsxs('div', {
                className: 'rounded-md border border-(--ui-stroke-tertiary) p-3 text-xs leading-relaxed',
                children: [
                  jsx('div', { className: 'mb-2 text-(--ui-text-primary)', children: '现在不能投，卡在这些地方：' }),
                  jsxs('div', { className: 'flex flex-col gap-2', children:
                    blocked.map((b, i) => jsxs('div', {
                      key: i,
                      className: 'rounded border border-(--ui-stroke-tertiary) p-2',
                      children: [
                        jsx('div', { className: 'text-(--ui-text-primary)', children: b.label }),
                        b.hint ? jsx('div', { className: 'mt-1 text-[0.6875rem] text-(--ui-text-tertiary)',
                          children: b.hint }) : null,
                      ],
                    }))}),
                  gate && gate.daily_limit ? jsx('div', {
                    className: 'mt-2 text-[0.6875rem] text-(--ui-text-tertiary)',
                    children: '今日已投 ' + gate.daily_used + ' / 上限 ' + gate.daily_limit,
                  }) : null,
                ],
              })
            : null,

          phase === 'gate' && !blocked.length
            ? jsx('div', { className: 'py-6 text-center text-xs text-(--ui-text-tertiary)',
                children: '正在检查投递条件…' })
            : null,

          // ② 选简历
          phase === 'pick'
            ? jsxs('div', { className: 'flex flex-col gap-2', children: pickBody })
            : null,

          // ③ 确认
          phase === 'confirm'
            ? jsxs('div', { className: 'flex flex-col gap-2', children: [
                jsx('div', {
                  className: 'rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-3 text-[0.6875rem] leading-relaxed text-(--ui-text-secondary)',
                  children: [
                    jsx('div', { children: '即将投递：' + (chosen ? (chosen.title || chosen.resume_id) : '') }),
                    jsx('div', { className: 'mt-1 text-(--ui-text-tertiary)',
                      children: '岗位：' + (job.title || '') }),
                    jsx('div', { className: 'mt-1 text-(--ui-text-tertiary)',
                      children: '确认令牌已签发（5 分钟内有效，一次性）' }),
                  ],
                }),
                jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
                  children: '投递不可逆。确认后会真的投出去，并把这份简历存进档案、打上标签。' }),
                jsxs('div', { className: 'mt-1 flex gap-2', children: [
                  jsx('button', {
                    type: 'button',
                    disabled: busy,
                    onClick: submit,
                    className: cn('rounded-md border border-(--ui-accent) px-3 py-1.5 text-xs',
                      'text-(--ui-text-primary) disabled:opacity-50'),
                    children: busy ? '投递中…' : '确认投递',
                  }),
                  job.url ? jsx('a', {
                    href: job.url, target: '_blank', rel: 'noreferrer',
                    className: 'rounded-md border border-(--ui-stroke-tertiary) px-3 py-1.5 text-xs text-(--ui-text-secondary)',
                    children: '去招聘网站手动投',
                  }) : null,
                ]}),
              ]})
            : null,

          // 完成
          phase === 'done'
            ? jsxs('div', { className: 'py-6 text-center', children: [
                jsx('div', { className: 'text-sm text-(--ui-text-primary)', children: '投递完成' }),
                jsx('div', { className: 'mt-1 text-[0.6875rem] text-(--ui-text-tertiary)',
                  children: '简历已存进「用户简历」并打好标签' }),
              ]})
            : null,
        ]}),
      ],
    }),
  })
}

/* 简历匹配优化弹窗。
 *
 * **只生成，不投递** —— 投递要用户明确点确认，那是另一道闸门。
 * 结果里有「← 依据：经历第 N 条」的标注，可以核对每条都是真经历。
 */
function ResumeOptimizeDialog({ job, ctx, onClose }) {
  const [tpl, setTpl] = React.useState('classic')
  const [state, setState] = React.useState({ phase: 'idle' })
  const [showBasis, setShowBasis] = React.useState(true)

  const run = React.useCallback(async () => {
    setState({ phase: 'loading' })
    try {
      const r = await ctx.rest('/resume/optimize', {
        method: 'POST',
        body: { job_id: job.job_id, template_id: tpl, save: false },
      })
      if (r && r.ok === false) {
        setState({ phase: 'error', error: r.error, hint: r.hint })
        return
      }
      setState({ phase: 'done', data: r })
    } catch (e) {
      setState({ phase: 'error', error: String((e && e.message) || e) })
    }
  }, [job.job_id, tpl, ctx])

  const save = React.useCallback(async () => {
    setState((s) => ({ ...s, phase: 'saving' }))
    try {
      const r = await ctx.rest('/resume/optimize', {
        method: 'POST',
        body: { job_id: job.job_id, template_id: tpl, save: true },
      })
      if (r && r.ok === false) {
        setState((s) => ({ ...s, phase: 'error', error: r.error, hint: r.hint }))
        return
      }
      setState((s) => ({ ...s, phase: 'done', data: r, saved: r.saved }))
    } catch (e) {
      setState((s) => ({ ...s, phase: 'error', error: String((e && e.message) || e) }))
    }
  }, [job.job_id, tpl, ctx])

  const d = state.data
  const html = showBasis ? (d && d.html_preview) : (d && d.html)

  return jsx('div', {
    className: cn(
      'fixed inset-0 z-50 flex items-center justify-center',
      'bg-black/55 p-6'
    ),
    onClick: onClose,
    children: jsxs('div', {
      className: cn(
        'flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden',
        'rounded-xl border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor)'
      ),
      onClick: (e) => e.stopPropagation(),
      children: [
        jsxs('div', {
          className: 'flex items-center justify-between border-b border-(--ui-stroke-tertiary) px-4 py-3',
          children: [
            jsxs('div', { children: [
              jsx('div', { className: 'text-sm font-medium', children: '简历匹配优化' }),
              jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: job.title || '' }),
            ]}),
            jsxs('div', {
              className: 'flex items-center gap-3',
              children: [
                // **「编辑槽位」** —— 转换时猜错了可以改。
                //
                // 只给**有槽位的模板**（PDF 转换来的）显示 ——
                // 内置模板没有 spec.json，给个点进去是空的入口更糟。
                jsx('button', {
                  type: 'button',
                  onClick: loadSlots,
                  className: 'rounded border border-(--ui-stroke-tertiary) px-2 py-1 text-xs text-(--ui-text-secondary) hover:text-(--ui-text-primary)',
                  children: '编辑槽位',
                }),
                jsx('button', {
                  type: 'button',
                  onClick: onClose,
                  className: 'text-xs text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
                  children: '关闭',
                }),
              ],
            }),
          ],
        }),
        jsxs('div', { className: cn('flex flex-col gap-3 overflow-auto p-4',
          editing && 'hidden'), children: [
          jsxs('div', { className: 'flex flex-wrap items-center gap-2', children: [
            jsx('span', { className: 'text-xs text-(--ui-text-secondary)', children: '模板' }),
            ...['classic', 'modern', 'tech', 'acad'].map((id) => jsx('button', {
              key: id,
              type: 'button',
              onClick: () => setTpl(id),
              className: cn(
                'rounded-md border px-2.5 py-1 text-[0.6875rem]',
                tpl === id
                  ? 'border-(--ui-accent) text-(--ui-text-primary)'
                  : 'border-(--ui-stroke-tertiary) text-(--ui-text-secondary)'
              ),
              children: ({ classic: '经典单栏', modern: '现代双栏', tech: '技术极客', acad: '学术风' })[id],
            })),
            state.phase === 'idle' || state.phase === 'error'
              ? jsx('button', {
                  type: 'button',
                  onClick: run,
                  className: cn(
                    'rounded-md border border-(--ui-accent) px-2.5 py-1',
                    'text-[0.6875rem] text-(--ui-text-primary)'
                  ),
                  children: '开始优化',
                })
              : null,
          ]}),

          state.phase === 'loading' || state.phase === 'saving'
            ? jsx('div', { className: 'py-8 text-center text-xs text-(--ui-text-tertiary)', children: '正在分析 JD 与你的经历…' })
            : null,

          state.phase === 'error'
            ? jsxs('div', {
                className: 'rounded-md border border-(--ui-stroke-tertiary) p-3 text-xs',
                children: [
                  jsx('div', { className: 'text-(--ui-text-primary)', children: state.error }),
                  state.hint ? jsx('div', { className: 'mt-1 text-(--ui-text-tertiary)', children: state.hint }) : null,
                ],
              })
            : null,

          d ? jsxs('div', { className: 'flex flex-col gap-3', children: [
            jsxs('div', { className: 'flex flex-wrap gap-3 text-[0.6875rem]', children: [
              jsx('span', { className: 'text-(--ui-text-secondary)',
                children: '命中 ' + ((d.matched && d.matched.covered) || []).length + ' 条经历' }),
              (d.matched && d.matched.gaps && d.matched.gaps.length)
                ? jsx('span', { className: 'text-(--ui-text-quaternary)',
                    children: '缺口：' + d.matched.gaps.map((g) => g.name).join('、') })
                : null,
              jsx('span', { className: 'text-(--ui-text-tertiary)',
                children: '依据来自你的真实经历，不会编造' }),
            ]}),
            jsxs('div', { className: 'flex items-center gap-2', children: [
              jsx('label', { className: 'flex items-center gap-1.5 text-[0.6875rem] text-(--ui-text-secondary)', children: [
                jsx('input', {
                  type: 'checkbox',
                  style: { accentColor: 'var(--ui-accent)' },
                  checked: showBasis,
                  onChange: (e) => setShowBasis(e.target.checked),
                }),
                '显示依据标注',
              ]}),
              jsx('button', {
                type: 'button',
                onClick: save,
                className: cn(
                  'rounded-md border border-(--ui-stroke-tertiary) px-2.5 py-1',
                  'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-elevated)'
                ),
                children: state.saved ? '已存进简历档案' : '存进简历档案',
              }),
            ]}),
            jsx('div', {
              className: cn(
                'overflow-auto rounded-md border border-(--ui-stroke-tertiary)',
                'bg-white p-6'
              ),
              dangerouslySetInnerHTML: { __html: html || '' },
            }),
          ]}) : null,
        ]}),
      ],
    }),
  })
}

function RecommendView({ ctx, cfg }) {
  const settings = (cfg && cfg.settings) || {}
  const jobsQ = useJobs(ctx, 0)
  const runsQ = useRuns(ctx)
  const jobs = (jobsQ.data && jobsQ.data.jobs) || []
  const runs = (runsQ.data && runsQ.data.runs) || []

  // 「高级」筛选：默认收起，展开后改动立即生效（和 demo 一致）。
  // 字段和「设置」页共用 FilterFields —— 同一个东西不该两处长得不一样。
  const qc = useQueryClient()
  const [advOpen, setAdvOpen] = React.useState(false)
  // 「更多岗位」折叠 —— 默认只显示分数最高的 5 条。
  const [showAllJobs, setShowAllJobs] = React.useState(false)
  const [local, setLocal] = React.useState(settings)

  // **后端已按 score 倒序**（ORDER BY score DESC），
  // 但这里再排一次 —— 前端不能假设后端的顺序。
  //
  // **注意位置** —— 必须在 `showAllJobs` 声明之后，
  // 否则 const 的暂时性死区会直接抛
  // 「Cannot access 'showAllJobs' before initialization」（整页白屏）。
  const ranked = jobs.slice().sort((a, b) => (b.score || 0) - (a.score || 0))
  const TOP_N = 5
  const PER_TYPE = 3

  // **同类型只推最高分前 3** ——
  //
  // 用户诉求：「同一类型岗位只推最高分前 3 项」。
  //
  // ## 后端做了什么
  //
  // `plugin_api.list_jobs` 把超额的岗位**排到最后**并打了
  // `_over_type_limit` 标记（类型判定在 `matcher.job_type_key`）。
  //
  // ## 前端还要再做一次
  //
  // **后端的「排到最后」不够** —— 折叠区默认只显示前 TOP_N 条，
  // 而前 TOP_N 条**可能全是同类型**（比如 5 条跨境电商运营）。
  //
  // → 前端再按类型去重：**每类最多 PER_TYPE 条**，
  //   剩下的进「更多岗位」。
  //
  // **为什么在前端做** —— 折叠/展开是**纯前端行为**，
  // 后端不知道用户是不是在看折叠区。
  const seenTypes = {}
  const deduped = []
  const overflow = []
  for (const j of ranked) {
    const key = (j && j.type_key) || ''
    if (!key) { deduped.push(j); continue }   // 没有类型 → 不参与去重
    const n = seenTypes[key] || 0
    seenTypes[key] = n + 1
    if (n < PER_TYPE) deduped.push(j)
    else overflow.push(j)
  }
  const topJobs = showAllJobs ? ranked : deduped.slice(0, TOP_N)
  const restCount = Math.max(0, (showAllJobs ? ranked.length : deduped.length) - TOP_N)
  // **同类型折叠掉的条数** —— 告诉用户「还有 N 条同类型的在下面」
  const dupCount = overflow.length
  React.useEffect(() => { setLocal(settings) }, [settings])
  const save = useMutation({
    mutationFn: async (next) => ctx.rest('/settings', { method: 'POST', body: { settings: next } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['job-radar', 'config'] }),
    onError: (e) => host.notify({ kind: 'error', message: String(e && e.message || e) }),
  })
  const set = (k, v) => {
    const next = { ...local, [k]: v }
    setLocal(next)
    save.mutate(next)
  }

  return jsxs(Fragment, {
    children: [
      jsx(Panel, {
        title: '今日候选',
        hint: jobsQ.isLoading ? '加载中…' : ('命中 ' + jobs.length + ' 条'),
        actions: jsx(Button, {
          size: 'sm',
          variant: 'outline',
          onClick: () => setAdvOpen((v) => !v),
          children: advOpen ? '收起' : '高级',
        }),
        bodyClass: 'p-0',
        // children 必须放在 props 里 —— jsx(type, props, key) 的第三个参数是 key
        children: jsxs('div', { children: [
          advOpen && jsxs('div', {
            className: 'border-b border-(--ui-stroke-tertiary) px-4 py-3',
            children: [
              jsx('div', { className: 'mb-2 text-[0.6875rem] text-(--ui-text-tertiary)',
                children: '筛选条件 · 改动立即生效' }),
              jsx(FilterFields, { local, set }),
            ],
          }),
          jobsQ.isLoading
            ? jsx(GlyphSpinner, { className: 'p-6' })
            : jobsQ.isError
              ? jsx(ErrorState, { message: String(jobsQ.error) })
              : jobs.length === 0
                ? jsx(EmptyState, { title: '还没有岗位', description: '跑一次抓取就会出现' })
                : jsxs('div', { children: [
                    topJobs.map((j, i) => jsx(JobCard, { job: j, ctx }, j.job_id || i)),
                    // 其余的折叠起来 —— 「更多岗位」
                    restCount > 0 && jsx('div', {
                      className: 'border-t border-(--ui-stroke-tertiary) px-4 py-2',
                      children: jsxs('div', {
                        className: 'flex flex-wrap items-center gap-2',
                        children: [
                          jsx(Button, {
                            size: 'sm',
                            variant: 'outline',
                            onClick: () => setShowAllJobs((v) => !v),
                            children: showAllJobs
                              ? '收起（只显示前 ' + TOP_N + ' 条）'
                              : '更多岗位（还有 ' + restCount + ' 条）',
                          }),
                          // **同类型折叠了多少条** ——
                          //
                          // 用户诉求：「同一类型岗位只推最高分前 3 项」。
                          // → 要**看得见**折叠了多少，不然用户以为只有这几条。
                          !showAllJobs && dupCount > 0
                            ? jsx('span', {
                                className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
                                children: '（同类只保留前 ' + PER_TYPE
                                  + ' 条，另有 ' + dupCount + ' 条同类已折叠）',
                              })
                            : null,
                        ],
                      }),
                    }),
                  ] }),
        ] }),
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

/* 投递开关用的站点名。
 *
 * **注意跟 SITE_META 的键不一样**：登录态体检用的是 `zhipin`
 * （招聘站自己的域名），但岗位记录里的 source 是 `boss`
 * （抓取层用的名字）。投递按岗位的 source 判，所以这里要用 `boss`。
 * 两个表别混。
 */
const APPLY_SITE_META = {
  zhaopin: { label: '智联招聘' },
  boss: { label: 'BOSS直聘' },
  huibo: { label: '汇博招聘网' },
}

/* 招聘站登录入口 —— 跟 backend 的 browser_session.LOGIN_URLS 对应。 */
const BROWSER_LOGIN_SITES = {
  zhaopin: { label: '智联招聘' },
  boss: { label: 'BOSS直聘' },
}


/** mock 模式状态 —— 开发时一眼看到「现在跑的是假数据」。 */
function useMock(ctx) {
  return useQuery({
    queryKey: ['job-radar', 'mock-status'],
    queryFn: async () => ctx.rest('/mock/status'),
  })
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

/** 各站的投递开关与每日上限（投递三道门的第一、三道）。 */
// 智联城市码表（城市名 → jl 码）。
//
// **用户不该看到「南宁 = 3150」这种天书** ——
// 所以前端给城市名，抓取时后端翻译成码。
function useCities(ctx) {
  return useQuery({
    queryKey: ['job-radar', 'cities'],
    queryFn: async () => ctx.rest('/cities'),
    staleTime: 600000,
  })
}

function useApplySwitches(ctx) {
  return useQuery({
    queryKey: ['job-radar', 'apply-switches'],
    queryFn: async () => ctx.rest('/apply/switches'),
  })
}

/* 投递开关面板 —— 第一道门（站点开关）+ 第三道门（每日上限）。
 *
 * **开关默认全关**，这是设计：投递不可逆，得用户自己显式打开。
 * 开关开着不代表能投 —— 中间还有一次性令牌（第二道门），
 * 那道门在「投递简历」弹层里，点完确认才会签发。
 */
function ApplySwitchPanel({ ctx }) {
  const qc = useQueryClient()
  const q = useApplySwitches(ctx)
  const save = useMutation({
    mutationFn: async (payload) =>
      ctx.rest('/apply/switches', { method: 'POST', body: payload }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job-radar', 'apply-switches'] })
      host.notify({ kind: 'success', message: '投递设置已保存' })
    },
    onError: (e) => host.notify({ kind: 'error', message: String((e && e.message) || e) }),
  })

  const data = q.data || {}
  const sites = data.sites || {}
  const order = data.known_sites || Object.keys(sites)

  if (q.isLoading) return jsx(GlyphSpinner, { className: 'p-4' })

  return jsxs('div', { className: 'flex flex-col gap-2', children:
    order.map((site) => {
      const meta = APPLY_SITE_META[site] || { label: site }
      const info = sites[site] || { apply_enabled: false, daily_limit: 0 }
      const on = !!info.apply_enabled
      return jsxs('div', {
        key: site,
        className: 'flex items-center gap-3 rounded-md border border-(--ui-stroke-tertiary) px-3 py-2',
        children: [
          jsxs('div', { className: 'min-w-0 flex-1', children: [
            jsx('div', { className: 'text-sm font-medium', children: meta.label }),
            jsx('div', { className: 'mt-1 text-xs text-(--ui-text-tertiary)',
              children: on
                ? '已允许投递 · 每日上限 ' + (info.daily_limit ?? 0) + ' 份'
                : '未开启投递（默认关闭）' }),
          ]}),
          jsx('label', {
            className: 'flex items-center gap-1.5 text-xs text-(--ui-text-secondary)',
            children: [
              jsx('input', {
                type: 'number',
                min: 0,
                value: String(info.daily_limit ?? 0),
                disabled: !on,
                onChange: (e) => save.mutate({
                  site,
                  daily_limit: Number(e.target.value) || 0,
                }),
                className: 'w-14 rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor) px-1.5 py-0.5 text-xs disabled:opacity-50',
              }),
              jsx('span', { children: '份/天' }),
            ],
          }),
          jsx('input', {
            type: 'checkbox',
            style: { accentColor: 'var(--ui-accent)' },
            checked: on,
            disabled: save.isPending,
            onChange: (e) => save.mutate({ site, enabled: e.target.checked }),
            className: 'h-3.5 w-3.5',
          }),
        ],
      })
    })
  })
}

/* 招聘站登录面板 —— 登录态只在浏览器里，插件不碰密码。
 *
 * 点「登录智联招聘」→ 弹出插件专用的浏览器 → 用户在里面正常登录 →
 * cookie 持久化到磁盘，之后抓取和投递都复用它。
 *
 * **不接管用户的日常 Chrome** —— 那个默认不开调试端口，
 * 开了 Chrome 还会弹「远程调试」警告。
 */
function LoginPanel({ ctx }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['job-radar', 'browser-status'],
    queryFn: async () => ctx.rest('/browser/status'),
    refetchInterval: 15000,
  })
  const open = useMutation({
    mutationFn: async (site) =>
      ctx.rest('/browser/login', { method: 'POST', body: { site } }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['job-radar', 'browser-status'] })
      host.notify({
        kind: 'success',
        message: (r && r.detail) || '已打开登录页，在弹出的浏览器里登录即可',
      })
    },
    onError: (e) => host.notify({ kind: 'error', message: String((e && e.message) || e) }),
  })

  const data = q.data || {}
  const loggedIn = data.logged_in || {}
  const alive = data.cdp_alive
  const rows = Object.keys(BROWSER_LOGIN_SITES).map((site) => {
    const meta = BROWSER_LOGIN_SITES[site]
    const on = !!loggedIn[site]
    return jsxs('div', {
      key: site,
      className: 'flex items-center gap-3 rounded-md border border-(--ui-stroke-tertiary) px-3 py-2',
      children: [
        jsx('span', {
          className: cn('text-xs font-semibold',
            on ? 'text-(--ui-green)' : 'text-(--ui-text-tertiary)'),
          children: on ? '✓' : '·',
        }),
        jsxs('div', { className: 'min-w-0 flex-1', children: [
          jsx('div', { className: 'text-sm font-medium', children: meta.label }),
          jsx('div', { className: 'mt-1 text-xs text-(--ui-text-tertiary)',
            children: on ? '已登录' : '未登录（登录后一直有效，不用反复登）' }),
        ]}),
        jsx('button', {
          type: 'button',
          disabled: open.isPending,
          onClick: () => open.mutate(site),
          className: cn('rounded-md border border-(--ui-stroke-tertiary) px-2.5 py-1',
            'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-elevated)',
            'disabled:opacity-50'),
          children: on ? '重新登录' : '登录',
        }),
      ],
    })
  })

  const banner = !alive ? jsx('div', {
    className: 'mb-3 rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) px-3 py-2 text-[0.6875rem] text-(--ui-text-secondary)',
    children: '招聘站浏览器没在跑 —— 点下面的「登录」会自动拉起一个专用浏览器（只在这一个里登录，不碰你日常的 Chrome）',
  }) : null

  return jsxs('div', { className: 'flex flex-col gap-2', children:
    [banner].concat(rows)
  })
}

function PlatformView({ ctx, cfg }) {
  const loginQ = useLogin(ctx)
  const sites = (loginQ.data && loginQ.data.sites) || []
  const summary = (loginQ.data && loginQ.data.summary) || {}
  const settings = (cfg && cfg.settings) || {}
  const [showLogs, setShowLogs] = React.useState(false)
  const logsQ = useLogs(ctx, showLogs)
  const mockQ = useMock(ctx)
  const mockOn = mockQ.data && mockQ.data.mock && mockQ.data.mock.enabled

  return jsxs(Fragment, {
    children: [
      // 开发模式的横幅 —— 一眼看到现在跑的是真数据还是假数据
      mockOn ? jsx('div', {
        className: 'mb-3 flex items-center gap-2 rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) px-3 py-2 text-[0.6875rem] text-(--ui-text-secondary)',
        children: [
          jsx('span', { className: 'font-medium', children: '开发模式' }),
          jsx('span', { className: 'text-(--ui-text-tertiary)',
            children: '投递闸门、经历、模板转换现在用的是 mock 数据' }),
          jsx('button', {
            type: 'button',
            onClick: async () => {
              await ctx.rest('/mock/reset', { method: 'POST' })
              mockQ.refetch()
              host.notify({ kind: 'success', message: 'mock 状态已重置' })
            },
            className: 'ml-auto rounded border border-(--ui-stroke-tertiary) px-2 py-0.5 text-[0.625rem]',
            children: '重置',
          }),
        ],
      }) : null,
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
                className: 'flex items-center gap-3 rounded-md border border-(--ui-stroke-tertiary) px-3 py-2',
                children: [
                  jsx('span', {
                    className: cn('text-xs font-semibold',
                      s.status === 'ok' ? 'text-(--ui-green)' :
                      s.status === 'expiring' ? 'text-(--ui-orange)' : 'text-(--ui-text-tertiary)'),
                    children: s.status === 'ok' ? '✓' : s.status === 'expiring' ? '!' : '·',
                  }),
                  jsxs('div', { className: 'min-w-0 flex-1', children: [
                    jsx('div', { className: 'text-sm font-medium', children: s.label }),
                    jsx('div', { className: 'mt-1 text-xs text-(--ui-text-tertiary)', children: s.detail }),
                    s.hint ? jsx('div', {
                      className: 'mt-1 text-xs text-(--ui-orange)',
                      children: s.hint,
                    }) : null,
                  ]}),
                ],
              })),
            }),
      }),

      // 招聘站登录 —— 最重要，放首位（没登录态后面全白搭）
      jsx(Panel, {
        title: '招聘站登录',
        hint: '登录一次就长期有效，不用反复登',
        children: jsx(LoginPanel, { ctx }),
      }),

      // 投递开关 —— 三道门的第一道（站点开关）+ 第三道（每日上限）
      jsx(Panel, {
        title: '投递开关',
        hint: '默认全关。打开后仍需在「投递简历」里逐次确认。',
        children: jsx(ApplySwitchPanel, { ctx }),
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
                  className: 'max-h-80 overflow-auto rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-3 text-[0.6875rem] leading-relaxed',
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

/* 推送内容 —— 定时与推送的设置。
 *
 * **次要设置收进「高级」按钮**（模块标题栏右上角，默认折叠）——
 * 这是 UI 约定：日报模块顺序是「今日日报 → 推送内容」，
 * 最重要的内容放首位。
 */
function PushSettingsPanel({ ctx, cfg }) {
  const qc = useQueryClient()
  const settings = (cfg && cfg.settings) || {}
  const [advOpen, setAdvOpen] = React.useState(false)
  const save = useMutation({
    mutationFn: async (next) =>
      ctx.rest('/settings', { method: 'POST', body: { settings: next } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job-radar', 'config'] })
      host.notify({ kind: 'success', message: '推送设置已保存' })
    },
    onError: (e) => host.notify({ kind: 'error', message: String((e && e.message) || e) }),
  })

  const set = (k, v) => save.mutate({ ...settings, [k]: v })

  const row = (title, desc, control) => jsxs('div', {
    className: 'flex items-start gap-3',
    children: [
      jsxs('div', { className: 'min-w-0 flex-1', children: [
        jsx('div', { className: 'text-sm font-medium', children: title }),
        desc ? jsx('div', { className: 'mt-1 text-[0.6875rem] leading-relaxed text-(--ui-text-tertiary)',
          children: desc }) : null,
      ]}),
      control,
    ],
  })

  const toggle = (key) => jsx('input', {
    type: 'checkbox',
    style: { accentColor: 'var(--ui-accent)' },
    checked: settings[key] !== false,
    disabled: save.isPending,
    onChange: (e) => set(key, e.target.checked),
    className: 'mt-1 h-3.5 w-3.5 shrink-0',
  })

  const rounds = settings.rounds_per_day ?? 4
  const pushMax = settings.push_max ?? 3

  return jsx(Panel, {
    title: '推送内容',
    hint: '每条 = 一份岗位，名称 + 城市 + 链接',
    actions: jsx('button', {
      type: 'button',
      onClick: () => setAdvOpen((v) => !v),
      className: cn(
        'rounded-md border px-2.5 py-1 text-[0.6875rem]',
        advOpen
          ? 'border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) text-(--ui-text-primary)'
          : 'border-(--ui-stroke-tertiary) text-(--ui-text-secondary) hover:bg-(--ui-bg-elevated)'),
      children: advOpen ? '收起' : '高级',
    }),
    children: jsxs('div', { className: 'flex flex-col gap-3', children: [
      jsx('div', { className: 'text-[0.6875rem] leading-relaxed text-(--ui-text-secondary)',
        children: '每天 ' + rounds + ' 次自动抓取并推送；每次最多 ' + pushMax + ' 条。' +
          (settings.push_new_only !== false ? '只推当天新出现的岗位。' : '每次都会推最高分的几条。') }),
      advOpen ? jsxs('div', { className: 'flex flex-col gap-3 border-t border-(--ui-stroke-tertiary) pt-3', children: [
        row('自动抓取并推送', '当前：每 ' + rounds + ' 小时一次',
          toggle('notify_on_failure')),
        row('只推当天新岗位', '老岗位不重复推。关掉则每次推最高分的几条',
          toggle('push_new_only')),
        row('每次最多推几条', '条',
          jsx(Input, {
            type: 'number',
            min: 1,
            value: String(pushMax),
            disabled: save.isPending,
            onChange: (e) => set('push_max', Number(e.target.value) || 0),
            className: 'w-20',
          })),
        row('每天抓取次数', '次',
          jsx(Input, {
            type: 'number',
            min: 1,
            value: String(rounds),
            disabled: save.isPending,
            onChange: (e) => set('rounds_per_day', Number(e.target.value) || 0),
            className: 'w-20',
          })),
        row('失败也通知', '抓不到数据时告诉你原因，而不是静默',
          toggle('notify_on_failure')),
      ]}) : null,
    ]}),
  })
}

function ReportView({ ctx, cfg }) {
  const q = useQuery({
    queryKey: ['job-radar', 'report'],
    queryFn: async () => ctx.rest('/report'),
    refetchInterval: 60000,
  })
  const md = (q.data && q.data.markdown) || ''

  return jsxs('div', { className: 'flex flex-col gap-4', children: [
    jsx(Panel, {
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
    }),
    jsx(PushSettingsPanel, { ctx, cfg }),
  ]})
}

// ── 设置 ────────────────────────────────────────────────────────────────────

function SettingsView({ ctx, cfg }) {
  const qc = useQueryClient()
  const settings = (cfg && cfg.settings) || {}
  const [local, setLocal] = React.useState(settings)
  React.useEffect(() => { setLocal(settings) }, [settings])

  // **按当前画像重排岗位** ——
  // 改了方向/技能/城市之后，没被抓到的老岗位分数还是旧的
  // （`upsert` 只在被重新抓到时更新分数）→ 老岗位会挤在前面。
  const rescore = useMutation({
    mutationFn: async () => ctx.rest('/rescore', { method: 'POST' }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['job-radar', 'jobs'] })
      host.notify({
        kind: 'success',
        message: '已按当前画像重排 ' + ((r && r.rescored) || 0) + ' 条岗位',
      })
    },
    onError: (e) => host.notify({ kind: 'error', message: String(e && e.message || e) }),
  })

  const save = useMutation({
    mutationFn: async (next) => ctx.rest('/settings', { method: 'POST', body: { settings: next } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job-radar', 'config'] })
      host.notify({ kind: 'success', message: '设置已保存' })
    },
    onError: (e) => host.notify({ kind: 'error', message: String(e && e.message || e) }),
  })

  const set = (k, v) => setLocal((s) => ({ ...s, [k]: v }))

  // **没关键词 = 抓不到任何东西** ——
  // `tools.scan` 直接中止（「没有配置关键词」）。
  // 不提示的话，用户点了「抓取」只看到没结果，不知道原因。
  const noKeywords = !(local.keywords || []).length

  return jsxs(Fragment, {
    children: [
      noKeywords ? jsxs('div', {
        className: 'rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-3',
        children: [
          jsx('div', {
            className: 'text-sm font-medium',
            children: '还没有搜索关键词 —— 没有它抓不到任何岗位',
          }),
          jsx('div', {
            className: 'mt-1 text-[0.6875rem] leading-relaxed text-(--ui-text-tertiary)',
            children: '填岗位名里的词，比如「跨境电商运营」「结构设计工程师」。' +
              '一个关键词会按每个城市各抓一遍。',
          }),
        ],
      }) : null,
      noKeywords ? jsx('div', { className: 'h-3' }) : null,
      jsx(Panel, {
        title: '筛选条件',
        hint: '改动立即生效',
        actions: jsx(Button, {
          size: 'sm',
          variant: 'default',
          disabled: save.isPending,
          onClick: () => save.mutate(local),
          children: save.isPending ? '保存中…' : '保存',
        }),
        children: jsx(FilterFields, {
          local,
          set,
        }),
      }),
      jsx('div', { className: 'h-3' }),
      jsx(Panel, {
        title: '抓取城市',
        hint: (local.cities && local.cities.length)
          ? ('已选 ' + local.cities.length + ' 个：' + local.cities.join('、'))
          : '没选 = 按插件默认城市',
        actions: jsxs('div', { className: 'flex items-center gap-2', children: [
          jsx(Button, {
            size: 'sm',
            variant: 'outline',
            disabled: rescore.isPending,
            onClick: () => rescore.mutate(),
            children: rescore.isPending ? '重排中…' : '按当前画像重排岗位',
          }),
          jsx(Button, {
            size: 'sm',
            variant: 'default',
            disabled: save.isPending,
            onClick: () => save.mutate(local),
            children: save.isPending ? '保存中…' : '保存',
          }),
        ] }),
        children: jsxs('div', { className: 'flex flex-col gap-2', children: [
          jsx('div', {
            className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
            children: '选想看的城市。每个城市都会单独抓一遍 —— ' +
              '智联一次只认一个城市，逗号分隔会静默变成全国。',
          }),
          jsx(CityPicker, {
            ctx,
            value: local.cities || [],
            onChange: (v) => set('cities', v),
          }),
        ] }),
      }),
    ],
  })
}

/* 抓取城市 —— 给用户**城市名**，不给人「南宁 = 3150」这种天书。
 *
 * 智联的 --city 只认一个码，逗号分隔会静默退化成全国，
 * 所以这里是**多选**，后端逐个城市抓。
 *
 * 「热门」是常用城市（实测有岗位的），「全部」是完整码表。 */
function CityPicker({ ctx, value, onChange }) {
  const citiesQ = useCities(ctx)
  const all = (citiesQ.data && citiesQ.data.cities) || []
  const list = Array.isArray(value) ? value : []
  const [showAll, setShowAll] = React.useState(false)

  // **只列码表里有的城市** —— 不然点了选不上（后端认不出）。
  const HOT = ['广州', '深圳', '杭州', '上海', '北京', '重庆', '南宁',
               '桂林', '南京', '东莞', '珠海', '江门', '泉州', '海口',
               '柳州', '北海', '常州', '徐州', '宁波']
  const shown = showAll ? all : all.filter((c) => HOT.includes(c.name))

  const toggle = (name) => {
    onChange(list.includes(name)
      ? list.filter((x) => x !== name)
      : [...list, name])
  }

  if (citiesQ.isLoading) return jsx(GlyphSpinner, { className: 'p-3' })
  if (citiesQ.isError) return jsx(ErrorState, { message: String(citiesQ.error) })

  return jsxs('div', { className: 'flex flex-col gap-2', children: [
    jsxs('div', { className: 'flex flex-wrap gap-1.5', children:
      shown.map((c) => jsx('button', {
        key: c.name,
        type: 'button',
        className: cn(
          'rounded-full border px-2.5 py-0.5 text-xs',
          list.includes(c.name)
            ? 'border-(--ui-accent) text-(--ui-text-primary)'
            : 'border-(--ui-stroke-tertiary) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'),
        onClick: () => toggle(c.name),
        children: c.name,
      })) }),
    jsxs('div', { className: 'flex items-center gap-2', children: [
      jsx('button', {
        type: 'button',
        className: 'text-[0.6875rem] text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
        onClick: () => setShowAll((v) => !v),
        children: showAll ? '只看热门城市' : '看全部城市（' + all.length + '）',
      }),
      list.length > 0 && jsx('button', {
        type: 'button',
        className: 'text-[0.6875rem] text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
        onClick: () => onChange([]),
        children: '清空',
      }),
    ] }),
  ] })
}

/* 筛选条件的字段组 —— 「设置」页和「今日候选 ▸ 高级」共用一套，
 * 免得同一个东西两处长得不一样（之前就是这么对不上的）。 */
function FilterFields({ local, set }) {
  return jsxs('div', {
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
            jsx(Field, {
              label: '抓取站点',
              hint: '两个站各用各的城市码，勾哪个就抓哪个',
              wide: true,
              children: jsx(SitePicker, {
                value: local.sites || ['zhaopin'],
                onChange: (v) => set('sites', v),
              }),
            }),
    ],
  })
}

/* 抓取站点 —— 智联 / BOSS 多选。
 *
 * **为什么要有这个** —— BOSS 接入前只有一个站，写死在配置里就够。
 * 现在两个站各有各的城市码（智联 3~4 位 jl、BOSS 9 位 city），
 * 用户要能自己勾「只抓智联」还是「两个都抓」。
 *
 * **不能一个都不选** —— `args.get("sites") or cfg["sites"]` 会把空列表
 * 兜回配置值（见 skill 里「别靠传空列表阻止网络调用」那条）。
 * 所以这里**至少留一个**，默认智联。 */
const FETCH_SITE_META = {
  zhaopin: { label: '智联招聘' },
  boss: { label: 'BOSS直聘' },
}

function SitePicker({ value, onChange }) {
  const list = Array.isArray(value) && value.length ? value : ['zhaopin']
  const toggle = (name) => {
    const next = list.includes(name)
      ? list.filter((x) => x !== name)
      : [...list, name]
    // **至少留一个** —— 全不选会被后端兜回配置值，看起来像「没生效」
    if (!next.length) return
    onChange(next)
  }
  return jsxs('div', { className: 'flex flex-wrap gap-1.5', children:
    Object.keys(FETCH_SITE_META).map((site) => {
      const on = list.includes(site)
      return jsx('button', {
        key: site,
        type: 'button',
        className: cn(
          'rounded-full border px-2.5 py-0.5 text-xs',
          on
            ? 'border-(--ui-accent) text-(--ui-text-primary)'
            : 'border-(--ui-stroke-tertiary) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'),
        onClick: () => toggle(site),
        children: FETCH_SITE_META[site].label,
      })
    }) })
}

// ── 主视图 ──────────────────────────────────────────────────────────────────

function SettingsPage({ ctx }) {
  const cfgQ = useConfig(ctx)
  const cfg = cfgQ.data

  // **Hook 必须在条件 return 之前调用** —— React 规则。
  // 之前 useState 写在下面 loading/error 的 return 之后：
  //   首次渲染 isLoading=true → 提前 return → useState 没执行
  //   → 数据到了再渲染 → Hook 数量变了 → 标签栏状态错乱
  //   → 表现就是「只有个人信息模块，标签栏不出现」
  const [tab, setTab] = React.useState('profile')

  const tabs = [
    { id: 'profile', label: '个人信息' },
    { id: 'recommend', label: '岗位推荐' },
    { id: 'resume', label: '用户简历' },
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

  const body = {
    profile: jsx(ProfileView, { ctx, cfg }),
    recommend: jsx(RecommendView, { ctx, cfg }),
    resume: jsx(ResumeView, { ctx, cfg }),
    platform: jsx(PlatformView, { ctx, cfg }),
    report: jsx(ReportView, { ctx }),
  }[tab]

  // **不要设 h-full / overflow-y-auto** ——
  // app 的 SettingsContent 已经是 `h-full min-h-0 overflow-y-auto` 的滚动容器，
  // 外层 OverlayMain 是 `flex flex-col overflow-hidden`（高度确定）。
  // 这里再套一层 h-full + overflow-y-auto 会变成**嵌套滚动**：
  // 内层高度 = 外层高度，内容超出被内层裁掉，而外层因为内容没超出
  // **不出现滚动条** → 面板内容显示不全。
  // 根容器只要自然高度，滚动交给 app。
  return jsxs('div', {
    className: 'mx-auto flex w-full max-w-3xl flex-col gap-4',
    children: [
      jsxs('div', { className: 'flex flex-col gap-3', children: [
        jsxs('div', { children: [
          jsx('h1', { className: 'text-lg font-semibold', children: '好岗好找' }),
          jsx('p', {
            className: 'mt-1 text-xs text-(--ui-text-tertiary)',
            children: '定时抓取招聘网站岗位，按个人画像打分，生成日报并推送到 QQ',
          }),
        ]}),
        // 标签栏独占一行 —— 放在标题右侧时会被页面上沿裁掉，
        // 而且一行放不下 5 个标签。
        // **children 必须写在 props 里** ——
        // jsx(type, props, key) 的第三个参数是 key，不是 children！
        // 写成 jsx('div', {...}, child) 会把 child 当成 key，
        // 结果 div 根本没有 children → 标签栏**根本不渲染**。
        jsx('div', {
          className: 'flex flex-wrap items-center gap-2',
          children: jsx(Segmented, { tabs, active: tab, onChange: setTab }),
        }),
      ]}),
      body,
    ],
  })
}

// 自实现的分段控件 —— SDK 只导出 Tabs/TabsList/TabsTrigger，没有 TabsContent，
// 自己渲染内容区更省事，也避免引用未导出的组件。
function Segmented({ tabs, active, onChange }) {
  return jsx('div', {
    className: 'inline-flex gap-1 rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-1',
    children: tabs.map((t) => jsx('button', {
      key: t.id,
      type: 'button',
      onClick: () => onChange(t.id),
      className: cn(
        'rounded-md px-3 py-1 text-xs font-medium transition-colors',
        active === t.id
          ? 'bg-(--ui-bg-editor) text-(--ui-text-primary) shadow-sm'
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
function ResumeView({ ctx, cfg }) {
  const tplQ = useQuery({
    queryKey: ['job-radar', 'templates'],
    queryFn: async () => ctx.rest('/templates'),
  })
  const resQ = useQuery({
    queryKey: ['job-radar', 'resumes'],
    queryFn: async () => ctx.rest('/resume/list'),
  })
  const qc = useQueryClient()
  const [picked, setPicked] = React.useState(['classic', 'modern'])
  const [helpOpen, setHelpOpen] = React.useState(false)

  const settings = (cfg && cfg.settings) || {}
  const saveSettings = useMutation({
    mutationFn: async (next) =>
      ctx.rest('/settings', { method: 'POST', body: { settings: next } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job-radar', 'config'] })
      host.notify({ kind: 'success', message: '设置已保存' })
    },
    onError: (e) => host.notify({ kind: 'error', message: String((e && e.message) || e) }),
  })

  const templates = (tplQ.data && tplQ.data.templates) || []
  const resumes = (resQ.data && resQ.data.resumes) || []

  const toggle = (id) => setPicked((prev) =>
    prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])

  // ── 上传模板 ──
  //
  // **转换在本机完成，文件不离开这台电脑**（后端是本地规则解析，不调大模型）。
  //
  // `uploadTplRef` / `converting` / `onPickTemplate` 之前是未定义的 ——
  // 代码从 demo 转过来时抄漏了，切到这个标签就会 ReferenceError 崩掉。
  const uploadTplRef = React.useRef(null)
  // **文件夹选择**要用**另一个** input ——
  // 普通 `type=file` 选文件夹浏览器会报错。
  // 带 `webkitdirectory` 的才能选整个目录。
  const uploadDirRef = React.useRef(null)
  const [converting, setConverting] = React.useState(false)
  const [convertMsg, setConvertMsg] = React.useState('')
  // **预览哪个模板** —— 用户反馈「无法预览所转换模板的样子」
  const [previewTpl, setPreviewTpl] = React.useState(null)
  // **待确认的转换结果** —— 先转换+预览，用户点「加入模板库」才落盘
  const [pendingItems, setPendingItems] = React.useState([])
  // **正在编辑槽位的模板** ——
  //
  // 用户反馈：「模板库没有编辑槽位的功能」——
  // 之前只在**预览弹窗**里放了个按钮，要点两层才看得到。
  // → **模板库卡片上直接开编辑器**（不用先预览）。
  const [slotTpl, setSlotTpl] = React.useState(null)
  const [slotData, setSlotData] = React.useState(null)
  const [committing, setCommitting] = React.useState(false)

  // 单个文件 → base64
  //
  // 用 FileReader 读 —— 手写 btoa(String.fromCharCode(...))
  // 在大文件上会爆栈（展开参数过多）。
  const readBase64 = (file) => new Promise((resolve, reject) => {
    const fr = new FileReader()
    fr.onload = () => {
      const s = String(fr.result || '')
      // 去掉 data: URL 前缀
      resolve(s.indexOf(',') >= 0 ? s.slice(s.indexOf(',') + 1) : s)
    }
    fr.onerror = () => reject(new Error('读取文件失败'))
    fr.readAsDataURL(file)
  })

  // **先转换 + 预览，不落盘** —— 用户确认后才真正加入模板库。
  //
  // 用户反馈：「没有点击简历模板转换按钮，也无法预览所转换模板的样子」。
  //
  // **dry_run** —— 后端只转换、返回 CSS 片段和渲染好的 HTML，
  // **不写磁盘**。用户点「加入模板库」才真落盘。
  // → 用户点「取消」不会留下一堆垃圾模板。
  const convertOne = async (file) => {
    try {
      const data_base64 = await readBase64(file)
      const r = await ctx.rest('/templates/convert', {
        method: 'POST',
        body: { filename: file.name, data_base64, dry_run: true },
      })
      if (!r || r.ok === false) {
        return { ok: false, name: file.name, error: (r && r.error) || '转换失败' }
      }
      return {
        ok: true,
        name: (r.template && r.template.name) || file.name,
        filename: file.name,
        data_base64,
        extracted: r.extracted || [],
        note: r.note || '',
        html: r.html_preview || '',
        template_id: (r.template && r.template.template_id) || '',
      }
    } catch (err) {
      return { ok: false, name: file.name, error: String((err && err.message) || err) }
    }
  }

  // **真的加入模板库** —— 把 dry_run 转成正式落盘
  const commitOne = async (item) => {
    try {
      const r = await ctx.rest('/templates/convert', {
        method: 'POST',
        body: {
          filename: item.filename,
          data_base64: item.data_base64,
          name: item.name,
        },
      })
      if (!r || r.ok === false) {
        return { ok: false, name: item.name, error: (r && r.error) || '加入失败' }
      }
      return { ok: true, name: item.name }
    } catch (err) {
      return { ok: false, name: item.name, error: String((err && err.message) || err) }
    }
  }

  // **支持多文件** —— 单个文件和整个文件夹都能传
  //
  // 用户会直接选「简历模板」文件夹（里面有 .doc/.pdf 一堆）。
  // 选文件夹要用**另一个** input（带 webkitdirectory）——
  // 普通 file input 选文件夹会报错。
  const onPickTemplate = async (e) => {
    const files = Array.from((e.target.files) || [])
    e.target.value = ''            // 允许重复选同一个文件
    if (!files.length) return

    setConverting(true)
    setConvertMsg(files.length === 1
      ? '正在转换 ' + files[0].name + ' …'
      : '正在转换 ' + files.length + ' 个文件 …')

    const results = []
    for (const f of files) {
      results.push(await convertOne(f))
    }

    const okList = results.filter((r) => r.ok)
    const badList = results.filter((r) => !r.ok)

    // **成功的先摆着，等用户确认** ——
    // 「转换并加入模板库」是这个流程的名字：
    // **转换 → 预览 → 确认加入**。
    // 之前是「选完文件直接落盘」—— 用户既看不到预览，也没法取消。
    if (okList.length) {
      setPendingItems(okList)
    }

    const parts = []
    if (okList.length) {
      parts.push('已转换 ' + okList.length + ' 个，**预览确认后**加入模板库')
      const ex = okList[0].extracted
      if (ex && ex.length) parts.push('（识别到：' + ex.join('、') + '）')
    }
    if (badList.length) {
      parts.push('失败 ' + badList.length + ' 个：'
        + badList.map((r) => r.name + '（' + (r.error || '未知错误') + '）').join('；'))
    }
    setConvertMsg(parts.join('  ') || '没有可转换的文件')
    setConverting(false)
  }

  // **确认加入模板库** —— 把待确认的逐个真落盘
  const commitPending = async () => {
    if (!pendingItems.length) return
    setCommitting(true)
    setConvertMsg('正在加入模板库 …')
    const done = []
    const failed = []
    for (const item of pendingItems) {
      const r = await commitOne(item)
      if (r.ok) done.push(r.name)
      else failed.push(r.name + '（' + r.error + '）')
    }
    setPendingItems([])
    setCommitting(false)
    const parts = []
    if (done.length) parts.push('已加入模板库 ' + done.length + ' 个：' + done.join('、'))
    if (failed.length) parts.push('失败：' + failed.join('；'))
    setConvertMsg(parts.join('  ') || '没有加入任何模板')
    if (done.length) {
      qc.invalidateQueries({ queryKey: ['job-radar', 'templates'] })
    }
  }

  // **打开槽位编辑器** ——
  //
  // **先拉一次槽位** —— 没有槽位的模板（内置的 / docx 的）不显示编辑入口。
  // 拉不到就提示一句，不弹空编辑器。
  const openSlotEditor = async (tpl) => {
    try {
      const r = await ctx.rest('/templates/slots?template_id=' + encodeURIComponent(tpl.template_id))
      if (!r || r.ok === false || !r.has_slots) {
        setConvertMsg('这个模板没有槽位（只有 PDF 转换来的模板有）')
        return
      }
      setSlotData(r)
      setSlotTpl(tpl)
    } catch (e) {
      setConvertMsg(String((e && e.message) || e))
    }
  }

  // 删掉一个上传的模板（内置模板不给删）
  const onDeleteTemplate = async (tpl) => {
    if (!tpl || !tpl.template_id) return
    if (tpl.builtin || tpl.format === 'builtin') {
      setConvertMsg('内置模板不能删')
      return
    }
    setConverting(true)
    setConvertMsg('正在删除 ' + (tpl.name || '') + ' …')
    try {
      const r = await ctx.rest('/templates/delete', {
        method: 'POST',
        body: { template_id: tpl.template_id },
      })
      if (!r || r.ok === false) {
        setConvertMsg((r && r.error) || '删除失败')
        return
      }
      setConvertMsg('已删除：' + (tpl.name || tpl.template_id))
      qc.invalidateQueries({ queryKey: ['job-radar', 'templates'] })
    } catch (err) {
      setConvertMsg(String((err && err.message) || err))
    } finally {
      setConverting(false)
    }
  }

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
              ? 'border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated)'
              : 'border-(--ui-stroke-tertiary) hover:bg-(--ui-bg-elevated)'
          ),
          title: '上传模板说明',
          children: '?',
        }),
      ]}),
      children: jsxs('div', { className: 'flex flex-col gap-3', children: [
        helpOpen && jsx('div', {
          className: 'rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-3 text-xs leading-relaxed text-(--ui-text-secondary)',
          children: jsxs('div', { children: [
            jsx('b', { children: '上传自己的模板' }),
            jsx('span', { children: '：在模板库右下角点「＋ 上传模板」，选一个 ' }),
            jsx('b', { children: 'Word（.docx）' }),
            jsx('span', { children: '、' }),
            jsx('b', { children: 'PDF' }),
            jsx('span', { children: ' 或 ' }),
            jsx('b', { children: '图片（.png / .jpg）' }),
            jsx('span', { children: '，会自动转换并弹出预览 —— 看着对了再点「加入模板库」。' }),
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
            // **预览** —— 看看这个模板渲染成什么样
            onPreview: () => setPreviewTpl(tpl),
            // **编辑槽位** —— 只有上传的模板有槽位（PDF 转换来的）
            onEditSlots: (tpl.builtin || tpl.format === 'builtin')
              ? null
              : () => openSlotEditor(tpl),
            // 只有上传的模板能删
            onDelete: (tpl.builtin || tpl.format === 'builtin')
              ? null
              : () => onDeleteTemplate(tpl),
          })).concat([
            jsx('button', {
              key: '__upload',
              type: 'button',
              onClick: () => uploadTplRef.current && uploadTplRef.current.click(),
              className: 'flex min-h-32 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-(--ui-stroke-tertiary) p-4 text-xs text-(--ui-text-tertiary) transition-colors hover:border-(--ui-stroke-tertiary) hover:text-(--ui-text-secondary)',
              children: [
                jsx('span', { className: 'text-lg', children: '＋' }),
                jsx('span', { children: converting ? '转换中…' : '上传模板' }),
              ],
            }),
            // **上传文件夹** ——
            //
            // 选目录要用**带 webkitdirectory 的 input**（另一个）——
            // 普通 file input 选文件夹浏览器会报错。
            jsx('button', {
              key: '__upload_dir',
              type: 'button',
              onClick: () => uploadDirRef.current && uploadDirRef.current.click(),
              className: 'flex min-h-32 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-(--ui-stroke-tertiary) p-4 text-xs text-(--ui-text-tertiary) transition-colors hover:border-(--ui-stroke-tertiary) hover:text-(--ui-text-secondary)',
              children: [
                jsx('span', { className: 'text-lg', children: '📁' }),
                jsx('span', { children: converting ? '转换中…' : '上传文件夹' }),
              ],
            }),
          ])
        }),
      ]}),
    }),

    // 隐藏的文件选择框 —— 「＋ 上传模板」格子点它
    jsx('input', {
      ref: uploadTplRef,
      type: 'file',
      // **.doc 也要能选** —— 用户有 Word 存成 .doc 的模板。
      // （后端按文件头判断真实格式，.doc 里装 docx 也能转）
      accept: '.docx,.doc,.pdf,.png,.jpg,.jpeg,.webp',
      className: 'hidden',
      onChange: onPickTemplate,
    }),

    // **文件夹选择**（另一个 input）——
    //
    // **不能用 accept 过滤** —— 带 accept 时选目录会把文件全过滤掉。
    // `webkitdirectory` 让浏览器返回目录里**所有**文件。
    // React 不认识这个属性，要用 ref 手动 setAttribute。
    jsx('input', {
      ref: (el) => {
        uploadDirRef.current = el
        if (el && !el.getAttribute('webkitdirectory')) {
          el.setAttribute('webkitdirectory', '')
          el.setAttribute('directory', '')
        }
      },
      type: 'file',
      multiple: true,
      className: 'hidden',
      onChange: onPickTemplate,
    }),

    convertMsg ? jsx('div', {
      className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
      children: convertMsg,
    }) : null,

    // ── 智能选模板 ──
    jsx(Panel, {
      title: '智能选模板',
      children: jsxs('div', { className: 'flex flex-col gap-3', children: [
        jsxs('div', { className: 'flex items-start gap-3', children: [
          jsx('div', { className: 'min-w-0 flex-1', children: [
            jsx('div', { className: 'text-sm font-medium', children: '由 Agent 按 JD 自行推荐模板' }),
            jsx('div', { className: 'mt-1 text-[0.6875rem] leading-relaxed text-(--ui-text-tertiary)',
              children: '开启后，生成简历时会先读一遍 JD，再挑最合适的版式：要求简洁就选经典单栏，技能项多就选现代双栏，看重技术深度就选技术极客。你随时能在生成结果里手动换回去。' }),
          ]}),
          jsx('input', {
            type: 'checkbox',
            style: { accentColor: 'var(--ui-accent)' },
            checked: settings.smart_template !== false,
            disabled: saveSettings.isPending,
            onChange: (e) => saveSettings.mutate({ ...settings, smart_template: e.target.checked }),
            className: 'mt-1 h-3.5 w-3.5 shrink-0',
          }),
        ]}),
        jsxs('div', { className: 'flex items-start gap-3', children: [
          jsx('div', { className: 'min-w-0 flex-1', children: [
            jsx('div', { className: 'text-sm font-medium', children: '只在你勾选的模板里挑' }),
            jsx('div', { className: 'mt-1 text-[0.6875rem] leading-relaxed text-(--ui-text-tertiary)',
              children: '勾上后，Agent 只能从上面选中的模板里推荐（可多选）。一个都没勾时，它会在全部模板里自己选。' }),
          ]}),
          jsx('input', {
            type: 'checkbox',
            style: { accentColor: 'var(--ui-accent)' },
            checked: Array.isArray(settings.template_allow) && settings.template_allow.length > 0,
            disabled: saveSettings.isPending,
            onChange: (e) => saveSettings.mutate({
              ...settings,
              template_allow: e.target.checked ? picked : [],
            }),
            className: 'mt-1 h-3.5 w-3.5 shrink-0',
          }),
        ]}),
      ]}),
    }),

    // ── 用户简历 ──
    jsx(Panel, {
      title: '用户简历',
      hint: '投递成功的简历会自动存进这里并打标签',
      children: resumes.length
        ? jsxs('div', { className: 'flex flex-col divide-y divide-y [&>*+*]:border-t [&>*+*]:border-(--ui-stroke-tertiary)', children:
            resumes.map((r) => jsx(ResumeRow, { resume: r }, r.resume_id))
          })
        : jsx(EmptyState, {
            title: '还没有简历档案',
            description: '在「岗位推荐」里对某个岗位做「简历匹配优化」并投递成功后，简历会自动存到这里。',
          }),
    }),

    // ── 模板预览 ──
    previewTpl ? jsx(TemplatePreviewDialog, {
      tpl: previewTpl,
      ctx,
      onClose: () => setPreviewTpl(null),
    }) : null,

    // ── 槽位编辑器 ──
    //
    // **直接挂在页面上**（不是预览弹窗里）——
    // 用户反馈「模板库没有编辑槽位的功能」→ 要在模板库这一层就能进。
    slotTpl && slotData ? jsxs('div', {
      className: 'fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-6',
      onClick: () => { setSlotTpl(null); setSlotData(null) },
      children: jsx('div', {
        className: 'w-full max-w-5xl',
        onClick: (e) => e.stopPropagation(),
        children: jsx(SlotEditor, {
          templateId: slotTpl.template_id,
          slots: slotData.edit || { name: null, fields: [], sections: [] },
          roles: slotData.roles || [],
          ctx,
          onSaved: () => {
            setSlotTpl(null)
            setSlotData(null)
            setConvertMsg('槽位已保存')
            qc.invalidateQueries({ queryKey: ['job-radar', 'templates'] })
          },
          onCancel: () => { setSlotTpl(null); setSlotData(null) },
        }),
      }),
    }) : null,

    // ── 转换结果待确认 ──
    pendingItems.length ? jsx(ConvertConfirmDialog, {
      items: pendingItems,
      committing,
      onCommit: commitPending,
      onClose: () => setPendingItems([]),
    }) : null,
  ]})
}

/** 转换结果确认弹窗 —— 「转换并加入模板库」的下一步。
 *
 * 用户反馈：「没有点击简历模板转换按钮，也无法预览所转换模板的样子」。
 *
 * 流程改成：**选文件 → 转换（不落盘）→ 预览 → 点「加入模板库」才落盘**。
 * → 用户能看清版式对不对，也能取消（不留垃圾模板）。
 *
 * 多个文件时用标签页切换。
 */
function ConvertConfirmDialog({ items, committing, onCommit, onClose }) {
  const [idx, setIdx] = React.useState(0)
  const cur = items[Math.min(idx, items.length - 1)] || {}
  return jsx('div', {
    className: cn(
      'fixed inset-0 z-50 flex items-center justify-center',
      'bg-black/55 p-6'
    ),
    onClick: onClose,
    children: jsxs('div', {
      className: cn(
        'flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden',
        'rounded-xl border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor)'
      ),
      onClick: (e) => e.stopPropagation(),
      children: [
        jsxs('div', {
          className: 'flex items-center justify-between border-b border-(--ui-stroke-tertiary) px-4 py-3',
          children: [
            jsxs('div', { children: [
              jsx('div', { className: 'text-sm font-medium', children: '转换结果预览' }),
              jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: cur.name || '' }),
            ]}),
            jsx('button', {
              type: 'button',
              onClick: onClose,
              className: 'text-xs text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
              children: '取消',
            }),
          ],
        }),
        jsxs('div', { className: 'flex flex-col gap-3 overflow-auto p-4', children: [
          // 多个文件时切换
          items.length > 1
            ? jsxs('div', { className: 'flex flex-wrap gap-1.5', children:
                items.map((it, i) => jsx('button', {
                  key: it.template_id || i,
                  type: 'button',
                  onClick: () => setIdx(i),
                  className: cn(
                    'rounded-full border px-2.5 py-0.5 text-xs',
                    i === idx
                      ? 'border-(--ui-accent) text-(--ui-text-primary)'
                      : 'border-(--ui-stroke-tertiary) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'),
                  children: it.name,
                })) })
            : null,
          // 识别到了什么
          (cur.extracted && cur.extracted.length)
            ? jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: '识别到：' + cur.extracted.join('、') })
            : null,
          cur.note
            ? jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: cur.note })
            : null,
          // **预览本体**
          jsx('div', {
            className: cn(
              'overflow-auto rounded-md border border-(--ui-stroke-tertiary)',
              'bg-white p-6'
            ),
            dangerouslySetInnerHTML: { __html: cur.html || '' },
          }),
          jsxs('div', { className: 'flex justify-end gap-2', children: [
            jsx('button', {
              type: 'button',
              onClick: onClose,
              className: 'rounded-md border border-(--ui-stroke-tertiary) px-3 py-1.5 text-xs text-(--ui-text-secondary) hover:bg-(--ui-bg-elevated)',
              children: '取消',
            }),
            jsx('button', {
              type: 'button',
              disabled: committing,
              onClick: onCommit,
              className: cn(
                'rounded-md border border-(--ui-accent) px-3 py-1.5 text-xs',
                'text-(--ui-text-primary) disabled:opacity-50'),
              children: committing
                ? '加入中…'
                : ('加入模板库' + (items.length > 1 ? '（' + items.length + ' 个）' : '')),
            }),
          ]}),
        ]}),
      ],
    }),
  })
}

/** 模板预览弹窗 —— 看看这个模板渲染成什么样。
 *
 * 用户反馈：「没有点击简历模板转换按钮，也无法预览所转换模板的样子」。
 *
 * 上传的模板转换完只登记一条记录（名字 + CSS 片段），
 * **看不到渲染成什么样** → 不知道版式对不对、能不能用。
 *
 * 内容全部来自**用户自己的画像和经历** —— 不编造。
 * 渲染方式跟「简历匹配优化」弹窗一致（dangerouslySetInnerHTML + 白底）。
 */
function TemplatePreviewDialog({ tpl, ctx, onClose }) {
  const [state, setState] = React.useState({ phase: 'loading' })
  // **切到槽位编辑器** —— 用户说「这段认错了」时改。
  const [editing, setEditing] = React.useState(false)
  const [slots, setSlots] = React.useState(null)

  React.useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const r = await ctx.rest('/templates/preview', {
          method: 'POST',
          body: { template_id: tpl.template_id },
        })
        if (!alive) return
        if (!r || r.ok === false) {
          setState({ phase: 'error', error: (r && r.error) || '预览失败' })
          return
        }
        setState({ phase: 'done', html: r.html })
      } catch (e) {
        if (alive) setState({ phase: 'error', error: String((e && e.message) || e) })
      }
    })()
    return () => { alive = false }
  }, [tpl.template_id, ctx])

  // **拉一次槽位** —— 「编辑槽位」按钮要知道有没有槽位可编辑。
  //
  // **PDF 模板才有槽位**（内置模板没有 spec.json）→ 返回 has_slots=false
  // → 按钮不显示，不给用户一个点进去是空的入口。
  const loadSlots = async () => {
    try {
      const r = await ctx.rest('/templates/slots?template_id=' + encodeURIComponent(tpl.template_id))
      if (r && r.ok && r.has_slots) {
        setSlots(r)
        setEditing(true)
      } else {
        setState({ phase: 'done', html: state.html })
      }
    } catch (e) {
      setState({ phase: 'done', html: state.html })
    }
  }

  return jsx('div', {
    className: cn(
      'fixed inset-0 z-50 flex items-center justify-center',
      'bg-black/55 p-6'
    ),
    onClick: onClose,
    children: jsxs('div', {
      className: cn(
        'flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden',
        'rounded-xl border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor)'
      ),
      onClick: (e) => e.stopPropagation(),
      children: [
        jsxs('div', {
          className: 'flex items-center justify-between border-b border-(--ui-stroke-tertiary) px-4 py-3',
          children: [
            jsxs('div', { children: [
              jsx('div', { className: 'text-sm font-medium', children: '模板预览' }),
              jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: tpl.name || '' }),
            ]}),
            jsx('button', {
              type: 'button',
              onClick: onClose,
              className: 'text-xs text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
              children: '关闭',
            }),
          ],
        }),
        jsxs('div', { className: 'flex flex-col gap-3 overflow-auto p-4', children: [
          state.phase === 'loading'
            ? jsx('div', { className: 'py-8 text-center text-xs text-(--ui-text-tertiary)', children: '正在渲染…' })
            : null,
          state.phase === 'error'
            ? jsx('div', { className: 'rounded-md border border-(--ui-stroke-tertiary) p-3 text-xs text-(--ui-text-secondary)', children: state.error })
            : null,
          state.phase === 'done'
            ? jsx('div', {
                className: cn(
                  'overflow-auto rounded-md border border-(--ui-stroke-tertiary)',
                  'bg-white p-6'
                ),
                dangerouslySetInnerHTML: { __html: state.html || '' },
              })
            : null,
        ]}),
        // **槽位编辑器** —— 覆盖在预览上面。
        //
        // 编辑器自己渲染一份预览（右栏）→ 不用两层叠。
        editing && slots ? jsx(SlotEditor, {
          templateId: tpl.template_id,
          slots: slots.edit || { name: null, fields: [], sections: [] },
          roles: slots.roles || [],
          ctx,
          onSaved: () => { setEditing(false) },
          onCancel: () => { setEditing(false) },
        }) : null,
      ],
    }),
  })
}


/**
 * 槽位编辑器 —— 半自动地把模板的「示例内容」对应到个人信息。
 *
 * ## 为什么需要它
 *
 * 模板转换时会**猜**每个文字块是什么（姓名 / 联系方式 / 章节标题 / 正文）。
 * 猜**必然有错的时候** —— 「电话：1388888888」是联系方式还是正文？
 * 「意向城市：珠海」算页眉字段还是求职意向章节？
 *
 * 猜错 → 内容填错位置 → 简历不对，**但用户不知道错在哪**。
 *
 * → 让用户**点一下「这段是什么」**，改完存进模板。**一次确认，永久复用。**
 *
 * ## 交互
 *
 * 左边是槽位列表（姓名 / 联系方式 / 章节），右边是预览。
 * 改左边 → 右边立刻重渲染（走 `/templates/slots`）。
 *
 * ## 为什么用受控输入而不是 window.prompt
 *
 * `window.prompt` 在 Electron 里**静默无效**（本项目踩过）——
 * 点了没反应，用户以为功能坏了。
 * → 一律用内联受控输入。
 */
function SlotEditor({ templateId, slots, roles, ctx, onSaved, onCancel }) {
  const [edit, setEdit] = React.useState(slots || { name: null, fields: [], sections: [] })
  const [html, setHtml] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [msg, setMsg] = React.useState('')

  // **改了就重新渲染** —— 每改一下就调一次后端。
  //
  // 为什么不在前端拼 HTML —— 骨架是后端生成的（章节类型转换、
  // 字段标签映射都在后端），前端拼会分家。
  React.useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const r = await ctx.rest('/templates/slots', {
          method: 'POST',
          body: { template_id: templateId, edit },
        })
        if (!alive) return
        if (!r || r.ok === false) {
          setMsg((r && r.error) || '保存失败')
          return
        }
        setHtml(r.html || '')
        setMsg('')
      } catch (e) {
        if (alive) setMsg(String((e && e.message) || e))
      }
    })()
    return () => { alive = false }
  }, [templateId, JSON.stringify(edit)])

  const setName = (patch) => setEdit((old) => ({
    ...old,
    name: old.name ? { ...old.name, ...patch } : patch,
  }))

  const setField = (i, patch) => setEdit((old) => {
    const fields = (old.fields || []).slice()
    fields[i] = { ...fields[i], ...patch }
    return { ...old, fields }
  })

  const removeField = (i) => setEdit((old) => {
    const fields = (old.fields || []).slice()
    fields.splice(i, 1)
    return { ...old, fields }
  })

  const setSection = (i, patch) => setEdit((old) => {
    const sections = (old.sections || []).slice()
    sections[i] = { ...sections[i], ...patch }
    return { ...old, sections }
  })

  const removeSection = (i) => setEdit((old) => {
    const sections = (old.sections || []).slice()
    sections.splice(i, 1)
    return { ...old, sections }
  })

  const addSection = () => setEdit((old) => ({
    ...old,
    sections: (old.sections || []).concat([{ title: '新章节', kind: 'paragraph' }]),
  }))

  return jsxs('div', {
    className: cn('flex max-h-[80vh] w-full max-w-5xl flex-col overflow-hidden',
      'rounded-xl border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor)'),
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between border-b border-(--ui-stroke-tertiary) px-4 py-3',
        children: [
          jsxs('div', { children: [
            jsx('div', { className: 'text-sm font-medium', children: '编辑模板槽位' }),
            jsx('div', {
              className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
              children: '左边改槽位，右边实时预览。改完点「保存槽位」。',
            }),
          ]}),
          jsx('button', {
            type: 'button',
            onClick: onCancel,
            className: 'text-xs text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
            children: '关闭',
          }),
        ],
      }),
      jsxs('div', {
        className: 'grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-4 overflow-hidden p-4',
        children: [
          // ── 左：槽位列表 ──
          jsxs('div', {
            className: 'flex min-h-0 flex-col gap-3 overflow-auto pr-1',
            children: [
              // 姓名
              jsxs('div', {
                className: 'rounded-md border border-(--ui-stroke-tertiary) p-3',
                children: [
                  jsx('div', { className: 'mb-2 text-xs font-medium text-(--ui-text-secondary)', children: '姓名' }),
                  jsx(Input, {
                    value: (edit.name && edit.name.text) || '',
                    placeholder: '模板里的姓名（不填就不显示）',
                    onChange: (e) => setName({ text: e && e.target ? e.target.value : '' }),
                  }),
                ],
              }),
              // 联系方式
              jsxs('div', {
                className: 'rounded-md border border-(--ui-stroke-tertiary) p-3',
                children: [
                  jsx('div', { className: 'mb-2 text-xs font-medium text-(--ui-text-secondary)', children: '联系方式' }),
                  (edit.fields || []).length === 0
                    ? jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: '没识别到联系方式字段' })
                    : null,
                  ...(edit.fields || []).map((f, i) => jsxs('div', {
                    key: 'f' + i,
                    className: 'mb-2 flex items-center gap-1.5',
                    children: [
                      jsx(Input, {
                        className: 'w-20 shrink-0',
                        value: f.label || '',
                        placeholder: '标签',
                        onChange: (e) => setField(i, { label: e && e.target ? e.target.value : '' }),
                      }),
                      jsx(Input, {
                        className: 'min-w-0 flex-1',
                        value: f.value || '',
                        placeholder: '示例值',
                        onChange: (e) => setField(i, { value: e && e.target ? e.target.value : '' }),
                      }),
                      jsx('button', {
                        type: 'button',
                        onClick: () => removeField(i),
                        title: '删掉这个字段',
                        className: 'shrink-0 rounded px-1.5 text-xs text-(--ui-text-tertiary) hover:text-(--ui-red)',
                        children: '×',
                      }),
                    ],
                  })),
                ],
              }),
              // 章节
              jsxs('div', {
                className: 'rounded-md border border-(--ui-stroke-tertiary) p-3',
                children: [
                  jsxs('div', {
                    className: 'mb-2 flex items-center justify-between',
                    children: [
                      jsx('div', { className: 'text-xs font-medium text-(--ui-text-secondary)', children: '章节' }),
                      jsx('button', {
                        type: 'button',
                        onClick: addSection,
                        className: 'rounded border border-(--ui-stroke-tertiary) px-1.5 py-0.5 text-[0.625rem] text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
                        children: '＋ 加一个',
                      }),
                    ],
                  }),
                  ...(edit.sections || []).map((sc, i) => jsxs('div', {
                    key: 's' + i,
                    className: 'mb-2 flex items-center gap-1.5',
                    children: [
                      jsx(Input, {
                        className: 'min-w-0 flex-1',
                        value: sc.title || '',
                        placeholder: '章节标题',
                        onChange: (e) => setSection(i, { title: e && e.target ? e.target.value : '' }),
                      }),
                      jsx('select', {
                        className: 'shrink-0 rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor) px-1.5 py-1 text-xs',
                        value: sc.kind || 'paragraph',
                        onChange: (e) => setSection(i, { kind: e && e.target ? e.target.value : 'paragraph' }),
                        children: [
                          jsx('option', { key: 'p', value: 'paragraph', children: '段落' }),
                          jsx('option', { key: 'l', value: 'list', children: '列表' }),
                          jsx('option', { key: 'e', value: 'entry', children: '条目' }),
                          jsx('option', { key: 't', value: 'tags', children: '标签' }),
                        ],
                      }),
                      jsx('button', {
                        type: 'button',
                        onClick: () => removeSection(i),
                        title: '删掉这个章节',
                        className: 'shrink-0 rounded px-1.5 text-xs text-(--ui-text-tertiary) hover:text-(--ui-red)',
                        children: '×',
                      }),
                    ],
                  })),
                ],
              }),
            ],
          }),
          // ── 右：实时预览 ──
          jsxs('div', {
            className: 'flex min-h-0 flex-col gap-2',
            children: [
              jsx('div', {
                className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
                children: msg ? ('⚠ ' + msg) : '实时预览',
              }),
              jsx('div', {
                className: cn('min-h-0 flex-1 overflow-auto rounded-md border border-(--ui-stroke-tertiary)',
                  'bg-white p-6'),
                dangerouslySetInnerHTML: { __html: html || '' },
              }),
            ],
          }),
        ],
      }),
      jsxs('div', {
        className: 'flex items-center justify-end gap-2 border-t border-(--ui-stroke-tertiary) px-4 py-3',
        children: [
          jsx('button', {
            type: 'button',
            onClick: onCancel,
            className: 'rounded px-3 py-1.5 text-xs text-(--ui-text-tertiary) hover:text-(--ui-text-primary)',
            children: '取消',
          }),
          jsx('button', {
            type: 'button',
            disabled: busy,
            onClick: () => { setBusy(true); onSaved && onSaved(); setBusy(false) },
            className: cn('rounded-md border border-(--ui-accent) px-3 py-1.5 text-xs',
              'text-(--ui-text-primary) disabled:opacity-50'),
            children: busy ? '保存中…' : '保存槽位',
          }),
        ],
      }),
    ],
  })
}

/** 模板卡 —— 内置模板画一个迷你预览缩略图，上传模板用文件名。 */
function TemplateCard({ tpl, active, onToggle, onDelete, onPreview, onEditSlots }) {
  const builtin = tpl.builtin || tpl.format === 'builtin'
  // **外层是 div 不是 button** —— 上传的模板要在角上放「删除」按钮，
  // button 里套 button 是非法 HTML，浏览器会拆掉结构导致点击错位。
  return jsxs('div', {
    className: cn(
      'group relative flex flex-col overflow-hidden rounded-lg border text-left transition-colors',
      active
        ? 'border-(--ui-stroke-tertiary) ring-1 ring-(--ui-stroke-tertiary)'
        : 'border-(--ui-stroke-tertiary) hover:border-(--ui-stroke-tertiary)'
    ),
    children: [
      jsx('button', {
        type: 'button',
        onClick: onToggle,
        className: cn(
          'relative flex h-24 w-full items-center justify-center bg-(--ui-bg-elevated)',
          !active && 'opacity-60'
        ),
        children: [
          builtin
            ? jsx('div', {
                className: 'w-16 rounded-sm border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor) p-1.5',
                children: [
                  jsx('div', { className: 'h-1.5 w-8 rounded-sm bg-(--ui-bg-editor) opacity-70' }),
                  jsx('div', { className: 'mt-1 h-1 w-full rounded-sm bg-(--ui-stroke-tertiary)' }),
                  jsx('div', { className: 'mt-1 h-1 rounded-sm bg-(--ui-stroke-tertiary)', style: { width: '50%' } }),
                  jsx('div', { className: 'mt-1.5 h-1 w-full rounded-sm bg-(--ui-stroke-tertiary)' }),
                  jsx('div', { className: 'mt-1 h-1 rounded-sm bg-(--ui-stroke-tertiary)', style: { width: '50%' } }),
                ],
              })
            // **兜底** —— 后端漏字段时前端会整页崩（不是卡片不好看）
            : jsx('div', {
              className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
              children: String(tpl.format || 'html').toUpperCase(),
            }),
          jsx('span', {
            className: cn(
              'absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full text-[0.625rem]',
              active
                ? 'bg-(--ui-accent) text-white'
                : 'border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor) text-transparent'
            ),
            children: '✓',
          }),
        ],
      }),
      jsx('button', {
        type: 'button',
        onClick: onToggle,
        className: 'px-2.5 py-2 text-left',
        children: [
          jsx('div', { className: 'text-xs font-medium', children: tpl.name }),
          jsx('div', { className: 'mt-1 text-[0.6875rem] text-(--ui-text-tertiary)', children: tpl.description || '' }),
        ],
      }),
      // **预览按钮** —— 看看这个模板渲染成什么样
      //
      // 用户反馈：「无法预览所转换模板的样子」——
      // 上传的模板转换完只有一条记录（名字 + CSS），
      // **看不到渲染成什么样**，不知道版式对不对、能不能用。
      onPreview ? jsx('button', {
        type: 'button',
        onClick: onPreview,
        title: '预览这个模板',
        className: 'absolute bottom-2 left-2 rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor) px-1.5 py-0.5 text-[0.625rem] text-(--ui-text-tertiary) opacity-0 transition-opacity group-hover:opacity-100 hover:text-(--ui-text-primary)',
        children: '预览',
      }) : null,
      // **「槽位」按钮** —— 直接在卡片上编辑模板的槽位。
      //
      // 用户反馈：「模板库没有编辑槽位的功能」——
      // 之前只放在**预览弹窗**里，要点两层才看得到。
      // → **放到卡片上，hover 就出现**，一眼能看见。
      onEditSlots ? jsx('button', {
        type: 'button',
        onClick: onEditSlots,
        title: '编辑这个模板的槽位（姓名/联系方式/章节）',
        className: 'absolute bottom-2 left-14 rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor) px-1.5 py-0.5 text-[0.625rem] text-(--ui-text-tertiary) opacity-0 transition-opacity group-hover:opacity-100 hover:text-(--ui-text-primary)',
        children: '槽位',
      }) : null,
      // 删除按钮 —— 只有上传的模板能删，内置模板没有
      onDelete ? jsx('button', {
        type: 'button',
        onClick: onDelete,
        title: '删除这个上传的模板',
        className: 'absolute right-1.5 bottom-1.5 flex h-5 w-5 items-center justify-center rounded-full border border-(--ui-stroke-tertiary) bg-(--ui-bg-editor) text-[0.625rem] text-(--ui-text-tertiary) opacity-0 transition-opacity group-hover:opacity-100 hover:text-(--ui-red)',
        children: '×',
      }) : null,
    ],
  })
}

/** 一份简历档案。 */
function ResumeRow({ resume }) {
  const tags = (resume.tags || []).filter(Boolean)
  // 分隔线自己画 —— 容器上的 `divide-(--ui-*)` 任意值类在 app 的 CSS 里不存在
  return jsxs('div', { className: 'flex items-center gap-3 border-t border-(--ui-stroke-tertiary) py-2.5', children: [
    jsxs('div', {
      className: 'flex h-10 w-12 shrink-0 items-center justify-center rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) text-[0.5625rem] text-(--ui-text-tertiary)',
      children: (resume.format || 'pdf').toUpperCase(),
    }),
    jsxs('div', { className: 'min-w-0 flex-1', children: [
      jsx('div', { className: 'truncate text-xs font-medium', children: resume.title }),
      jsx('div', { className: 'mt-1 flex flex-wrap items-center gap-1.5', children:
        tags.map((tg) => jsx(Badge, { variant: 'muted', children: tg }, tg))
      }),
      jsx('div', { className: 'mt-1 text-[0.6875rem] text-(--ui-text-tertiary)', children:
        (resume.source === 'applied' ? '投递生成' : resume.source === 'optimized' ? '匹配优化' : '手动上传')
        + ' · ' + (resume.updated || '').slice(0, 10)
      }),
    ]}),
  ]})
}

export default {
  id: ID,
  name: '好岗好找 Good-job-Ez',
  defaultEnabled: true,
  register(ctx) {
    // 1) Settings ▸ Plugins —— 主入口
    //
    // **不注册 children** ——
    // app 会把 `children` 直接渲染成左侧 rail 里的子项
    // （见 apps/desktop/src/contrib/settings-pages.ts 的 subpagesOf）。
    // 之前注册了 5 个视图的 children，页面上又画了一套标签栏，
    // 结果是**两套一样的导航**：左侧 5 个子项 + 顶部 5 个标签。
    //
    // 现在只留一个入口 —— 插件主页自带标签栏（SettingsPage），
    // 左侧不再重复。主页默认落在「个人信息」。
    if (typeof ctx.registerSettingsPage === 'function') {
      ctx.registerSettingsPage({
        id: 'main',
        title: '好岗好找',
        icon: 'search',
        render: () => jsx(SettingsPage, { ctx }),
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


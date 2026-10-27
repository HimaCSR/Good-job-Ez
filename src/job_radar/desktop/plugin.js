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
    className: 'flex flex-col overflow-hidden rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-primary)',
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
        'rounded-md border border-dashed border-(--ui-stroke-primary) text-[0.625rem] text-(--ui-text-tertiary)',
        photo ? 'border-solid' : 'hover:border-(--ui-stroke-secondary)'
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
        className: 'mt-1.5 rounded-md border border-(--ui-stroke-secondary) px-2 py-1 text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-secondary)',
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
      const r = await ctx.rest('/experiences', { method: 'POST', body: { experience: exp } })
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
            className: 'rounded border border-(--ui-stroke-secondary) px-2 py-0.5 text-[0.625rem] text-(--ui-text-secondary)',
            children: '编辑',
          }),
          jsx('button', {
            type: 'button',
            onClick: () => remove(e.id),
            className: 'rounded border border-(--ui-stroke-secondary) px-2 py-0.5 text-[0.625rem] text-(--ui-text-tertiary)',
            children: '删除',
          }),
        ] }),
      ],
    })
    return jsx('div', {
      key: e.id,
      className: 'border-b border-(--ui-stroke-secondary) py-2.5 last:border-b-0',
      children: head,
    })
  })

  const addBtn = jsx('button', {
    type: 'button',
    onClick: () => setEditing({ id: '', company: '', title: '', start: '', end: '', bullets: [''] }),
    className: 'rounded-md border border-dashed border-(--ui-stroke-primary) px-3 py-1.5 text-[0.6875rem] text-(--ui-text-tertiary) hover:border-(--ui-stroke-secondary)',
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
      className: 'rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-2.5 py-1.5 text-[0.6875rem] text-(--ui-text-tertiary)',
      children: '开发模式：下面显示的是 mock 数据',
    }) : null,
    rows.length ? jsxs('div', {}, rows) : null,
    rows.length ? null : jsx('div', {
      className: 'rounded-md border border-(--ui-stroke-secondary) p-3 text-[0.6875rem] leading-relaxed text-(--ui-text-tertiary)',
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
        className: 'min-h-14 flex-1 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) px-2 py-1 text-xs text-(--ui-text-primary)',
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
    className: 'flex flex-col gap-2.5 rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3',
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
            className: 'self-start rounded border border-(--ui-stroke-secondary) px-2 py-0.5 text-[0.625rem] text-(--ui-text-secondary)',
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
          className: 'rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1 text-[0.6875rem] text-(--ui-text-secondary)',
          children: '取消',
        }),
      ] }),
    ],
  })
}

/* 从简历文档导入 —— 本地规则解析，不走大模型。
 *
 * **文件不离开这台电脑**：读进来就在内存里解析，不落盘、不外传。
 * 解析结果是**草稿**，填进表单后用户自己核对、保存。
 */
function ResumeImportPanel({ ctx, onDraft }) {
  const [file, setFile] = React.useState(null)
  const [status, setStatus] = React.useState('')
  const [busy, setBusy] = React.useState(false)

  const doParse = async () => {
    if (!file) { setStatus('先选一个文件'); return }
    setBusy(true); setStatus('解析中…')
    try {
      const buf = await file.arrayBuffer()
      let binary = ''
      const bytes = new Uint8Array(buf)
      const chunk = 0x8000
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk))
      }
      const r = await ctx.rest('/resume/import', {
        method: 'POST',
        body: { filename: file.name, data_base64: btoa(binary) },
      })
      if (!r || r.ok === false) {
        setStatus((r && r.error) || '解析失败')
        return
      }
      const found = r.found || {}
      const bits = []
      if (found.identity) bits.push('身份 ' + found.identity + ' 项')
      if (found.skills) bits.push('技能 ' + found.skills + ' 个')
      if (found.experiences) bits.push('经历 ' + found.experiences + ' 段')
      setStatus((r.note ? r.note + ' ' : '') + (bits.length ? '已识别：' + bits.join('、') : '没识别出内容'))
      if (r.draft) onDraft && onDraft(r.draft)
    } catch (e) {
      setStatus(String((e && e.message) || e))
    } finally {
      setBusy(false)
    }
  }

  return jsxs('div', { className: 'flex flex-col gap-3', children: [
    jsx('label', {
      className: 'flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-(--ui-stroke-primary) bg-(--ui-bg-secondary) px-4 py-6 text-center hover:bg-(--ui-bg-tertiary)',
      children: [
        jsx('span', { className: 'text-sm text-(--ui-text-primary)',
          children: file ? file.name : '拖入或点击选择简历文件' }),
        jsx('span', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
          children: '支持 .docx / .pdf / .txt · 解析在本机完成，文件不会离开这台电脑' }),
        jsx('input', {
          type: 'file',
          accept: '.docx,.pdf,.txt',
          className: 'hidden',
          onChange: (e) => {
            const f = e.target.files && e.target.files[0]
            setFile(f || null)
            setStatus(f ? '已选：' + f.name : '')
          },
        }),
      ],
    }),
    jsxs('div', { className: 'flex items-center gap-2.5', children: [
      jsx(Button, {
        size: 'sm',
        variant: 'primary',
        disabled: busy || !file,
        onClick: doParse,
        children: busy ? '解析中…' : '识别并填写表单',
      }),
      jsx('span', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
        children: status || '先选一个文件' }),
    ]}),
    jsx('span', { className: 'text-[0.6875rem] leading-relaxed text-(--ui-text-tertiary)',
      children: '识别走的是本地规则解析（按段落结构 + 字段关键词抽取），不调用大模型，避免简历内容被发送出去。解析结果只是一份草稿，确认无误后再点「保存」才写入。' }),
  ]})
}

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

  // 简历解析出来的草稿 → 填进表单
  // **只填空位，不覆盖用户已填的** —— 用户手改过的比机器抽的准。
  const applyDraft = (draft) => {
    setLocal((s) => {
      const next = { ...s }
      if (draft.identity) {
        next.identity = { ...(s.identity || {}) }
        for (const [k, v] of Object.entries(draft.identity)) {
          if (v && !next.identity[k]) next.identity[k] = v
        }
      }
      if (draft.skills && draft.skills.length) {
        const have = new Set(s.skills || [])
        next.skills = [...(s.skills || []), ...draft.skills.filter((x) => !have.has(x))]
      }
      if (draft.cities && draft.cities.length) {
        const have = new Set(s.cities || [])
        next.cities = [...(s.cities || []), ...draft.cities.filter((x) => !have.has(x))]
      }
      if (draft.title_keywords && draft.title_keywords.length) {
        const have = new Set(s.title_keywords || [])
        next.title_keywords = [...(s.title_keywords || []),
          ...draft.title_keywords.filter((x) => !have.has(x))]
      }
      if (draft.min_salary && !s.min_salary) next.min_salary = draft.min_salary
      if (draft.experience_text && !s.experience_text) {
        next.experience_text = draft.experience_text
      }
      return next
    })
  }

  if (!profile || !Object.keys(profile).length) {
    return jsx(ErrorState, { message: '读不到个人画像' })
  }

  return jsxs(Fragment, {
    children: [
      jsx(Panel, {
        title: '从简历文档导入',
        hint: '本地解析，不走大模型',
        children: jsx(ResumeImportPanel, { ctx, onDraft: applyDraft }),
      }),
      jsx('div', { className: 'h-3' }),
      jsx(Panel, {
        title: '身份信息',
        hint: '仅用于简历生成表单',
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
            jsx(Field, {
              label: '最高学历',
              children: jsx('select', {
                className: 'h-8 w-full rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-2 text-sm outline-none focus:border-(--ui-accent)',
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
      jsx('div', { className: 'h-3' }),
      jsx(Panel, {
        title: '结构化经历',
        hint: '公司 / 职位 / 起止 —— 简历「工作经历」章节靠它',
        children: jsx(ExperienceEditor, { ctx }),
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
              'rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1',
              'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-secondary)'
            ),
            onClick: (e) => { e.stopPropagation(); setOptOpen(true) },
            children: '简历匹配优化',
          }),
          jsx('button', {
            type: 'button',
            className: cn(
              'rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1',
              'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-secondary)'
            ),
            onClick: (e) => { e.stopPropagation(); setApplyOpen(true) },
            children: '投递简历',
          }),
          job.url ? jsx('a', {
            href: job.url,
            target: '_blank',
            rel: 'noreferrer',
            className: cn(
              'rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1',
              'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-secondary)'
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
      className: 'rounded bg-(--ui-bg-tertiary) px-1.5 py-0.5 text-[0.625rem] text-(--ui-text-secondary)',
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
          ? 'border-(--ui-stroke-secondary) bg-(--ui-bg-secondary)'
          : 'border-(--ui-stroke-secondary) hover:bg-(--ui-bg-secondary)'
      ),
      children: [main, badge],
    })
  })

  const emptyBox = jsx('div', {
    className: 'rounded-md border border-(--ui-stroke-secondary) p-4 text-xs leading-relaxed',
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
        'rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-bg-primary)'
      ),
      onClick: (e) => e.stopPropagation(),
      children: [
        jsxs('div', {
          className: 'flex items-center justify-between border-b border-(--ui-stroke-secondary) px-4 py-3',
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
            className: 'rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-2.5 text-[0.6875rem] text-(--ui-text-secondary)',
            children: err,
          }) : null,

          // ① 闸门没过
          phase === 'gate' && blocked.length
            ? jsxs('div', {
                className: 'rounded-md border border-(--ui-stroke-secondary) p-3 text-xs leading-relaxed',
                children: [
                  jsx('div', { className: 'mb-2 text-(--ui-text-primary)', children: '现在不能投，卡在这些地方：' }),
                  jsxs('div', { className: 'flex flex-col gap-2', children:
                    blocked.map((b, i) => jsxs('div', {
                      key: i,
                      className: 'rounded border border-(--ui-stroke-secondary) p-2',
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
                  className: 'rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3 text-[0.6875rem] leading-relaxed text-(--ui-text-secondary)',
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
                    className: 'rounded-md border border-(--ui-stroke-secondary) px-3 py-1.5 text-xs text-(--ui-text-secondary)',
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
        'rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-bg-primary)'
      ),
      onClick: (e) => e.stopPropagation(),
      children: [
        jsxs('div', {
          className: 'flex items-center justify-between border-b border-(--ui-stroke-secondary) px-4 py-3',
          children: [
            jsxs('div', { children: [
              jsx('div', { className: 'text-sm font-medium', children: '简历匹配优化' }),
              jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: job.title || '' }),
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
                  : 'border-(--ui-stroke-secondary) text-(--ui-text-secondary)'
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
                className: 'rounded-md border border-(--ui-stroke-secondary) p-3 text-xs',
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
                  'rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1',
                  'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-secondary)'
                ),
                children: state.saved ? '已存进简历档案' : '存进简历档案',
              }),
            ]}),
            jsx('div', {
              className: cn(
                'overflow-auto rounded-md border border-(--ui-stroke-secondary)',
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
  const [local, setLocal] = React.useState(settings)
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
          variant: advOpen ? 'primary' : 'outline',
          onClick: () => setAdvOpen((v) => !v),
          children: advOpen ? '收起' : '高级',
        }),
        bodyClass: 'p-0',
        children: jsxs('div', {}, [
          advOpen && jsxs('div', {
            className: 'border-b border-(--ui-stroke-secondary) px-4 py-3',
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
                : jsxs('div', {}, jobs.map((j, i) => jsx(JobCard, { key: j.job_id || i, job: j, ctx }))),
        ]),
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
        className: 'flex items-center gap-3 rounded-md border border-(--ui-stroke-secondary) px-3 py-2',
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
                className: 'w-14 rounded border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) px-1.5 py-0.5 text-xs disabled:opacity-50',
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
      className: 'flex items-center gap-3 rounded-md border border-(--ui-stroke-secondary) px-3 py-2',
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
          className: cn('rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1',
            'text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--ui-bg-secondary)',
            'disabled:opacity-50'),
          children: on ? '重新登录' : '登录',
        }),
      ],
    })
  })

  const banner = !alive ? jsx('div', {
    className: 'mb-3 rounded-md border border-(--ui-stroke-primary) bg-(--ui-bg-secondary) px-3 py-2 text-[0.6875rem] text-(--ui-text-secondary)',
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
        className: 'mb-3 flex items-center gap-2 rounded-md border border-(--ui-stroke-primary) bg-(--ui-bg-secondary) px-3 py-2 text-[0.6875rem] text-(--ui-text-secondary)',
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
            className: 'ml-auto rounded border border-(--ui-stroke-secondary) px-2 py-0.5 text-[0.625rem]',
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
          ? 'border-(--ui-stroke-primary) bg-(--ui-bg-secondary) text-(--ui-text-primary)'
          : 'border-(--ui-stroke-secondary) text-(--ui-text-secondary) hover:bg-(--ui-bg-secondary)'),
      children: advOpen ? '收起' : '高级',
    }),
    children: jsxs('div', { className: 'flex flex-col gap-3', children: [
      jsx('div', { className: 'text-[0.6875rem] leading-relaxed text-(--ui-text-secondary)',
        children: '每天 ' + rounds + ' 次自动抓取并推送；每次最多 ' + pushMax + ' 条。' +
          (settings.push_new_only !== false ? '只推当天新出现的岗位。' : '每次都会推最高分的几条。') }),
      advOpen ? jsxs('div', { className: 'flex flex-col gap-3 border-t border-(--ui-stroke-secondary) pt-3', children: [
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
        children: jsx(FilterFields, {
          local,
          set,
        }),
      }),
    ],
  })
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
    ],
  })
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
        jsx('div', { className: 'flex flex-wrap items-center gap-2' },
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
          ? 'bg-(--ui-bg-primary) text-(--ui-text-primary) shadow-sm'
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
  const [converting, setConverting] = React.useState(false)
  const [convertMsg, setConvertMsg] = React.useState('')

  const onPickTemplate = async (e) => {
    const file = e.target.files && e.target.files[0]
    e.target.value = ''            // 允许重复选同一个文件
    if (!file) return
    setConverting(true)
    setConvertMsg('正在转换 ' + file.name + ' …')
    try {
      // 用 FileReader 读 base64 —— 手写 btoa(String.fromCharCode(...))
      // 在大文件上会爆栈（展开参数过多）。
      const data_base64 = await new Promise((resolve, reject) => {
        const fr = new FileReader()
        fr.onload = () => {
          const s = String(fr.result || '')
          // 去掉 data: URL 前缀
          resolve(s.indexOf(',') >= 0 ? s.slice(s.indexOf(',') + 1) : s)
        }
        fr.onerror = () => reject(new Error('读取文件失败'))
        fr.readAsDataURL(file)
      })
      const r = await ctx.rest('/templates/convert', {
        method: 'POST',
        body: { filename: file.name, data_base64 },
      })
      if (!r || r.ok === false) {
        setConvertMsg((r && r.error) || '转换失败')
        return
      }
      setConvertMsg('已加入模板库：' + ((r.template && r.template.name) || file.name))
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
              ? 'border-(--ui-stroke-primary) bg-(--ui-bg-secondary)'
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
              onClick: () => uploadTplRef.current && uploadTplRef.current.click(),
              className: 'flex min-h-32 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-(--ui-stroke-primary) p-4 text-xs text-(--ui-text-tertiary) transition-colors hover:border-(--ui-stroke-secondary) hover:text-(--ui-text-secondary)',
              children: [
                jsx('span', { className: 'text-lg', children: '＋' }),
                jsx('span', { children: converting ? '转换中…' : '上传模板' }),
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
      accept: '.docx,.pdf,.png,.jpg,.jpeg,.webp',
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
        ? jsxs('div', { className: 'flex flex-col divide-y divide-y [&>*+*]:border-t [&>*+*]:border-(--ui-stroke-primary)', children:
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
        ? 'border-(--ui-stroke-secondary) ring-1 ring-(--ui-stroke-secondary)'
        : 'border-(--ui-stroke-secondary) hover:border-(--ui-stroke-primary)'
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
                className: 'w-16 rounded-sm border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) p-1.5',
                children: [
                  jsx('div', { className: 'h-1.5 w-8 rounded-sm bg-(--ui-bg-primary) opacity-70' }),
                  jsx('div', { className: 'mt-1 h-1 w-full rounded-sm bg-(--ui-stroke-secondary)' }),
                  jsx('div', { className: 'mt-1 h-1 rounded-sm bg-(--ui-stroke-secondary)', style: { width: '50%' } }),
                  jsx('div', { className: 'mt-1.5 h-1 w-full rounded-sm bg-(--ui-stroke-secondary)' }),
                  jsx('div', { className: 'mt-1 h-1 rounded-sm bg-(--ui-stroke-secondary)', style: { width: '50%' } }),
                ],
              })
            : jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: tpl.format.toUpperCase() }),
          jsx('span', {
            className: cn(
              'absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full text-[0.625rem]',
              active
                ? 'bg-(--ui-accent) text-white'
                : 'border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) text-transparent'
            ),
            children: '✓',
          }),
        ],
      }),
      jsxs('div', { className: 'px-2.5 py-2', children: [
        jsx('div', { className: 'text-xs font-medium', children: tpl.name }),
        jsx('div', { className: 'mt-1 text-[0.6875rem] text-(--ui-text-tertiary)', children: tpl.description || '' }),
      ]}),
    ],
  })
}

/** 一份简历档案。 */
function ResumeRow({ resume }) {
  const tags = (resume.tags || []).filter(Boolean)
  // 分隔线自己画 —— 容器上的 `divide-(--ui-*)` 任意值类在 app 的 CSS 里不存在
  return jsxs('div', { className: 'flex items-center gap-3 border-t border-(--ui-stroke-secondary) py-2.5', children: [
    jsxs('div', {
      className: 'flex h-10 w-12 shrink-0 items-center justify-center rounded border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) text-[0.5625rem] text-(--ui-text-tertiary)',
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


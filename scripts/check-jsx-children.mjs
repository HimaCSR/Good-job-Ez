// 找出 plugin.js 里「children 传到了第三个参数」的误用。
//
// ## 背景
//
//   jsx(type, props, key) —— **第三个参数是 key，不是 children**。
//
//   写成 jsx('div', { ... }, child) 的话，child 变成 key，
//   div 根本没有 children → 那段 UI **根本不渲染**，而且**不报错**。
//
//   本机踩过：标签栏 `jsx('div', {...}, jsx(Segmented, {...}))`
//   → 标签栏从来没出现过；岗位列表 `jsxs('div', {}, jobs.map(...))`
//   → 岗位列表是空的。
//
// ## 为什么用真解析器而不是正则
//
//   判断「这个调用到底有几个参数」很难靠正则：
//   嵌套的 {} [] ()、字符串里的逗号、模板字符串都会骗过它。
//   所以这里让 V8 来切分参数 —— 把源码写成临时 .mjs，
//   import 一个会记录调用的 jsx/jsxs，然后真的执行一遍。
//
// ## 怎么覆盖所有分支
//
//   模块顶层不渲染组件，所以 import 之后还要**逐个调用每个组件**
//   （用几组不同的参数，尽力走到不同分支）。
//
// ## 输出
//
//   报出**原文行号**（临时文件行号减去 stub 占的行数）。

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const SRC = process.argv[2]
if (!SRC) {
  console.error('用法: node check-jsx-children.mjs <plugin.js>')
  process.exit(2)
}

let code = fs.readFileSync(SRC, 'utf8')

// 剥 import
code = code.replace(/^import[\s\S]*?from\s+['"][^'"]+['"];?\s*$/gm, '')
// export default → 普通赋值
code = code.replace(/^export default /m, 'const __default_export = ')
// 其它 export
code = code.replace(/^export\s+/gm, '')

const calls = []

// stub 单独写成文件，避免模板字符串的多层转义
const stub = [
  'const __calls = globalThis.__calls',
  'const __describe = (v) => {',
  "  if (v === null) return 'null'",
  "  if (v === undefined) return 'undefined'",
  "  if (typeof v === 'string') return JSON.stringify(v)",
  "  if (typeof v === 'number' || typeof v === 'boolean') return String(v)",
  "  if (Array.isArray(v)) return '[array ' + v.length + ']'",
  '  if (typeof v === \'object\') {',
  '    if (v && v.type) return \'<\' + (typeof v.type === \'string\' ? v.type : (v.type.name || \'Component\')) + \'>\'',
  "    return '{object}'",
  '  }',
  '  return typeof v',
  '}',
  'const jsx = function (type, props, key) {',
  '  if (arguments.length >= 3 && key !== undefined && key !== null) {',
  "    const stack = new Error().stack || ''",
  '    // 第 1 帧 = jsx 自己，之后才是调用点。',
  '    // 找第一帧行号大于 stub 里 jsx 定义行（25）的。',
  "    const frames = stack.split('\\n').slice(1)",
  '    let rawLine = -1',
  '    for (const fr of frames) {',
  "      const m = fr.match(/jr-jsx-check-([0-9]+)\\.mjs:([0-9]+):([0-9]+)/)",
  '      if (!m) continue',
  '      const ln = parseInt(m[2], 10)',
  '      if (ln > 25) { rawLine = ln; break }',
  '    }',
  '    __calls.push({',
  '      rawLine,',
  '      snippet: __describe(key),',
  '    })',
  '  }',
  "  return { __jsx: 'jsx', type, props, key }",
  '}',
  'const jsxs = jsx',
  "const Fragment = 'Fragment'",
  'const React = {',
  '  createElement: jsx,',
  '  Fragment,',
  '  useState: () => [null, () => {}],',
  '  useEffect: () => {},',
  '  useMemo: () => null,',
  '  useRef: () => ({ current: null }),',
  '  useCallback: (f) => f,',
  '  useContext: () => null,',
  '}',
  'const __noop = () => {}',
  'const __sdk = new Proxy({',
  '  useQuery: () => ({ data: null, isLoading: false, isError: false, error: null }),',
  '  useMutation: () => ({ mutate: __noop, isPending: false }),',
  '  useQueryClient: () => ({ invalidateQueries: __noop }),',
  '  host: { notify: __noop },',
  "  cn: (...a) => a.filter(Boolean).join(' '),",
  '}, { get: (t, k) => (k in t ? t[k] : __noop) })',
  "const Button = 'Button', Input = 'Input', Textarea = 'Textarea', Badge = 'Badge'",
  "const GlyphSpinner = 'GlyphSpinner', EmptyState = 'EmptyState', ErrorState = 'ErrorState'",
  "const ROUTES_AREA = 'routes', SIDEBAR_NAV_AREA = 'sidebar'",
  'const useQuery = __sdk.useQuery, useMutation = __sdk.useMutation',
  'const useQueryClient = __sdk.useQueryClient, host = __sdk.host, cn = __sdk.cn',
  '',
].join('\n')

// 把所有顶层 function 重新导出，这样外部能逐个调用
const fnNames = [...code.matchAll(/^function (\w+)\s*\(/gm)].map((m) => m[1])
const exportLine = fnNames.length ? '\nexport { ' + fnNames.join(', ') + ' }\n' : ''

const tmp = path.join(os.tmpdir(), `jr-jsx-check-${process.pid}.mjs`)
const stubLines = stub.split('\n').length
fs.writeFileSync(tmp, stub + '\n' + code + exportLine, 'utf8')

globalThis.__calls = calls

let mod
try {
  mod = await import(pathToFileURL(tmp).href)
} catch (e) {
  if (!calls.length) {
    console.error('执行失败且没有捕获到调用:', e.message)
    fs.unlinkSync(tmp)
    process.exit(3)
  }
}

// **主动调用每个组件** —— 只 import 的话，函数体里的 jsx 不会执行。
if (mod) {
  const ctx = {
    rest: async () => ({}),
    storage: { get: async () => null, set: async () => {} },
  }
  const cfg = { profile: {}, settings: {}, experiences: [] }
  const argSets = [
    [{ ctx, cfg }],
    [{ ctx }],
    [{ ctx, cfg, onSaved: () => {} }],
    [{ ctx, view: 'profile' }],
    [{ ctx, job: { job_id: '1', title: 'x' }, onClose: () => {} }],
    [{ ctx, resume: { resume_id: '1' }, onClose: () => {} }],
    [{ ctx, exp: { id: '1' }, busy: false, onCancel: () => {}, onSave: () => {} }],
    [{ tpl: { template_id: 'classic' }, active: false, onToggle: () => {} }],
    [{ label: 'x', hint: 'y', children: null }],
    [{ title: 'x', children: null }],
    [{ value: [], onChange: () => {} }],
    [{ tabs: [{ id: 'a', label: 'A' }], active: 'a', onChange: () => {} }],
    [{ children: null }],
    [{ label: 'x', labelContent: null, children: null }],
    [{ text: 'x' }],
  ]
  for (const name of Object.keys(mod)) {
    const fn = mod[name]
    if (typeof fn !== 'function') continue
    for (const args of argSets) {
      try {
        fn(...args)
      } catch {
        // 某个分支缺参数抛错是正常的，继续试下一组
      }
    }
  }
}

fs.unlinkSync(tmp)

if (!calls.length) {
  console.log('✔ 没有发现 children 传到第三个参数的调用')
  process.exit(0)
}

console.log('✘ 这些调用把 children 传到了第三个参数（React 会当成 key，UI 不渲染）：')
const seen = new Set()
for (const c of calls) {
  const line = c.rawLine > 0 ? c.rawLine - stubLines : -1
  const k = line + '|' + c.snippet
  if (seen.has(k)) continue
  seen.add(k)
  console.log(`  L${String(line).padStart(5)}  第三个参数 = ${c.snippet}`)
}
process.exit(1)

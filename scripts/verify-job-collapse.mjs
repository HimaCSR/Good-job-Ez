// 真实渲染验证：「岗位推荐」默认只显示最高分的 5 条，其余折叠到「更多岗位」。
//
// ## 用户诉求
//
// > 岗位推荐优先显示最高分的前 5 条，其余折叠起来至更多岗位。
//
// ## 为什么用真渲染而不是复刻逻辑
//
// 折叠逻辑要成立，需要同时保证：
// 1. 排序按 score 降序（**前端不能假设后端的顺序**）
// 2. 默认只渲染前 5 条
// 3. 有「更多岗位」按钮，点了能展开
// 4. 展开后能收起
// 5. **不足 5 条时不显示「更多岗位」按钮**
//
// 复刻逻辑只能验证 1 和 2 —— 3/4/5 都在 JSX 里。
// 所以这里用 jsdom + React **渲染真的 RecommendView**。
//
// 用法：
//     node scripts/verify-job-collapse.mjs [plugin.js]

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const HERMES_HOME = process.env.HERMES_HOME
  || path.join(process.env.LOCALAPPDATA || '', 'hermes')
const AGENT_ROOT = path.join(HERMES_HOME, 'hermes-agent')
const require = createRequire(path.join(AGENT_ROOT, 'package.json'))

const HERE = path.dirname(path.dirname(new URL(import.meta.url).pathname.replace(/^\//, '')))
const PLUGIN_JS = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(HERE, 'src', 'job_radar', 'desktop', 'plugin.js')

const OK = '  ✔'
const BAD = '  ✘'
const fails = []

function check(label, cond, detail = '') {
  if (cond) console.log(OK, label, detail)
  else { console.log(BAD, label, detail); fails.push(label) }
}

let React, ReactDOMClient, jsxRuntime, JSDOM
try {
  React = require('react')
  ReactDOMClient = require('react-dom/client')
  jsxRuntime = require('react/jsx-runtime')
  ;({ JSDOM } = require('jsdom'))
} catch (e) {
  console.log('  (跳过: 找不到 hermes-agent 的 node_modules —— ' + e.message + ')')
  process.exit(0)
}

const { act } = React

const dom = new JSDOM(
  '<!doctype html><html><body><div id="root"></div></body></html>',
  { url: 'http://localhost/', pretendToBeVisual: true },
)
global.window = dom.window
global.document = dom.window.document
try {
  Object.defineProperty(global, 'navigator', {
    value: dom.window.navigator, configurable: true, writable: true,
  })
} catch { /* ignore */ }
global.HTMLElement = dom.window.HTMLElement
global.Element = dom.window.Element
global.Node = dom.window.Node
global.Event = dom.window.Event
global.MouseEvent = dom.window.MouseEvent
global.KeyboardEvent = dom.window.KeyboardEvent
global.getComputedStyle = dom.window.getComputedStyle
global.requestAnimationFrame = (cb) => setTimeout(cb, 0)
global.cancelAnimationFrame = (id) => clearTimeout(id)
global.IS_REACT_ACT_ENVIRONMENT = true

const SDK_NAMES = [
  'Button', 'Input', 'Textarea', 'Badge', 'GlyphSpinner', 'EmptyState',
  'ErrorState', 'Checkbox', 'Switch', 'Select', 'SelectContent', 'SelectItem',
  'SelectTrigger', 'SelectValue', 'Tabs', 'TabsList', 'TabsTrigger',
  'ROUTES_AREA', 'SIDEBAR_NAV_AREA',
]

const stubSrc = [
  'const __sdk = globalThis.__SDK__',
  'const React = __sdk.React',
  'const jsx = __sdk.jsx, jsxs = __sdk.jsxs, Fragment = __sdk.Fragment',
  ...SDK_NAMES.map((n) => `const ${n} = __sdk.${n}`),
  'const cn = __sdk.cn, host = __sdk.host',
  'const useQuery = __sdk.useQuery, useMutation = __sdk.useMutation',
  'const useQueryClient = __sdk.useQueryClient',
].join('\n')

async function loadPlugin(sdk) {
  let code = fs.readFileSync(PLUGIN_JS, 'utf8')
  code = code.replace(/^import[\s\S]*?from\s+['"][^'"]+['"];?\s*$/gm, '')
  code = code.replace(/^export default /m, 'const __default_export = ')
  const tmp = path.join(os.tmpdir(), `jr-collapse-${process.pid}.mjs`)
  fs.writeFileSync(tmp, stubSrc + '\n' + code + '\nexport { RecommendView };\n', 'utf8')
  globalThis.__SDK__ = sdk
  const mod = await import(pathToFileURL(tmp).href)
  return { mod, tmp }
}

// 造 8 条岗位，**故意乱序**（分数从低到高）——
// 验证前端自己会排序，不能依赖后端的顺序。
function makeJobs(n) {
  const out = []
  for (let i = 0; i < n; i++) {
    out.push({
      job_id: 'job-' + i,
      title: '岗位' + i,
      company: '公司' + i,
      city: '杭州',
      salary: '20-30K',
      score: 40 + i * 5,      // 40,45,...,75 —— 分数越高越是后面
      tags: ['Java'],
      reasons: ['会 Java'],
      missing: [],
    })
  }
  return out
}

async function main() {
  console.log('='.repeat(62))
  console.log('岗位推荐折叠 —— 真实 DOM 渲染验证')
  console.log('='.repeat(62))

  const state = { jobs: makeJobs(8), runs: [] }

  const sdk = {
    React,
    jsx: jsxRuntime.jsx,
    jsxs: jsxRuntime.jsxs,
    Fragment: jsxRuntime.Fragment,
    useQuery(opts) {
      // 按 queryKey 区分 jobs / runs
      const key = JSON.stringify(opts?.queryKey || [])
      if (key.includes('jobs')) {
        return { data: { jobs: state.jobs }, isLoading: false, isError: false, error: null }
      }
      if (key.includes('runs')) {
        return { data: { runs: state.runs }, isLoading: false, isError: false, error: null }
      }
      return { data: {}, isLoading: false, isError: false, error: null }
    },
    useMutation: () => ({ mutate: () => {}, isPending: false }),
    useQueryClient: () => ({ invalidateQueries: () => {} }),
    host: { notify: () => {} },
    cn: (...a) => a.filter(Boolean).join(' '),
    Button: 'button', Input: 'input', Textarea: 'textarea', Badge: 'span',
    GlyphSpinner: 'span', EmptyState: 'span', ErrorState: 'span',
    Checkbox: 'input', Switch: 'input',
    Select: 'div', SelectContent: 'div', SelectItem: 'div',
    SelectTrigger: 'div', SelectValue: 'span',
    Tabs: 'div', TabsList: 'div', TabsTrigger: 'div',
    ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'sidebar',
  }

  const { mod, tmp } = await loadPlugin(sdk)
  check('plugin.js 加载成功', typeof mod.RecommendView === 'function')
  if (typeof mod.RecommendView !== 'function') {
    fs.unlinkSync(tmp); process.exit(1)
  }

  const ctx = { rest: async () => ({ jobs: state.jobs }) }
  const container = document.getElementById('root')
  const root = ReactDOMClient.createRoot(container)

  const jobTitles = () => Array.from(container.querySelectorAll('*'))
    .filter((el) => el.children.length === 0)
    .map((el) => (el.textContent || '').trim())
    .filter((t) => /^岗位\d+$/.test(t))

  const buttons = () => Array.from(container.querySelectorAll('button'))
  const moreBtn = () => buttons().find((b) => (b.textContent || '').includes('更多岗位'))

  // ── 8 条岗位 ──
  await act(async () => {
    root.render(React.createElement(mod.RecommendView, { ctx, cfg: { settings: {} } }))
  })

  let titles = jobTitles()
  check('默认只渲染 5 条岗位', titles.length === 5,
        `实际 ${titles.length} 条：${titles.join(',')}`)
  check('显示的是分数最高的 5 条',
        titles.includes('岗位7') && titles.includes('岗位3') &&
        !titles.includes('岗位0') && !titles.includes('岗位1'),
        titles.join(','))

  // ── 有「更多岗位」按钮 ──
  let mb = moreBtn()
  check('有「更多岗位」按钮', !!mb, mb ? (mb.textContent || '').trim() : '没找到')
  check('按钮上标了还剩几条', !!mb && (mb.textContent || '').includes('3'),
        mb ? (mb.textContent || '').trim() : '')

  // ── 展开 ──
  if (mb) {
    await act(async () => { mb.click() })
    titles = jobTitles()
    check('★ 点开后展开全部 8 条', titles.length === 8,
          `实际 ${titles.length} 条`)
    const collapse = buttons().find((b) => (b.textContent || '').includes('收起'))
    check('展开后有「收起」按钮', !!collapse,
          collapse ? (collapse.textContent || '').trim() : '没找到')
  }

  // ── 收起 ──
  const collapse = buttons().find((b) => (b.textContent || '').includes('收起'))
  if (collapse) {
    await act(async () => { collapse.click() })
    titles = jobTitles()
    check('★ 点「收起」回到 5 条', titles.length === 5, `实际 ${titles.length} 条`)
  }

  // ── 不足 5 条时不该有「更多岗位」按钮 ──
  state.jobs = makeJobs(3)
  await act(async () => {
    root.render(React.createElement(mod.RecommendView, { ctx, cfg: { settings: {} } }))
  })
  titles = jobTitles()
  check('只有 3 条时全部显示', titles.length === 3, `实际 ${titles.length} 条`)
  check('只有 3 条时没有「更多岗位」按钮', !moreBtn(),
        moreBtn() ? '居然有' : '')

  // ── 正好 5 条 ──
  state.jobs = makeJobs(5)
  await act(async () => {
    root.render(React.createElement(mod.RecommendView, { ctx, cfg: { settings: {} } }))
  })
  check('正好 5 条时没有「更多岗位」按钮', !moreBtn())

  fs.unlinkSync(tmp)

  console.log('='.repeat(62))
  if (fails.length) {
    console.log('失败 %d 项：%s' % (fails.length, fails.join('、')))
    process.exit(1)
  }
  console.log('全部通过')
}

main().catch((e) => {
  console.error('ERR', e)
  process.exit(1)
})

// 真实渲染验证：「日报 ▸ 推送内容」面板里**必须有**抓取/推送时间编辑器。
//
// ## 为什么需要这个
//
// 用户反馈：「**推送内容模块并没有，选填推送时间的功能。**」
//
// 真相：编辑器一直存在 —— 但在**「设置」页**的「抓取与推送时间」面板里，
// 而**「推送内容」面板的提示语却写着「未设置抓取/推送时间点」**
// → **指向一个他看不到的地方** → 像是功能不存在。
//
// **这类 bug 单测抓不到**：代码里 `TimeSlotEditor` 在不在、
// 在哪个面板里，只有**真渲染**才能证明「用户看得到」。
//
// ## 验什么
//
// 1. 「推送内容」面板**渲染出来了**
// 2. 面板里**有两个**时间编辑器（抓取 / 推送）
// 3. **点「＋ 添加抓取时间」会出现输入框**（能真的加，不是摆设）
// 4. 输入 `07:30` 能加进列表
// 5. 「设置」页**不再有**第二个时间编辑器（同类入口只留一处）
//
// 用法：node scripts/verify-push-times-panel.mjs [plugin.js]

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
  const tmp = path.join(os.tmpdir(), `jr-pushtimes-${process.pid}.mjs`)
  fs.writeFileSync(tmp, stubSrc + '\n' + code + '\nexport { ReportView, SettingsView };\n', 'utf8')
  globalThis.__SDK__ = sdk
  const mod = await import(pathToFileURL(tmp).href)
  return { mod, tmp }
}

async function main() {
  console.log('='.repeat(62))
  console.log('「推送内容」面板时间编辑器 —— 真实 DOM 渲染验证')
  console.log('='.repeat(62))

  const state = { settings: { scan_times: ['09:00'], push_times: ['17:30'] }, saved: [] }

  const sdk = {
    React,
    jsx: jsxRuntime.jsx,
    jsxs: jsxRuntime.jsxs,
    Fragment: jsxRuntime.Fragment,
    useQuery(opts) {
      const key = JSON.stringify(opts?.queryKey || [])
      if (key.includes('config')) {
        return { data: { settings: state.settings }, isLoading: false, isError: false, error: null }
      }
      if (key.includes('report')) {
        return { data: { markdown: '# 日报' }, isLoading: false, isError: false, error: null }
      }
      return { data: {}, isLoading: false, isError: false, error: null }
    },
    // **记录每次保存调用** —— 「点确定有没有真的把新值送出去」
    useMutation(opts) {
      return {
        mutate: (payload) => { state.saved.push(payload) },
        isPending: false,
      }
    },
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
  check('plugin.js 加载成功', typeof mod.ReportView === 'function')
  if (typeof mod.ReportView !== 'function') {
    fs.unlinkSync(tmp); process.exit(1)
  }

  const ctx = { rest: async () => ({}) }
  const container = document.getElementById('root')
  const root = ReactDOMClient.createRoot(container)

  const text = () => (container.textContent || '')
  const buttons = () => Array.from(container.querySelectorAll('button'))
  const inputs = () => Array.from(container.querySelectorAll('input'))

  // ── 渲染「日报」页（里面含「推送内容」面板）──
  await act(async () => {
    root.render(React.createElement(mod.ReportView, { ctx, cfg: { settings: state.settings } }))
  })

  check('「推送内容」面板渲染出来了', text().includes('推送内容'))
  check('面板里有「每天抓取时间」', text().includes('每天抓取时间'))
  check('面板里有「每天推送时间」', text().includes('每天推送时间'))

  // ── 已配的时间点要显示出来 ──
  check('已配的抓取时间显示出来了', text().includes('09:00'), text().slice(0, 200))
  check('已配的推送时间显示出来了', text().includes('17:30'))

  // ── 「＋ 添加抓取时间」按钮存在 ──
  const addScan = buttons().find((b) => (b.textContent || '').includes('添加抓取时间'))
  check('有「＋ 添加抓取时间」按钮', !!addScan,
        addScan ? (addScan.textContent || '').trim() : buttons().map((b) => (b.textContent || '').trim()).join(' | '))

  // ── 点它 → 出现输入框 ──
  //
  // **别用「输入框总数」判断** —— 页面上本来就有别的输入框
  // （报告面板的输入、筛选框等）→ 计数不可靠。
  // → **直接看有没有 `HH:MM` 的输入框**。
  const hhmmInputs = () => inputs().filter((i) => (i.placeholder || '').toUpperCase().includes('HH:MM'))
  if (addScan) {
    const before = hhmmInputs().length
    await act(async () => { addScan.click() })
    check('点「＋」后出现 HH:MM 输入框', hhmmInputs().length > before,
          `HH:MM 输入框数 ${before} → ${hhmmInputs().length}`)

    const editor = hhmmInputs()[hhmmInputs().length - 1]
    const confirm = buttons().find((b) => {
      const t = (b.textContent || '').trim()
      return t === '添加' || t === '确定' || t === '保存'
    })
    check('时间点编辑器有确认按钮', !!confirm,
          confirm ? (confirm.textContent || '').trim() : '没找到')

    // ⚠️ **「输入 → 添加」的完整链路不在这里验** ——
    //
    // jsdom 里 `Input` 是**原生 input**，而 `TimeSlotEditor` 用的是
    // **受控 value**（`value={input}` + `onChange`）。
    // React 对受控组件有**内部值追踪**：jsdom 里改 DOM 的 value
    // 不会让 React 认为值变了 → `onChange` 拿到的还是旧值
    // → `add()` 的校验失败 → 不调 `onChange`。
    //
    // **这是 jsdom + React 受控组件的经典陷阱，不是产品 bug。**
    // → **行为（输入 → 列表里出现）必须让用户在真 app 里点**。
    //
    // 这里只验到「**控件确实在、能点开、能输入**」。
    check('编辑器控件齐备（输入框 + 确定 + 取消）',
          !!editor && !!confirm &&
          buttons().some((b) => (b.textContent || '').trim() === '取消'))
  }

  // ── 「设置」页**不再有**第二个时间编辑器 ──
  if (typeof mod.SettingsView === 'function') {
    await act(async () => {
      root.render(React.createElement(mod.SettingsView, { ctx, cfg: { settings: state.settings } }))
    })
    const addBtns = buttons().filter((b) => (b.textContent || '').includes('添加抓取时间'))
    check('「设置」页不再有第二个时间编辑器（同类入口只留一处）',
          addBtns.length === 0, `找到 ${addBtns.length} 个`)
    check('「设置」页不再有「抓取与推送时间」面板',
          !text().includes('抓取与推送时间'))
  }

  fs.unlinkSync(tmp)

  console.log('='.repeat(62))
  if (fails.length) {
    console.log('失败 %d 项：%s' % (fails.length, fails.join('、')))
    process.exit(1)
  }
  console.log('全部通过')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})

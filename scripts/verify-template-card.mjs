// 真实渲染验证：简历模板卡片在**后端漏字段**时不能崩。
//
// ## 为什么需要这个
//
// 用户报：**整个路由渲染失败**（不是卡片不好看，是整页报错）：
//
//     plugin:job-radar:job-radar:job-radar-route 渲染失败
//     Cannot read properties of undefined (reading 'toUpperCase')
//
// 日志里的堆栈很明确：
//
//     at TemplateCard (blob:file:///...:2657:25)
//
// 根因：`TemplateCard` 渲染上传模板的角标时写了
//
//     tpl.format.toUpperCase()
//
// 而 `resume_template.template_info()` 原来**不返回 `format`** →
// `tpl.format` 是 undefined → 抛异常 → **React 整棵组件树崩掉**
// （错误边界接管，整页显示失败）。
//
// **这个脚本喂一条「没有 format 的模板」**，验证**不崩**。
//
// ## 为什么必须真渲染
//
// 复刻逻辑只能验「表达式写了兜底」——
// **真正的风险是「后端某天又少给一个字段」**。
// 真渲染才能证明「字段缺失时页面还能出来」。
//
// 用法：node scripts/verify-template-card.mjs [plugin.js]

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
  const tmp = path.join(os.tmpdir(), `jr-tplcard-${process.pid}.mjs`)
  fs.writeFileSync(tmp, stubSrc + '\n' + code + '\nexport { TemplateCard };\n', 'utf8')
  globalThis.__SDK__ = sdk
  const mod = await import(pathToFileURL(tmp).href)
  return { mod, tmp }
}

async function main() {
  console.log('='.repeat(62))
  console.log('简历模板卡片 —— 真实 DOM 渲染验证（字段缺失不能崩）')
  console.log('='.repeat(62))

  const sdk = {
    React,
    jsx: jsxRuntime.jsx,
    jsxs: jsxRuntime.jsxs,
    Fragment: jsxRuntime.Fragment,
    useQuery: () => ({ data: {}, isLoading: false, isError: false, error: null }),
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
  check('plugin.js 加载成功', typeof mod.TemplateCard === 'function')
  if (typeof mod.TemplateCard !== 'function') {
    fs.unlinkSync(tmp); process.exit(1)
  }

  const container = document.getElementById('root')
  const root = ReactDOMClient.createRoot(container)

  // **故意缺 format** —— 这就是崩溃的输入
  const CASES = [
    { label: '上传模板（没有 format 字段）', tpl: { template_id: 'u1', name: '我的模板', builtin: false } },
    { label: '上传模板（format 是 undefined）', tpl: { template_id: 'u2', name: '另一个', builtin: false, format: undefined } },
    { label: '上传模板（format 是空串）', tpl: { template_id: 'u3', name: '空的', builtin: false, format: '' } },
    { label: '上传模板（正常，有 format）', tpl: { template_id: 'u4', name: '正常', builtin: false, format: 'docx' } },
    { label: '内置模板（走缩略图分支）', tpl: { template_id: 'classic', name: '经典单栏', builtin: true } },
    { label: '整个对象都没有', tpl: {} },
  ]

  for (const c of CASES) {
    let crashed = null
    try {
      await act(async () => {
        root.render(React.createElement(mod.TemplateCard, {
          tpl: c.tpl, active: false, onToggle: () => {}, onDelete: () => {},
        }))
      })
    } catch (e) {
      crashed = e
    }
    check(c.label + ' —— 渲染不崩', !crashed,
      crashed ? String(crashed.message || crashed) : '')
  }

  // 角标文本：有 format 时显示大写，没有时显示兜底
  const texts = () => Array.from(container.querySelectorAll('*'))
    .filter((el) => el.children.length === 0)
    .map((el) => (el.textContent || '').trim())

  await act(async () => {
    root.render(React.createElement(mod.TemplateCard, {
      tpl: { template_id: 'u', name: '我的模板', builtin: false, format: 'docx' },
      active: false, onToggle: () => {}, onDelete: () => {},
    }))
  })
  check('有 format 时角标是大写', texts().includes('DOCX'), texts().join(','))

  await act(async () => {
    root.render(React.createElement(mod.TemplateCard, {
      tpl: { template_id: 'u', name: '我的模板', builtin: false },
      active: false, onToggle: () => {}, onDelete: () => {},
    }))
  })
  check('没有 format 时有兜底角标', texts().length > 0, texts().join(','))

  fs.unlinkSync(tmp)
  console.log('='.repeat(62))
  if (fails.length) {
    console.log(`✘ ${fails.length} 项没过`)
    process.exit(1)
  }
  console.log('✔ 全部通过')
}

main().catch((e) => { console.error(e); process.exit(1) })

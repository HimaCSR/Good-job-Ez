#!/usr/bin/env node
/**
 * 检查桌面端 plugin.js 用到的 Tailwind 类在 app 的 CSS 里是否真的存在。
 *
 * ## 为什么需要这个
 *
 * Hermes 桌面 app 的 CSS 是 **Tailwind JIT 生成的** ——
 * **只包含 app 自己源码里出现过的类**。
 *
 * 插件是「磁盘上未编译的 ESM」，它的 className 不会进 Tailwind 的扫描范围。
 * 所以插件写了一个 app 没用过的类（比如 `max-w-5xl`），
 * **那个类在 app 的 CSS 里根本不存在** → 样式静默失效，
 * 不报错、不警告，只是「看起来不对」。
 *
 * 这就是为什么「标签栏不显示」这种问题能在代码层查不出来：
 * JS 完全正确，React 完全正确，只是那个 class 没有对应的 CSS 规则。
 *
 * ## 用法
 *
 *   node scripts/check-desktop-css.mjs <plugin.js> <app.css>
 *
 * app.css 从 Hermes 安装目录里拿：
 *   apps/desktop/release/win-unpacked/resources/app.asar.unpacked/dist/assets/index-*.css
 */

import fs from 'node:fs'

const [pluginPath, cssPath] = process.argv.slice(2)
if (!pluginPath || !cssPath) {
  console.error('用法：node scripts/check-desktop-css.mjs <plugin.js> <app.css>')
  process.exit(2)
}

const plugin = fs.readFileSync(pluginPath, 'utf8')
const css = fs.readFileSync(cssPath, 'utf8')

// ① 收集 plugin.js 里用到的 className
const used = new Set()
const push = (s) => {
  for (const c of String(s).split(/\s+/)) {
    if (c && c.length > 1 && !c.startsWith('--')) used.add(c)
  }
}
// className: '...'  和  className: cn('a', 'b')
for (const m of plugin.matchAll(/className:\s*'([^']*)'/g)) push(m[1])
for (const m of plugin.matchAll(/className:\s*"([^"]*)"/g)) push(m[1])
for (const m of plugin.matchAll(/cn\(([\s\S]{0,400}?)\)/g)) {
  for (const q of m[1].matchAll(/'([^']*)'/g)) push(q[1])
}

// ② 不是 Tailwind 类的（HTML 标签名、配置值、路径……）—— 排除掉
const IGNORE = new Set([
  'h1', 'h2', 'h3', 'pre', 'main', 'select', 'textarea', 'input', 'div',
  'span', 'button', 'label', 'img', 'svg', 'path', 'a', 'p', 'ul', 'li',
  'classic', 'modern', 'tech', 'acad', 'builtin', 'pdf', 'docx', 'image',
  'profile', 'recommend', 'resume', 'platform', 'report', 'mock', 'primary',
  'secondary', 'tertiary', 'muted', 'warn', 'ok', 'pick', 'phone', 'email',
  'name', 'school', 'major', 'degree', 'zp_at', '__zp_stoken__', 'at', 'rt',
  'mock-status', 'min_salary', 'min_score', 'max_jobs_per_run', 'push_max',
  'push_new_only', 'rounds_per_day', 'active_hours', 'notify_on_failure',
  'template_allow', 'smart_template', 'apply_zhaopin', 'apply_boss',
  'apply_huibo', 'apply_limit_zhaopin', 'apply_limit_boss', 'apply_limit_huibo',
  'keywords', 'city', 'boss_city', 'sites', 'request_gap_seconds',
  'min_experience_years', 'title_keywords', 'skills', 'cities', 'identity',
  'experience_text', 'exclude_companies', 'uploaded', 'job_id', 'resume_id',
  'template_id', 'file_path', 'match_score', 'tags', 'source', 'created',
  'updated', 'builtin', 'preview_path', 'description', 'name', 'format',
])

// ③ CSS 里类名的字面量匹配
// Tailwind 把 .  (  )  [  ]  /  #  %  等都转义成反斜杠形式：
//   bg-(--ui-x)  →  .bg-\(--ui-x\)
//   gap-2.5      →  .gap-2\.5
//   w-1/2        →  .w-1\/2
//   text-[0.5rem]→  .text-\[0\.5rem\]
function escapeClass(c) {
  // Tailwind 在 CSS 里把类名中的特殊字符转义成反斜杠形式：
  //   bg-(--ui-x)   →  .bg-\(--ui-x\)
  //   gap-2.5       →  .gap-2\.5
  //   w-1/2         →  .w-1\/2
  //   text-[0.5rem] →  .text-\[0\.5rem\]
  // 冒号单独处理（变体前缀）：hover:bg-x → .hover\:bg-x
  // **用函数形式的 replace** —— 替换串里的 `$&` 是「整个匹配」，
  // 直接写 `'\\$&'` 会把原字符全丢掉（替换串里 `$&` 永远是特殊语法，
  // 要拿到字面量 `$&` 得用函数形式）。
  return c.replace(/[.*+?^${}()|[\]\\/#%!,'"<>~]/g, (m) => '\\' + m)
}

const missing = []
for (const c of used) {
  if (IGNORE.has(c)) continue
  if (!/^[a-z]/.test(c)) continue

  // 变体前缀：hover: / focus: / disabled: / sm: / last: …
  // **只拆第一个冒号** —— Tailwind 的任意值语法里也有冒号
  // （比如 `bg-(--ui-x)`），拆多了会把类名切碎。
  let base = c
  const variants = []
  while (base.includes(':')) {
    const i = base.indexOf(':')
    variants.push(base.slice(0, i))
    base = base.slice(i + 1)
  }
  if (!base || base.startsWith('--')) continue

  // 变体类在 CSS 里形如 `.hover\:bg-xxx:hover{...}`
  // —— **变体前缀在 base 前面**，冒号转义成 `\:`，后面跟状态伪类
  const state = variantState(variants)
  const literal = '.' +
    (variants.length ? variants.map(escapeClass).join('\\:') + '\\:' : '') +
    escapeClass(base) + state
  if (process.env.DEBUG_CSS) console.error('DEBUG', JSON.stringify({ c, literal, inCss: css.includes(literal) }))
  // 有些变体编译成 `.hover\:bg-xxx:hover{...}`，有些是 `.hover\:bg-xxx{...}`
  if (!css.includes(literal)) {
    // 再试不带状态伪类的裸类（app 可能有等价实现）
    const bare = '.' + escapeClass(base)
    if (!css.includes(bare)) missing.push(c)
  }
}

/** 状态类（hover / focus / disabled …）在 CSS 里是 `:hover` 这种伪类。 */
function variantState(variants) {
  for (const v of variants) {
    if (v === 'hover' || v === 'focus' || v === 'active'
        || v === 'disabled' || v === 'focus-visible') {
      return ':' + v
    }
  }
  return ''
}

if (missing.length) {
  console.error('✘ 以下类在 app 的 CSS 里不存在（样式会静默失效）：')
  for (const c of missing.sort()) console.error('    ' + c)
  console.error('')
  console.error('  → 换一个 app 用过的等价类，或改用内联 style。')
  console.error('  → 硬编码颜色（如 #0053fd）也违反主题变量约定。')
  process.exit(1)
}
console.log('✔ 桌面端用到的类在 app CSS 里都存在（检查了 ' + used.size + ' 个）')

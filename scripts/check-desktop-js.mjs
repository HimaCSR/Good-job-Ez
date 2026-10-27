/* 桌面端 plugin.js 的语法自检。
 *
 * 只解析，不执行 —— plugin.js 会 import '@hermes/plugin-sdk'，
 * 那个包在插件目录外，node 直接 import 会失败。
 * 所以把 import 语句剥掉，再把剩下的当脚本解析。
 *
 * 用法：node scripts/check-desktop-js.mjs <文件路径>
 */
import fs from 'node:fs'
import vm from 'node:vm'

const path = process.argv[2]
if (!path) {
  console.error('用法：node scripts/check-desktop-js.mjs <文件路径>')
  process.exit(2)
}

const src = fs.readFileSync(path, 'utf8')

// 剥掉 import / export default（顶层 await 保留）
const stripped = src
  .replace(/^\s*import\s[\s\S]*?from\s+['"][^'"]*['"];?\s*$/gm, '')
  .replace(/^\s*import\s+['"][^'"]*['"];?\s*$/gm, '')
  .replace(/^\s*export\s+default\s/gm, 'const __default = ')

try {
  new vm.Script(stripped, { filename: path })
  console.log('JS 语法 OK：' + path)
} catch (err) {
  console.error('JS 语法错误：' + path)
  console.error(err.message)
  process.exit(1)
}

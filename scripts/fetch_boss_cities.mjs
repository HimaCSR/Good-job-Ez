// 从 BOSS 页面上下文抓全量城市码 → 存 JSON
//
// **为什么要这个**：
// `bb-browser eval "<长代码>"` 走命令行，**Windows 命令行有 8191 字符上限**
// → 长代码被截断 → SyntaxError: Unexpected end of input。
// 直连 CDP 的 Runtime.evaluate **没有长度限制**。
//
// 用法：node fetch_boss_cities.mjs <输出路径>
import { writeFileSync } from 'node:fs';

const outPath = process.argv[2];
if (!outPath) { console.error('用法: node fetch_boss_cities.mjs <输出路径>'); process.exit(1); }

const CDP = 'http://127.0.0.1:9222';

// 找 BOSS 的 tab
const listRes = await fetch(CDP + '/json/list');
const tabs = await listRes.json();
const boss = tabs.find((t) => t.type === 'page' && (t.url || '').includes('zhipin.com'));
if (!boss) { console.error('没有 BOSS tab —— 先 bb-browser open zhipin.com'); process.exit(1); }
console.error('BOSS tab:', boss.id, boss.url);

const ws = new WebSocket(boss.webSocketDebuggerUrl);
let msgId = 0;
const pending = new Map();

ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});

function send(method, params) {
  const id = ++msgId;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

await new Promise((res, rej) => {
  ws.addEventListener('open', res, { once: true });
  ws.addEventListener('error', rej, { once: true });
});

// 在页面上下文里跑 —— 一次拿全量，不分批（CDP 没有长度限制）
const code = `(async () => {
  const r = await fetch('/wapi/zpgeek/common/data/city/site.json', { credentials: 'include' });
  const d = await r.json();
  const zd = d.zpData || {};
  const out = {};
  for (const g of (zd.siteGroup || [])) {
    for (const c of (g.cityList || [])) {
      if (c && c.code && c.name) out[c.name] = c.code;
    }
  }
  for (const c of (zd.otherCitySites || [])) {
    if (c && c.code && c.name && !out[c.name]) out[c.name] = c.code;
  }
  for (const c of (zd.hotCitySites || [])) {
    if (c && c.code && c.name && !out[c.name]) out[c.name] = c.code;
  }
  for (const c of (zd.siteList || [])) {
    if (c && c.code && c.name && !out[c.name]) out[c.name] = c.code;
  }
  return JSON.stringify({ count: Object.keys(out).length, cities: out });
})()`;

const res = await send('Runtime.evaluate', {
  expression: code,
  awaitPromise: true,
  returnByValue: true,
});

const val = res.result?.result?.value;
if (!val) {
  console.error('eval 失败:', JSON.stringify(res).slice(0, 500));
  process.exit(1);
}
const parsed = JSON.parse(val);
console.error('城市数:', parsed.count);
writeFileSync(outPath, JSON.stringify(parsed.cities, null, 1), 'utf-8');
console.error('已写入', outPath);
ws.close();
process.exit(0);

// 从智联的**城市 SEO 页**抓全量城市码。
//
// ## 为什么走这条路
//
// 智联的搜索接口 `zhaopin/search --city <码>` 只认码，
// 而「城市名 → 码」的对应关系**没有公开接口**：
// - `city/` 城市列表页是 **SPA**（HTML 只有 8 KB 空壳）
// - `fe-api.zhaopin.com/c/i/city-page/user-city` **按 IP 定位**，参数无效
//   （传 ipCity=苏州 仍返回重庆）
//
// **但城市 SEO 页是完整 SSR**（80 万字符），URL 里带 pinyin，
// 页面里的搜索链接带自己的 jl 码：
//
//     https://www.zhaopin.com/suzhou/  →  href=".../sou/jl639"
//
// → **抓 SEO 页就能拿到「城市名 → 码」**。
//
// ## 用法
//
//     node fetch_zhaopin_cities.mjs <输出路径> [pinyin ...]
//
// 不给 pinyin 就用内置的常见城市列表。
//
// ## 找城市的办法
//
// 城市页链接在别处；先给一批 pinyin 试，
// 404 的（len 很小）说明这个 pinyin 不存在 —— 去掉即可。
import { writeFileSync } from 'node:fs';

const outPath = process.argv[2];
const extra = process.argv.slice(3);

// 常见城市 pinyin（智联 SEO 页用的就是拼音）
const BASE = [
  // 直辖市
  'beijing', 'shanghai', 'guangzhou', 'shenzhen', 'tianjin', 'chongqing',
  // 省会 / 计划单列市
  'hangzhou', 'nanjing', 'suzhou', 'wuxi', 'chengdu', 'xian', 'wuhan',
  'changsha', 'zhengzhou', 'jinan', 'qingdao', 'hefei', 'fuzhou', 'xiamen',
  'kunming', 'guiyang', 'taiyuan', 'shijiazhuang', 'shenyang', 'dalian',
  'changchun', 'haerbin', 'lanzhou', 'wulumuqi', 'nanchang', 'nanning',
  // 地级市（江苏 / 浙江 / 山东）
  'liuzhou', 'guilin', 'beihai', 'ningbo', 'wenzhou', 'jinhua', 'shaoxing',
  'taizhou', 'huzhou', 'jiaxing', 'changzhou', 'xuzhou', 'nantong',
  'yancheng', 'yangzhou', 'zhenjiang', 'taizhoujs', 'lianyungang',
  'huaian', 'jining', 'zibo', 'weifang', 'yantai', 'rizhao',
  // 广东 / 福建 / 海南
  'foshan', 'dongguan', 'zhuhai', 'zhongshan', 'huizhou', 'shantou',
  'jiangmen', 'zhanjiang', 'maoming', 'zhaoqing', 'shanwei', 'meizhou',
  'qionghai', 'sanya', 'haikou', 'quanzhou', 'putian', 'longyan',
  'sanming', 'nanping',
  // 华中 / 华南
  'luoyang', 'yichang', 'xiangyang', 'zhuzhou', 'hengyang', 'ganzhou',
  'wuhu', 'bengbu', 'huanggang', 'yueyang', 'changde', 'zhangjiajie',
  'foshan2', 'shaoguan', 'meizhou2', 'heyuan', 'yunfu',
  // 西南 / 西北
  'leshan', 'zigong', 'luocheng', 'mianyang', 'nanchong', 'yibin',
  'guangyuan', 'dazhou', 'yaan', 'ziyang', 'changde2', 'guiyang2',
  'lijiang', 'dali', 'baoshan', 'jinghong', 'weinan', 'baoji', 'xianyang',
  'yanan', 'hanzhong', 'yulin', 'anning', 'pingliang', 'qingyang',
  'zhongwei', 'shihezi', 'kelamayi', 'korla', 'shihezi2', 'yining',
  // 华北
  'tangshan', 'qinhuangdao', 'handan', 'xingtai', 'baoding', 'zhangjiakou',
  'chengde', 'cangzhou', 'hengshui', 'datong', 'yangquan', 'changzhi',
  'jincheng', 'shuozhou', 'jinzhong', 'yuncheng', 'xinzhou', 'linfen',
  'lvliang', 'xingtai2', 'langfang', 'zhuozhou', 'baoding2',
  // 东北
  'anshan', 'fushun', 'benxi', 'dandong', 'jinzhou', 'yingkou',
  'fuxin', 'liaoyang', 'panjin', 'tieling', 'chaoyang', 'huludao',
  'jilin', 'siping', 'liaoyuan', 'tonghua', 'baishan', 'songyuan',
  'baicheng', 'qiqihar', 'jixi', 'hegang', 'shuangyashan', 'qitaihe',
  'mudanjiang', 'heihe', 'yichun', ' Daxinganling', 'hohhot', 'baotou',
  'wuhai', 'chifeng', 'tongliao', 'ordos', 'hulunbeier', 'xinganmeng',
  'xilin Gol', 'wulanchabu', 'bayannaoer', 'alashan',
];

const pinyins = [...new Set([...BASE, ...extra])];

// 在页面里找「这个城市自己的 jl 码」
// 形如 href="https://www.zhaopin.com/sou/jl639"
function findCode(html) {
  // 取**第一个** jl 码 —— 页面顶部是当前城市的搜索按钮
  const m = html.match(/\/sou\/jl(\d+)/);
  if (m) return m[1];
  const m2 = html.match(/[?&]jl=(\d+)/);
  return m2 ? m2[1] : null;
}

// 页面标题里通常有城市名
//
// 标题长这样：
//   北京招聘网_北京人才网_2026年北京最新招聘信息-智联招聘
//   长株潭招聘网_长株潭人才网_2026年长株潭最新招聘信息-智联招聘
//
// **取第一段**（「北京」「长株潭」）—— 后面那些是 SEO 套话。
function findName(html) {
  const m = html.match(/<title>([^<]*?)-2026/);
  let raw = m ? m[1] : (html.match(/<title>([^<]*)/) || ['', ''])[1];
  raw = raw.trim();
  // 「北京招聘网_北京人才网」 → 「北京」
  const head = raw.split(/[_\-]/)[0].trim();
  const clean = head.replace(/招聘网$/, '').replace(/人才网$/, '');
  return clean || raw;
}

const CHUNK = 6;
for (let i = 0; i < pinyins.length; i += CHUNK) {
  const batch = pinyins.slice(i, i + CHUNK);
  const codes = await Promise.all(batch.map(async (py) => {
    try {
      const r = await fetch('https://www.zhaopin.com/' + py + '/', {
        headers: { 'user-agent': 'Mozilla/5.0' },
      });
      if (!r.ok) return { py, code: null, name: '', status: r.status };
      const t = await r.text();
      // 8 KB 左右 = SPA 空壳，不是城市页
      if (t.length < 20000) return { py, code: null, name: '', len: t.length };
      return { py, code: findCode(t), name: findName(t), len: t.length };
    } catch (e) {
      return { py, code: null, name: '', err: String(e && e.message) };
    }
  }));
  for (const c of codes) {
    if (c.code) {
      console.log('  ' + String(c.name || c.py).padEnd(10) + c.py.padEnd(14) + ' → ' + c.code);
    }
  }
  // 限速
  await new Promise((r) => setTimeout(r, 1200));
}

// 第二遍：收集成映射
const all = {};
for (let i = 0; i < pinyins.length; i += CHUNK) {
  const batch = pinyins.slice(i, i + CHUNK);
  await Promise.all(batch.map(async (py) => {
    try {
      const r = await fetch('https://www.zhaopin.com/' + py + '/', {
        headers: { 'user-agent': 'Mozilla/5.0' },
      });
      if (!r.ok) return;
      const t = await r.text();
      if (t.length < 20000) return;
      const code = findCode(t);
      const name = findName(t);
      if (code && name) all[name] = code;
    } catch { /* 忽略 */ }
  }));
  await new Promise((r) => setTimeout(r, 1200));
}

console.log('\n合计 ' + Object.keys(all).length + ' 个城市');
writeFileSync(outPath, JSON.stringify(all, null, 1), 'utf-8');
console.log('已写入 ' + outPath);

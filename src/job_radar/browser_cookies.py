"""通过 CDP 读取浏览器的 cookie（不复制、不落盘）。

用 Node 跑一小段脚本连 CDP 的 browser target，拿 Storage.getCookies。
这样登录态只存在于内存里，不进日志、不进磁盘。
"""

import json
import os
import subprocess

NODE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "tools",
                     "node-26.7.0-win32-x64", "node.exe")

_SCRIPT = r'''
(async () => {
  const base = process.env.BB_CDP_URL || 'http://127.0.0.1:9222';
  const list = await (await fetch(base + '/json/version')).json();
  const ws = new WebSocket(list.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  await new Promise(r => ws.onopen = r);
  const send = (method, params) => new Promise(res => {
    const i = ++id; pending.set(i, res);
    ws.send(JSON.stringify({id: i, method, params: params || {}}));
  });
  // Storage.getCookies 是 browser 级 API，能拿到全部域的 cookie；
  // Network.getAllCookies 在 browser target 上会返回空。
  const r = await send('Storage.getCookies', {});
  const cookies = ((r.result && r.result.cookies) || []).map(c => ({
    name: c.name, domain: c.domain, expires: c.expires || 0,
    session: c.expires === -1 || !c.expires
  }));
  console.log(JSON.stringify(cookies));
  ws.close();
})();
'''


def fetch_cookies(cdp_url="http://127.0.0.1:9222", timeout=30):
    """返回 cookie 列表 [{name, domain, expires, session}]。失败返回 []。"""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".mjs")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_SCRIPT)
        env = dict(os.environ)
        env["BB_CDP_URL"] = cdp_url
        p = subprocess.run([NODE, path], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace",
                           env=env)
        out = (p.stdout or "").strip()
        if not out:
            return []
        return json.loads(out)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

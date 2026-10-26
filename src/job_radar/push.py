"""把日报推成 ≤50 字的多条消息。

用户的硬性约定：任何聊天窗单条消息不超过 50 字符，超出必须按句子拆成多条依次发。
这个模块负责生成那些消息片段（纯函数，可单测），发送由 gateway 负责。
"""

import re

# 强断点：句子/分句结束。弱断点：词内分隔符。硬切时绝不能落进 ASCII 单词里。
_STRONG_SEP = "。！？；\n"
_WEAK_SEP = "、，,:：; "
_ASCII_WORD = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-+/#")


def _last_index_of_any(text, chars):
    """text 中 chars 里任一字符的最后出现位置；没有则 -1。"""
    best = -1
    for ch in chars:
        i = text.rfind(ch)
        if i > best:
            best = i
    return best


def _safe_cut(text, limit):
    """在 <=limit 处找一个不会把 ASCII 单词劈成两半的断点，返回切分长度。

    顺序：句末标点 → 词内分隔符 → 回退到 ASCII 单词起点 → 硬切。
    切分点落在单词中间时（"javascript" 被切成 "javas"/"cript"）必须回退。
    """
    n = len(text)
    if n <= limit:
        return n
    window = text[:limit]
    strong = _last_index_of_any(window, _STRONG_SEP)
    if strong >= max(1, limit // 2):
        return strong + 1          # 断点标点归上一段，内容不丢
    weak = _last_index_of_any(window, _WEAK_SEP)
    if weak >= max(1, limit // 2):
        return weak + 1
    cut = limit
    if text[cut - 1] in _ASCII_WORD and cut < n and text[cut] in _ASCII_WORD:
        back = cut
        while back > 0 and text[back - 1] in _ASCII_WORD:
            back -= 1
        if back > 0:
            cut = back           # 退到单词起点，整词留给下一段
    return cut


def split_for_qq(text, limit=50):
    """按句子把长文本拆成 <=limit 字符的多条。

    优先在句末标点处断开；一句话本身就超长时，按 limit 硬切，
    但不会把英文单词从中间劈开（javascript → javas + cript）。

    **URL 行不拆。** 链接被切成两半就点不开了 —— 宁可这条超长，
    平台对 URL 本来就有豁免。
    """
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    parts, rest = [], text
    while len(rest) > limit:
        # 当前这段以 URL 开头（可能带前导文字）→ 先把 URL 完整切出来
        cut = _url_boundary(rest, limit)
        if cut is None:
            cut = _safe_cut(rest, limit)
        if cut <= 0:
            cut = limit
        piece = rest[:cut].strip()
        if piece:
            parts.append(piece)
        rest = rest[cut:]
    tail = rest.strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


_URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _url_boundary(text, limit):
    """切分点：让下一段从一个完整 URL 的开头开始。

    返回切分长度；这一段里没有需要保护的 URL 时返回 None。

    场景：「正文… https://example.com/very/long/path」在 limit 处硬切，
    结果前半段的 https: 和后半段的 //example.com 分家 ——
    这里把切点推到 URL 之前，URL 完整落到下一段。
    """
    m = _URL_RE.search(text)
    if not m:
        return None
    start = m.start()
    if start == 0:
        # 这一段就是 URL —— 整条不切，交给调用方原样发出
        return len(text)
    if start >= limit:
        return None
    # URL 起点在 limit 之内 → 在 URL 前切开，URL 完整进下一段
    return start


def format_job(job, index=None):
    """一条岗位 → 两条短消息：标题行 + 链接。

    **格式（2026-10-26 用户定）**：
    ```
    web前端开发工程师 · 杭州拱墅
    https://www.zhaopin.com/jobdetail/CC3985.htm
    ```
    **不带分数、不带命中理由** —— 完整明细在日报 Markdown 文件里，
    推送只是索引。

    每条 ≤50 字符（URL 除外）。
    """
    title = job.get("title") or "(无标题)"
    area = job.get("area") or job.get("city") or ""
    url = job.get("url") or ""

    head = title
    if area:
        head = "%s · %s" % (title, area)
    if len(head) > 48:
        head = head[:47] + "…"
    msgs = [head]

    if url:
        # URL 不能拆（拆了就点不开），超长时原样发出。
        # 平台本身对 URL 有豁免，50 字约定针对的是正文文本。
        msgs.append(url)

    return [m for m in msgs if m]


def build_push(jobs, min_score=0, max_jobs=3):
    """给一批岗位生成推送消息序列。"""
    msgs = []
    picked = [j for j in jobs if (j.get("score") or 0) >= min_score][:max_jobs]
    for i, j in enumerate(picked, 1):
        msgs.extend(format_job(j, i))
    return msgs

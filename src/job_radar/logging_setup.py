"""插件日志。

两层输出：

1. **插件自己的文件** —— <plugin-data>/logs/job-radar.log
   RotatingFileHandler（5 MB × 3 份），上限约 20 MB，到点自动轮转，
   最老的被覆盖删除。排查时一份文件看完，不被 agent.log 的噪音淹没，
   也能单独清理。

2. **标准 logging** —— logger 名 ``hermes_plugins.job_radar``
   跟着 Hermes 走，落进 agent.log / errors.log。
   Hermes 那边也有自己的轮转上限（5 MB × 3 / 2 MB × 2）。

**绝不能进日志的东西**（用户既定约束）：
- 凭证值（zp_at / at / rt 的具体内容）—— 只记「已登录，剩 N 天」
- cookie 值、请求头、session token
- 简历原文、真实经历

只记状态、计数、耗时、错误类型。凭证值统一记成 [REDACTED]。
"""

import logging
import logging.handlers
import os
import re
import sys

LOG_NAME = "hermes_plugins.job_radar"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3

# 需要打码的模式 —— 命中就把「值」换成 [REDACTED]
#
# 只打「键=值」形式的凭证。状态描述（「凭证 zp_at，剩余 12 天」）不该被打 ——
# 那不是密钥，打了就没法排查了。
# 已知凭证键的值：单 token（不含空格）—— 避免「zp_at=x 剩余 12 天」把中文也吃掉
_SECRET_KV = re.compile(
    r"(?P<key>\b[A-Za-z_][A-Za-z0-9_.-]*)\s*[=:]\s*"
    r"(?P<val>(?!\[REDACTED)[^\s,;}\]\"']+)",
    re.I)
# 「Authorization: Bearer tok_123」这类 —— 值是「前缀 + 空格 + 真 token」，
# 只打第一个词（Bearer）会漏掉真正的 token，所以整段打到行尾。
_BEARER_KV = re.compile(
    r"(?P<key>\b(?:authorization|proxy-authorization)\b)\s*[=:]\s*"
    r"(?P<val>[^\s,;}\]\"']+(?:\s+[^\s,;}\]\"']+)*)",
    re.I)
# 其它键值：严格（单 token）—— 避免「zp_at=xxx 剩余 12 天」把中文也吃掉
_PLAIN_KV = re.compile(
    r"(?P<key>\b[A-Za-z_][A-Za-z0-9_.-]*)\s*[=:]\s*(?P<val>(?!\[REDACTED\])[^\s,;}\]\"']+)")

# 已知的凭证键（大小写不敏感）
_SECRET_KEYS = {
    "zp_at", "wt2", "wbg", "__zp_stoken__", "at", "rt",
    "cookie", "cookies", "set-cookie", "authorization", "auth",
    "token", "access_token", "refresh_token", "password", "passwd", "secret",
    "session", "sessionid", "sid", "ticket", "api_key", "apikey",
}

# 超长随机串（session/token 特征）—— 不碰 URL 里的路径段
_LONG_RE = re.compile(r"(?<![/\w.-])[A-Za-z0-9_-]{40,}(?![/\w.-])")


def _redact_kv(m):
    """已知凭证键 → 整段值换成 [REDACTED]；其它键值原样保留。"""
    key = m.group("key")
    if key.lower() in _SECRET_KEYS:
        return f"{key}=[REDACTED]"
    return m.group(0)


def redact(text):
    """把凭证样的内容打码。日志里出现 [REDACTED] 而不是原值。

    两轮：先按「已知凭证键」宽松匹配（值可跨空格，能吃掉
    「Bearer tok_123」整段），再按普通键值严格匹配（不误伤
    「剩余 12 天」这类中文描述）。

    「凭证 zp_at，剩余 12 天」这种状态描述不打 —— 打了就没法排查。
    """
    if text is None:
        return ""
    s = str(text)
    s = _BEARER_KV.sub(_redact_kv, s)
    s = _SECRET_KV.sub(_redact_kv, s)
    s = _PLAIN_KV.sub(_redact_kv, s)
    # 长串规则在打码之后跑：避免把刚生成的 [REDACTED] 又打一遍
    s = _LONG_RE.sub("[REDACTED]", s)
    return s


class _RedactingFormatter(logging.Formatter):
    """所有消息过一遍 redact()，双保险。"""

    def format(self, record):
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return super().format(record)


def _plugin_data_dir() -> str:
    """插件数据目录（与 storage.py 同一处）。"""
    try:
        from plugins.plugin_storage import plugin_data_dir
        return plugin_data_dir("job-radar")
    except ImportError:
        base = os.environ.get("LOCALAPPDATA", "")
        return os.path.join(base, "hermes", "plugin-data", "job-radar")


def log_dir() -> str:
    d = os.path.join(_plugin_data_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def log_file() -> str:
    """当前日志文件路径（设置页「查看日志」用）。"""
    return os.path.join(log_dir(), "job-radar.log")


_logger = None


def get_logger() -> logging.Logger:
    """插件日志器。幂等，重复调用返回同一个。"""
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger(LOG_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False      # 不往 root 冒泡，避免重复写

    # **全局注册表里的 logger 是共享的。** 同一个名字再取一次拿到的是同一个对象，
    # 再 addHandler 就会写两遍（插件宿主 + dashboard 层各加载一次就会撞上）。
    # 所以先看有没有 handler，有就直接复用。
    if logger.handlers:
        _logger = logger
        return logger

    fmt = _RedactingFormatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ① 自己的文件（轮转）
    try:
        fh = logging.handlers.RotatingFileHandler(
            log_file(), maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
            encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass    # 文件开不了也不能拖垮插件

    # ② 标准 logging → Hermes 的 agent.log / errors.log
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    _logger = logger
    return logger


def tail(n: int = 200) -> str:
    """日志末尾 n 行（设置页「查看日志」用）。"""
    path = log_file()
    if not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        return "".join(lines[-n:])
    except Exception:
        return ""


def purge(keep_days: int = 30) -> int:
    """删掉太老的轮转文件（.1 .2 .3），返回删掉的数量。

    轮转本身已经保证了总量上限；这个是额外的「按天清理」，
    留着几个月前的 .3 没意义。
    """
    import time
    d = log_dir()
    cutoff = time.time() - keep_days * 86400
    removed = 0
    try:
        for name in os.listdir(d):
            if not name.startswith("job-radar.log."):
                continue
            p = os.path.join(d, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed

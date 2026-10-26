"""日志模块的测试 —— 重点是「凭证不进日志」。"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging  # noqa: E402
import tempfile  # noqa: E402
from logging_setup import (  # noqa: E402
    redact, get_logger, log_file, tail, purge, _LazyRotatingFileHandler,
)


class TestRedact(unittest.TestCase):

    def test_known_secret_keys_are_masked(self):
        for text in [
            "zp_at=abc123def456",
            "cookie: sessionid=xyz987",
            "Authorization: Bearer tok_123",
            "token=ghp_ABCDEFGHIJKLMNOP",
            "password: hunter2",
        ]:
            out = redact(text)
            self.assertIn("[REDACTED]", out, text)
            # 原值不能残留
            for secret in ("abc123def456", "xyz987", "tok_123", "hunter2"):
                self.assertNotIn(secret, out, text)

    def test_status_text_is_not_masked(self):
        """状态描述不是密钥 —— 打了就没法排查。"""
        text = "BOSS直聘已登录（凭证 zp_at），剩余 12 天"
        self.assertEqual(redact(text), text)

    def test_url_is_not_masked(self):
        url = "https://www.zhaopin.com/jobdetail/CC398533130J40905945205.htm"
        self.assertEqual(redact(url), url)

    def test_company_name_is_not_masked(self):
        text = "杭州东识科技有限公司 · 20-30K"
        self.assertEqual(redact(text), text)

    def test_long_random_string_is_masked(self):
        long_token = "A" * 48
        self.assertIn("[REDACTED]", redact("x=" + long_token))

    def test_none_and_empty(self):
        self.assertEqual(redact(None), "")
        self.assertEqual(redact(""), "")


class TestLogger(unittest.TestCase):

    def test_logger_is_singleton(self):
        a = get_logger()
        b = get_logger()
        self.assertIs(a, b)
        # 重复取不能叠加 handler（否则每条日志写两遍）
        self.assertEqual(len(a.handlers), len(b.handlers))

    def test_write_and_tail(self):
        log = get_logger()
        log.info("测试日志行 %d", 12345)
        text = tail(50)
        self.assertIn("测试日志行 12345", text)

    def test_secret_never_reaches_file(self):
        """凭证值不能落到日志文件里。

        只看**这次新写的**那几行 —— tail() 会带出历史内容，
        早先版本没打码时写下的行还在文件里，不能拿它们判定。
        """
        log = get_logger()
        marker = "SECRET_PROBE_%d" % (int(time.time() * 1000) % 1000000)
        before = len(tail(100000))
        log.error("zp_at=%s 登录失败", marker)
        fresh = tail(100000)[before:]
        self.assertNotIn(marker, fresh)
        self.assertIn("[REDACTED]", fresh)

    def test_log_file_exists(self):
        get_logger().info("确保文件存在")
        self.assertTrue(os.path.exists(log_file()))


class TestLazyHandlerStream(unittest.TestCase):
    """logging.shutdown 会摸 handler.stream ——
    懒加载时文件可能还没打开，属性缺失会抛 AttributeError。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jr-lazy-")

    def test_stream_property_exists_before_open(self):
        h = _LazyRotatingFileHandler(
            os.path.join(self.tmp, "never-written.log"), maxBytes=1024, backupCount=1)
        # 还没 emit 过，文件没打开
        self.assertIsNone(h.stream)

    def test_stream_setter_accepted(self):
        h = _LazyRotatingFileHandler(
            os.path.join(self.tmp, "never-written2.log"), maxBytes=1024, backupCount=1)
        h.stream = None          # 不该抛
        self.assertIsNone(h.stream)

    def test_shutdown_does_not_raise(self):
        """真实触发一次 shutdown —— 这是原来会炸的地方。"""
        h = _LazyRotatingFileHandler(
            os.path.join(self.tmp, "never-written3.log"), maxBytes=1024, backupCount=1)
        logging.addLevelName(logging.INFO, "INFO")
        logger = logging.getLogger("test_lazy_shutdown_%d" % id(h))
        logger.handlers = [h]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logging.shutdown()      # 不该抛


if __name__ == "__main__":
    unittest.main(verbosity=2)

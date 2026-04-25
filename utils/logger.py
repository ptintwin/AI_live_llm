# -*- coding: utf-8 -*-
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from datetime import datetime
from yaml import safe_load


# §四.2 Bug-10：全局日志脱敏过滤器。
# 避免异常堆栈 / 调试输出把 DashScope apiKey、X-Internal-Token 等敏感值写进日志。
# 正则覆盖：sk-xxx（DashScope）、Bearer xxx、apiKey/api_key/token 字段、X-Internal-Token 头值。
_REDACT_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9\-_]{16,}"), "sk-***REDACTED***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-_.=]{8,}"), r"\1***REDACTED***"),
    (re.compile(
        r"(?i)([\"']?(?:api[_\-]?key|access[_\-]?key[_\-]?secret|secret|token|x-internal-token)[\"']?\s*[:=]\s*[\"']?)"
        r"([^\s,'\"}\)]{4,})"
    ), r"\1***REDACTED***"),
]


class _RedactFilter(logging.Filter):
    """应用到所有 handler 的单例过滤器；消息最终文本中匹配到敏感值则替换。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = msg
        for pat, repl in _REDACT_PATTERNS:
            redacted = pat.sub(repl, redacted)
        if redacted is not msg:
            # 清空原 args，避免 format 时再次拼装未脱敏值
            record.msg = redacted
            record.args = None
        return True

# 日志目录
LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)


# 加载配置
def load_config():
    """加载配置文件"""
    config_path = "./config/config.yaml"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return safe_load(f)
    return {}


# 配置映射
LOG_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL
}


def get_logger(name: str = "game_live") -> logging.Logger:
    """工程级日志工具（文件+控制台双输出）"""
    logger = logging.getLogger(name)

    # 加载配置并设置日志级别
    config = load_config()
    log_level = config.get("server", {}).get("log_level", "info").lower()
    logger.setLevel(LOG_LEVEL_MAP.get(log_level, logging.INFO))

    logger.handlers.clear()  # 避免重复日志

    # 日志格式
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S.%f"
    )

    redact_filter = _RedactFilter()

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(redact_filter)
    logger.addHandler(console_handler)

    # 文件输出（按大小切割）
    file_handler = RotatingFileHandler(
        filename=f"{LOG_DIR}/live_{datetime.now().strftime('%Y%m%d')}.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redact_filter)
    logger.addHandler(file_handler)

    # 同名 filter 也挂 logger 本身，确保 propagate 到 root 时仍脱敏
    logger.addFilter(redact_filter)

    return logger


# 全局日志实例
logger = get_logger()
# -*- coding: utf-8 -*-
import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime
from yaml import safe_load

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

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出（按大小切割）
    file_handler = RotatingFileHandler(
        filename=f"{LOG_DIR}/live_{datetime.now().strftime('%Y%m%d')}.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# 全局日志实例
logger = get_logger()
# -*- coding: utf-8 -*-
"""
通用工具函数
"""
import time
import asyncio
from functools import wraps
from utils.logger import logger


def timer(func):
    """
    函数耗时统计装饰器

    Args:
        func: 被装饰的函数

    Returns:
        装饰后的函数
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        """异步函数包装器"""
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            end_time = time.time()
            elapsed_time = end_time - start_time
            logger.info(f"函数 {func.__name__} 执行完成，耗时: {elapsed_time:.2f}秒")
            return result
        except Exception as e:
            end_time = time.time()
            elapsed_time = end_time - start_time
            logger.error(f"函数 {func.__name__} 执行异常，耗时: {elapsed_time:.2f}秒，错误: {e}")
            raise

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        """同步函数包装器"""
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            end_time = time.time()
            elapsed_time = end_time - start_time
            logger.info(f"函数 {func.__name__} 执行完成，耗时: {elapsed_time:.2f}秒")
            return result
        except Exception as e:
            end_time = time.time()
            elapsed_time = end_time - start_time
            logger.error(f"函数 {func.__name__} 执行异常，耗时: {elapsed_time:.2f}秒，错误: {e}")
            raise

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


# ─────────────────────────────────────────────────────────────
# §八.5 配置取值工具：区分"显式 None / 缺字段 / 空串"与"合法值"
# 用于消费 Spring EffectiveConfigService 下发的合并配置，替代 ``rc.get(k) or default``。
# 原因（Bug-2）：旧写法会把用户显式设置的 0 / 0.0 / "" 误判为 falsy 并回退到默认值。
# ─────────────────────────────────────────────────────────────


def pick_str(source: dict, key: str, default):
    """取字符串值。仅当 key 缺失 / 值为 None / 值为空白串时才用 default。"""
    if not isinstance(source, dict) or key not in source:
        return default
    v = source.get(key)
    if v is None:
        return default
    if isinstance(v, str) and not v.strip():
        return default
    return v


def pick_float(source: dict, key: str, default):
    """取浮点值。区分"键缺失 / None → default"与"可转 float（含 0）→ 返回"。"""
    if not isinstance(source, dict) or key not in source:
        return float(default)
    v = source.get(key)
    if v is None:
        return float(default)
    try:
        return float(v)
    except (TypeError, ValueError):
        logger.warning(f"pick_float 解析失败 key={key} value={v!r}，回退 default={default}")
        return float(default)


def pick_int(source: dict, key: str, default):
    """取整数值。语义同 pick_float。"""
    if not isinstance(source, dict) or key not in source:
        return int(default)
    v = source.get(key)
    if v is None:
        return int(default)
    try:
        return int(v)
    except (TypeError, ValueError):
        logger.warning(f"pick_int 解析失败 key={key} value={v!r}，回退 default={default}")
        return int(default)


def pick_bool(source: dict, key: str, default):
    """取布尔值。None → default；其他转 bool()。"""
    if not isinstance(source, dict) or key not in source:
        return bool(default)
    v = source.get(key)
    if v is None:
        return bool(default)
    return bool(v)
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
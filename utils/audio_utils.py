# -*- coding: utf-8 -*-
import pyaudio
from utils.logger import logger

# 全局音频配置
AUDIO_CONFIG = {
    "format": pyaudio.paInt16,
    "channels": 1,
    "rate": 22050,
    "output": True,
    "frames_per_buffer": 1024
}


def get_pyaudio_instance() -> pyaudio.PyAudio:
    """获取PyAudio单例"""
    try:
        return pyaudio.PyAudio()
    except Exception as e:
        logger.error(f"PyAudio初始化失败: {str(e)}")
        raise


def close_audio_stream(p: pyaudio.PyAudio, stream):
    """安全关闭音频流"""

    def safe_operation(operation, error_msg):
        """安全执行操作并捕获异常"""
        try:
            operation()
        except Exception as e:
            logger.debug(f"{error_msg}: {e}")

    try:
        # 关闭音频流
        if stream:
            safe_operation(lambda: stream.stop_stream() if not stream.is_stopped() else None, "停止音频流时出错")
            safe_operation(lambda: stream.close(), "关闭音频流时出错")

        # 终止PyAudio实例
        if p:
            safe_operation(lambda: p.terminate(), "终止PyAudio时出错")

        logger.info("音频流已关闭")
    except Exception as e:
        logger.error(f"关闭音频流时出错: {e}")
# -*- coding: utf-8 -*-
from utils.logger import logger

# 懒加载 pyaudio（容器内 websocket 模式不需要，避免 import 崩溃）
try:
    import pyaudio as _pyaudio
    _PYAUDIO_FORMAT = _pyaudio.paInt16
except ImportError:
    _pyaudio = None
    _PYAUDIO_FORMAT = 8  # paInt16 的数值常量

# 全局音频配置
AUDIO_CONFIG = {
    "format": _PYAUDIO_FORMAT,
    "channels": 1,
    "rate": 22050,
    "output": True,
    "frames_per_buffer": 1024
}


def get_pyaudio_instance():
    """获取PyAudio单例（仅 pyaudio 模式下调用）"""
    if _pyaudio is None:
        raise RuntimeError("pyaudio 未安装，请使用 websocket 音频模式（audio_mode: websocket）")
    try:
        return _pyaudio.PyAudio()
    except Exception as e:
        logger.error(f"PyAudio初始化失败: {str(e)}")
        raise


def close_audio_stream(p, stream):
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
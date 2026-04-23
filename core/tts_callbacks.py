# -*- coding: utf-8 -*-
"""
TTS回调实现 - 支持两种音频播报模式
1. WebsocketTTSStreamCallback: 通过WebSocket将音频流广播到前端
2. PyAudioTTSStreamCallback: 通过pyaudio在服务端直接播放
"""
import asyncio
import time
from collections import deque
from dashscope.audio.tts_v2 import ResultCallback
from utils.audio_utils import get_pyaudio_instance, close_audio_stream, AUDIO_CONFIG
from utils.logger import logger

_PCM_BYTES_PER_SEC = 44100


class WebsocketTTSStreamCallback(ResultCallback):
    """TTS流式回调：将音频数据通过 WebSocket 广播到前端"""

    def __init__(self, tts_service, audio_broadcast_fn=None, main_loop=None):
        self.playing = False
        self.tts_service = tts_service
        self.play_completed = asyncio.Event()
        self.has_error = False
        self.total_bytes_received = 0
        self.audio_broadcast_fn = audio_broadcast_fn
        self._main_loop = main_loop
        self._complete_future = None

    def on_open(self):
        logger.info("TTS WebSocket连接已打开")

    def on_data(self, data: bytes):
        logger.debug(f"[TTS] on_data: 接收音频块，大小: {len(data)} 字节")
        self.playing = True
        self.total_bytes_received += len(data)
        if not self.audio_broadcast_fn:
            return
        if self._main_loop is not None:
            asyncio.run_coroutine_threadsafe(self.audio_broadcast_fn(data), self._main_loop)
        else:
            logger.error("[TTS] on_data: 未绑定主事件循环，无法广播 PCM")

    def on_complete(self):
        logger.info("[TTS] on_complete: 服务端通知合成完成！")
        self.has_error = False
        duration = self.total_bytes_received / _PCM_BYTES_PER_SEC + 0.3
        if self._complete_future and not self._complete_future.done():
            self._complete_future.cancel()
        self._complete_future = None
        if self._main_loop is not None:
            self._complete_future = asyncio.run_coroutine_threadsafe(
                self._delayed_complete(duration), self._main_loop
            )
        else:
            logger.error("[TTS] on_complete: 未绑定主事件循环")
            self.play_completed.set()

    async def _delayed_complete(self, delay: float):
        try:
            await asyncio.sleep(delay)
            self.playing = False
            self.play_completed.set()
            logger.info(f"[TTS] 估算播放完成（延迟 {delay:.2f}s）")
        except asyncio.CancelledError:
            pass

    def on_error(self, msg):
        logger.error(f"[TTS] on_error: {msg}")
        self.has_error = True
        self.playing = False
        self.close()
        if self.tts_service:
            logger.info("通知 TTSLiveService 重启流式播报")
            self.play_completed.set()

    def on_close(self):
        logger.info("[TTS] on_close: 已触发")

    def reset(self):
        self.play_completed.clear()
        self.total_bytes_received = 0
        self.playing = False
        self.has_error = False
        if self._complete_future and not self._complete_future.done():
            self._complete_future.cancel()
        self._complete_future = None

    def close(self):
        if self._complete_future and not self._complete_future.done():
            self._complete_future.cancel()
        self.playing = False
        logger.info("[TTS] WebsocketTTSStreamCallback 已关闭")

    async def _set_completed_event(self):
        self.play_completed.set()


class PyAudioTTSStreamCallback(ResultCallback):
    """TTS流式回调：通过pyaudio在服务端直接播放音频"""

    def __init__(self, tts_service):
        self.p = None
        self.stream = None
        self.playing = False
        self.tts_service = tts_service
        self.play_completed = asyncio.Event()
        self.has_error = False
        self.audio_buffer = deque()
        self.total_bytes_received = 0
        self.bytes_played = 0
        self.playback_task = None
        self.frames_per_buffer = AUDIO_CONFIG['frames_per_buffer']

    def on_open(self):
        logger.info("TTS WebSocket连接已打开")
        try:
            self.p = get_pyaudio_instance()
            self.stream = self.p.open(**AUDIO_CONFIG)
            logger.info("音频播放器初始化成功")
            self.playback_task = asyncio.create_task(self._playback_worker())
        except Exception as e:
            logger.error(f"初始化音频播放器失败: {e}")

    def on_data(self, data: bytes):
        logger.debug(f"[TTS] on_data: 接收音频块，大小: {len(data)} 字节")
        if self.stream:
            self.audio_buffer.append(data)
            self.total_bytes_received += len(data)

    def on_complete(self):
        logger.info("[TTS] on_complete: 服务端通知合成完成！")
        self.has_error = False

    def on_error(self, msg):
        logger.error(f"[TTS] on_error: {msg}")
        self.has_error = True
        self.play_completed.set()

    def on_close(self):
        logger.info("[TTS] on_close: 已触发")
        self.close()

    def reset(self):
        """重置单句合成状态，在每句合成前调用"""
        self.play_completed.clear()
        self.total_bytes_received = 0
        self.bytes_played = 0
        self.playing = False
        self.has_error = False

    async def _playback_worker(self):
        try:
            while True:
                if not self.stream:
                    logger.info("音频流已关闭，播放工作线程退出")
                    break

                if self.audio_buffer:
                    data = self.audio_buffer.popleft()
                    try:
                        self.playing = True
                        if self.stream:
                            self.stream.write(data)
                            self.bytes_played += len(data)

                            if self._is_playback_complete():
                                logger.info("音频播放完成，设置完成事件")
                                await self._set_completed_event()
                    except Exception as e:
                        logger.error(f"播放音频块时出错: {e}")
                        self.playing = False
                else:
                    await asyncio.sleep(0.01)

                    if self._is_playback_stalled():
                        await self._set_completed_event()
        except asyncio.CancelledError:
            logger.info("播放工作线程被取消")
        except Exception as e:
            logger.error(f"播放工作线程异常: {e}")
        finally:
            self.playing = False

    def _is_playback_complete(self) -> bool:
        if not self.stream:
            return False
        all_data_written = (self.bytes_played >= self.total_bytes_received)
        queue_empty = (len(self.audio_buffer) == 0)
        return all_data_written and queue_empty

    def _is_playback_stalled(self) -> bool:
        if self.total_bytes_received > 0 and len(self.audio_buffer) == 0:
            return True
        return False

    def close(self):
        if self.playback_task:
            self.playback_task.cancel()
            logger.info("播放任务已取消")

        stream = self.stream
        p = self.p

        self.stream = None
        self.p = None

        if stream and p:
            try:
                time.sleep(0.1)
                close_audio_stream(p, stream)
                logger.info("音频流和播放器已关闭")
            except Exception as e:
                logger.error(f"关闭音频流时出错: {e}")
        else:
            logger.info("音频流和播放器已关闭，跳过重复关闭")

    async def _set_completed_event(self):
        self.play_completed.set()
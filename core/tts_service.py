# -*- coding: utf-8 -*-
"""
CosyVoice流式TTS服务
满足：实时流式播放、自然中断、克隆音色、回调接口
"""
import os
import time
import asyncio
import traceback
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat, ResultCallback
from yaml import safe_load
from collections import deque
from config.prompts import TTS_INSTRUCTION
from utils.audio_utils import get_pyaudio_instance, close_audio_stream, AUDIO_CONFIG
from utils.logger import logger

# 加载配置
with open("./config/config.yaml", "r", encoding="utf-8") as f:
    config = safe_load(f)

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
if not dashscope.api_key:
    raise ValueError("DASHSCOPE_API_KEY环境变量未设置")

# 地域配置（北京地域），新加坡地域需替换对应URL
dashscope.base_websocket_api_url = 'wss://dashscope.aliyuncs.com/api-ws/v1/inference'
dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'


class TTSStreamCallback(ResultCallback):
    """TTS流式回调：实时播放音频"""

    def __init__(self, tts_service):
        self.p = None
        self.stream = None
        self.playing = False
        self.tts_service = tts_service
        self.play_completed = asyncio.Event()
        self.has_error = False

        # 新增：用于跟踪播放状态
        self.audio_buffer = deque()
        self.total_bytes_received = 0
        self.bytes_played = 0
        self.playback_task = None  # 播放任务
        self._lock = asyncio.Lock()
        self.frames_per_buffer = AUDIO_CONFIG['frames_per_buffer']

    def on_open(self):
        """WebSocket连接打开时初始化音频播放器"""
        logger.info("TTS WebSocket连接已打开")
        try:
            self.p = get_pyaudio_instance()
            self.stream = self.p.open(**AUDIO_CONFIG)
            logger.info("音频播放器初始化成功")

            # 启动后台播放任务
            self.playback_task = asyncio.create_task(self._playback_worker())
        except Exception as e:
            logger.error(f"初始化音频播放器失败: {e}")

    def on_data(self, data: bytes):
        """接收音频数据，添加到缓冲队列"""
        logger.debug(f"[TTS] on_data: 接收音频块，大小: {len(data)} 字节")
        if self.stream:
            # 将音频数据添加到缓冲队列（线程安全）
            self.audio_buffer.append(data)
            self.total_bytes_received += len(data)

    def on_complete(self):
        """合成完成回调 - 服务端通知合成完成"""
        logger.info("[TTS] on_complete: 服务端通知合成完成！")
        # 实际播放完成由_playback_worker检测
        self.has_error = False

    def on_error(self, msg):
        """错误回调"""
        logger.error(f"[TTS] on_error: {msg}")
        self.has_error = True
        asyncio.create_task(self._set_completed_event())

    def on_close(self):
        """连接关闭时清理资源"""
        logger.info("[TTS] on_close: 已触发")
        self.close()

    async def _playback_worker(self):
        try:
            while True:
                # 检查stream是否已经关闭
                if not self.stream:
                    logger.info("音频流已关闭，播放工作线程退出")
                    break

                if self.audio_buffer:
                    data = self.audio_buffer.popleft()  # 从左边取数据
                    try:
                        self.playing = True
                        if self.stream:  # 再次检查stream是否存在
                            self.stream.write(data)
                            self.bytes_played += len(data)

                            # 检查是否播放完成
                            if self._is_playback_complete():
                                logger.info("音频播放完成，设置完成事件")
                                await self._set_completed_event()
                    except Exception as e:
                        logger.error(f"播放音频块时出错: {e}")
                        self.playing = False
                else:
                    await asyncio.sleep(0.01)

                    # 超时保护：如果长时间没有新数据且已收到 on_complete，则强制完成
                    if self._is_playback_stalled():
                        # logger.warning("检测到播放停滞，强制完成")
                        await self._set_completed_event()
                        # 不要 break，继续运行以处理后续音频
        except asyncio.CancelledError:
            logger.info("播放工作线程被取消")
        except Exception as e:
            logger.error(f"播放工作线程异常: {e}")
        finally:
            self.playing = False

    def _is_playback_complete(self) -> bool:
        if not self.stream:
            return False
        # 打印关键变量，帮助定位
        # write_available = self.stream.get_write_available()
        # logger.info(f"播放状态检查: 已写入={self.bytes_played}, 总计={self.total_bytes_received}, "
        #              f"可用帧数={write_available}, 总容量={self.frames_per_buffer}, "
        #              f"队列长度={len(self.audio_buffer)}")

        all_data_written = (self.bytes_played >= self.total_bytes_received)
        queue_empty = (len(self.audio_buffer) == 0)
        # 调整判断逻辑：当所有数据都已写入且队列为空时，认为播放完成
        # 不再严格要求 stream 完全为空，因为音频设备可能还有少量缓冲
        # logger.info(f"all_data_written: {all_data_written}, queue_empty: {queue_empty}")

        return all_data_written and queue_empty

    def _is_playback_stalled(self) -> bool:
        """检查播放是否停滞（超时保护）"""
        # 如果已经收到 on_complete 且所有数据已写入，但播放仍未完成
        # 或超过 30 秒无新数据，可视为停滞
        if self.total_bytes_received > 0 and len(self.audio_buffer) == 0:
            # 所有数据已接收且队列为空，认为播放已完成
            return True
        return False

    def close(self):
        # 取消播放任务
        if self.playback_task:
            self.playback_task.cancel()
            logger.info("播放任务已取消")

        # 保存当前的stream和p引用
        stream = self.stream
        p = self.p

        # 立即设置为None，避免重复关闭
        self.stream = None
        self.p = None

        if stream and p:
            try:
                # 给设备一点时间完成播放
                time.sleep(0.1)
                close_audio_stream(p, stream)
                logger.info("音频流和播放器已关闭")
            except Exception as e:
                logger.error(f"关闭音频流时出错: {e}")
        else:
            logger.info("音频流和播放器已关闭，跳过重复关闭")

    async def _set_completed_event(self):
        self.play_completed.set()


class TTSLiveService:
    """TTS实时服务类，负责管理流式语音合成和播放"""

    def __init__(self, session_id: str):
        """初始化TTS服务

        Args:
            session_id: 会话ID，用于日志跟踪
        """
        self.session_id = session_id
        self.callback = TTSStreamCallback(self)
        self.synthesizer = None
        # 初始化队列：按优先级排序的互动队列和循环播报队列
        self.mandatory_queue = asyncio.Queue()  # 必播句队列
        self.important_queue = asyncio.Queue()  # 重要句队列
        self.normal_queue = asyncio.Queue()  # 一般句队列
        self.loop_queue = asyncio.Queue()  # 循环播报队列
        # 消费任务
        self.consumer_task = None

    def _init_synthesizer(self):
        """初始化synthesizer实例"""
        logger.info(f"会话{self.session_id}初始化TTS synthesizer")
        try:
            self.callback = TTSStreamCallback(self)
            self.synthesizer = SpeechSynthesizer(
                model=config["tts"]["model_name"],
                voice=config["tts"]["voice_id"],
                format=AudioFormat.PCM_22050HZ_MONO_16BIT,  # 流式调用推荐格式
                speech_rate=config["tts"]["speech_rate"],
                pitch_rate=config["tts"]["pitch_rate"],
                callback=self.callback,
                instruction=TTS_INSTRUCTION
            )
            logger.info(f"会话{self.session_id}TTS synthesizer初始化成功")
        except Exception as e:
            logger.error(f"初始化TTS synthesizer失败: {e}")
            raise

    async def start_streaming(self):
        """开始流式合成会话，带重试机制"""
        logger.info(f"会话{self.session_id}开始流式合成会话")
        self._close_synthesizer()

        max_retries = 3
        retry_delay = 1.0  # 重试延迟（秒）

        for retry in range(max_retries):
            try:
                self._init_synthesizer()
                self.synthesizer.streaming_call(" ")
                await asyncio.sleep(0.5)

                logger.info(f"会话{self.session_id}TTS synthesizer启动成功（第{retry + 1}次尝试）")
                return
            except Exception as e:
                logger.error(f"启动TTS synthesizer失败（尝试 {retry + 1}/{max_retries}）: {traceback.print_exc()}")
                if retry < max_retries - 1:
                    await asyncio.sleep(retry_delay * (retry + 1))  # 指数退避
                else:
                    raise Exception(f"无法启动TTS synthesizer，尝试{max_retries}次后失败") from e

    async def _process_queue(self):
        """处理队列中的文本，按优先级处理"""
        while True:
            # 按优先级检查队列
            if not self.mandatory_queue.empty():
                sentence = await self.mandatory_queue.get()
                logger.info(f"当前必播句队列大小: {self.mandatory_queue.qsize()}，处理队列信息: {sentence}")
            elif not self.important_queue.empty():
                sentence = await self.important_queue.get()
                logger.info(f"当前重要句队列大小: {self.important_queue.qsize()}，处理队列信息: {sentence}")
            elif not self.normal_queue.empty():
                sentence = await self.normal_queue.get()
                logger.info(f"当前一般句队列大小: {self.normal_queue.qsize()}，处理队列信息: {sentence}")
            elif not self.loop_queue.empty():
                sentence = await self.loop_queue.get()
                logger.info(f"当前循环播报队列大小: {self.loop_queue.qsize()}，处理队列信息: {sentence}")
            else:
                # 所有队列都为空，等待新任务
                await asyncio.sleep(0.1)
                continue

            # 确保synthesizer已初始化并启动
            if not self.synthesizer or (hasattr(self.synthesizer, 'ws') and not self.synthesizer.ws):
                logger.info("TTS synthesizer未启动，正在启动")
                try:
                    await self.start_streaming()
                except Exception as e:
                    logger.error(f"启动TTS synthesizer时出错: {e}")
                    continue

            # 重置播放完成事件和播放状态
            self.callback.play_completed.clear()
            # 重置播放状态变量，确保新的音频播放从0开始计数
            self.callback.bytes_played = 0
            self.callback.total_bytes_received = 0

            # 流式发送文本
            logger.debug(f"发送文本块: {sentence[:20]}...")
            try:
                self.synthesizer.streaming_call(sentence)
                await asyncio.sleep(0.1)
                try:
                    await asyncio.wait_for(self.callback.play_completed.wait(), timeout=15.0)
                    self.callback.play_completed.clear()
                except asyncio.TimeoutError:
                    logger.warning(f"文本播放超时: {sentence[:20]}...")
            except Exception as e:
                import traceback
                logger.error(f"发送文本块时出错: {traceback.print_exc()}")
                # 尝试重新启动并发送
                try:
                    await self.start_streaming()
                    # 重置播放完成事件和播放状态
                    self.callback.play_completed.clear()
                    self.callback.bytes_played = 0
                    self.callback.total_bytes_received = 0
                    self.synthesizer.streaming_call(sentence)
                    await asyncio.sleep(0.1)
                    try:
                        await asyncio.wait_for(self.callback.play_completed.wait(), timeout=30.0)
                        logger.info("重新启动后文本播放完成")
                    except asyncio.TimeoutError:
                        logger.warning("重新启动后文本播放超时")
                except Exception as e2:
                    logger.error(f"重新启动后发送文本仍出错: {e2}")

    async def _check_connection_health(self):
        """定期检查连接健康状态"""
        while True:
            if self.synthesizer:
                try:
                    # 检查WebSocket连接是否活跃
                    if hasattr(self.synthesizer, 'ws') and self.synthesizer.ws:
                        if not (self.synthesizer.ws.sock and self.synthesizer.ws.sock.connected):
                            logger.warning("检测到WebSocket连接断开，重新初始化")
                            self._close_synthesizer()
                    else:
                        logger.warning("synthesizer.ws 不存在，重新初始化")
                        self._close_synthesizer()
                except Exception as e:
                    logger.error(f"检查连接健康状态时出错: {e}")
                    self._close_synthesizer()

            await asyncio.sleep(5.0)  # 每5秒检查一次

    async def start_consumer(self):
        """启动队列消费者任务"""
        if self.consumer_task is None or self.consumer_task.done():
            await self.start_streaming()
            self.consumer_task = asyncio.create_task(self._process_queue())
            asyncio.create_task(self._check_connection_health())
            logger.info(f"会话{self.session_id}TTS队列消费者和健康检查已启动")

    def add_to_queue(self, sentence: str, level: str = "normal"):
        """根据等级添加文本到相应队列

        Args:
            sentence: 要合成的文本
            level: 句子等级：mandatory（必播）、important（重要）、normal（一般）
        """
        if sentence:
            if level == "mandatory":
                self.mandatory_queue.put_nowait(sentence)
                logger.info(f"推送必播句队列成功，当前队列大小: {self.mandatory_queue.qsize()}")
            elif level == "important":
                self.important_queue.put_nowait(sentence)
                logger.info(f"推送重要句队列成功，当前队列大小: {self.important_queue.qsize()}")
            else:
                self.normal_queue.put_nowait(sentence)
                logger.info(f"推送一般句队列成功，当前队列大小: {self.normal_queue.qsize()}")

    def add_to_interact_queue(self, sentence: str):
        """添加文本到观众交互队列

        Args:
            sentence: 要合成的文本
        """
        if sentence:
            self.interact_queue.put_nowait(sentence)
            logger.info(f"推送观众交互队列成功，当前队列大小: {self.interact_queue.qsize()}")

    def add_to_loop_queue(self, sentence: str, cycle_count: int):
        """添加文本到循环播报队列

        Args:
            sentence: 要合成的文本
            cycle_count: 当前轮次，用于区分不同轮次的播报
        """
        if sentence:
            self.loop_queue.put_nowait(sentence)
            logger.info(f"当前第{cycle_count}轮次循环生成文本添加到播报队列成功，当前队列大小: {self.loop_queue.qsize()}")

    def get_loop_queue_size(self):
        """获取循环播报队列大小

        Returns:
            int: 队列大小
        """
        return self.loop_queue.qsize()

    def clear_loop_queue(self):
        """清空循环播报队列"""
        while not self.loop_queue.empty():
            try:
                self.loop_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info(f"会话{self.session_id}循环播报队列已清空")

    def clear_interact_queues(self):
        """清空所有互动队列"""
        # 清空必播句队列（实际上不应该清空，因为必播句必须播完）
        # 清空重要句队列
        while not self.important_queue.empty():
            try:
                self.important_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        # 清空一般句队列
        while not self.normal_queue.empty():
            try:
                self.normal_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info(f"会话{self.session_id}互动队列已清空")

    async def complete_streaming(self):
        """完成当前轮次的流式合成会话"""
        if self.synthesizer:
            try:
                # 检查synthesizer是否处于活跃状态
                if hasattr(self.synthesizer, 'ws') and self.synthesizer.ws:
                    self.synthesizer.streaming_complete()
                    logger.info(f"语音合成完成. Request ID: {self.synthesizer.get_last_request_id()}")
                else:
                    logger.info("TTS synthesizer未启动，跳过streaming_complete")
            except Exception as e:
                logger.error(f"调用streaming_complete时出错: {e}")

    def _close_synthesizer(self):
        """安全关闭synthesizer连接并清理资源"""
        try:
            if self.synthesizer:
                try:
                    if hasattr(self.synthesizer, 'ws') and self.synthesizer.ws:
                        self.synthesizer.streaming_cancel()  # 立即取消
                except Exception as e:
                    logger.debug(f"取消当前任务时出错: {e}")

                try:
                    self.synthesizer.close()
                    logger.info("TTS synthesizer连接已关闭")
                except Exception as e:
                    logger.warning(f"关闭synthesizer连接时出错: {e}")

                if self.callback:
                    self.callback.play_completed.clear()
                    self.callback.has_error = False
        except Exception as e:
            logger.error(f"清理synthesizer资源时出错: {e}")
        finally:
            self.synthesizer = None

    def close(self):
        """关闭TTS服务，清理所有资源"""
        # 取消消费者任务
        if self.consumer_task:
            self.consumer_task.cancel()
            logger.info("TTS队列消费者任务已取消")
        # 完成当前轮次的流式合成
        if self.synthesizer:
            try:
                if hasattr(self.synthesizer, 'ws') and self.synthesizer.ws:
                    self.synthesizer.streaming_complete()
            except Exception as e:
                logger.error(f"关闭前完成流式合成时出错: {e}")
        # 关闭synthesizer连接
        self._close_synthesizer()
        # 关闭音频回调
        self.callback.close()
        logger.info(f"会话{self.session_id}TTS服务已关闭")
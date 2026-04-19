# -*- coding: utf-8 -*-
"""
CosyVoice流式TTS服务
满足：实时流式播放、自然中断、克隆音色、回调接口
音频通过 WebSocket 流式传输到前端，不再使用 PyAudio 本地播放
"""
import asyncio
import traceback
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat, ResultCallback
from yaml import safe_load
from config.prompts import TTS_INSTRUCTION
from utils.logger import logger

# 加载配置
with open("./config/config.yaml", "r", encoding="utf-8") as f:
    config = safe_load(f)



# 22050Hz 单声道 16-bit PCM：每秒字节数 = 22050 * 2
_PCM_BYTES_PER_SEC = 44100


class TTSStreamCallback(ResultCallback):
    """TTS流式回调：将音频数据通过 WebSocket 广播到前端"""

    def __init__(self, tts_service, audio_broadcast_fn=None):
        self.playing = False
        self.tts_service = tts_service
        self.play_completed = asyncio.Event()
        self.has_error = False
        self.total_bytes_received = 0
        # 由 TTSLiveService 提供的异步广播函数 async def(data: bytes) -> None
        self.audio_broadcast_fn = audio_broadcast_fn
        self._complete_timer_task = None

    def on_open(self):
        """TTS WebSocket 连接打开"""
        logger.info("TTS WebSocket连接已打开")

    def on_data(self, data: bytes):
        """接收音频数据 — 广播给所有前端 WebSocket 客户端"""
        logger.debug(f"[TTS] on_data: 接收音频块，大小: {len(data)} 字节")
        self.playing = True
        self.total_bytes_received += len(data)
        if self.audio_broadcast_fn:
            asyncio.create_task(self.audio_broadcast_fn(data))

    def on_complete(self):
        """合成完成 — 按音频时长估算播放完成时间"""
        logger.info("[TTS] on_complete: 服务端通知合成完成！")
        self.has_error = False
        # 估算播放时长（秒）；额外留 0.3s 缓冲
        duration = self.total_bytes_received / _PCM_BYTES_PER_SEC + 0.3
        if self._complete_timer_task and not self._complete_timer_task.done():
            self._complete_timer_task.cancel()
        self._complete_timer_task = asyncio.create_task(self._delayed_complete(duration))

    async def _delayed_complete(self, delay: float):
        try:
            await asyncio.sleep(delay)
            self.playing = False
            self.play_completed.set()
            logger.info(f"[TTS] 估算播放完成（延迟 {delay:.2f}s）")
        except asyncio.CancelledError:
            pass

    def on_error(self, msg):
        """错误回调"""
        logger.error(f"[TTS] on_error: {msg}")
        self.has_error = True
        self.playing = False
        self.close()
        if self.tts_service:
            logger.info("通知 TTSLiveService 重启流式播报")
            self.play_completed.set()

    def on_close(self):
        """连接关闭"""
        logger.info("[TTS] on_close: 已触发")
        self.close()

    def close(self):
        """清理回调资源"""
        if self._complete_timer_task and not self._complete_timer_task.done():
            self._complete_timer_task.cancel()
        self.playing = False
        logger.info("[TTS] TTSStreamCallback 已关闭")

    async def _set_completed_event(self):
        self.play_completed.set()


class TTSLiveService:
    """TTS实时服务类，负责管理流式语音合成和音频 WebSocket 广播"""

    def __init__(self, session_id: str, room_config: dict = None, audio_broadcast_fn=None):
        """初始化TTS服务

        Args:
            session_id: 会话ID，用于日志跟踪
            room_config: 直播间配置，用于覆盖 TTS 参数
            audio_broadcast_fn: 异步函数 async def(data: bytes)，将 PCM 音频广播到前端 WebSocket
        """
        rc = room_config or {}
        self.session_id = session_id
        self.tts_enabled = True
        self.tts_model_name = rc.get("ttsModelName") or config["tts"]["model_name"]
        self.tts_profiles = rc.get("ttsProfiles") or []
        self.current_profile_index = 0  # 当前激活的 profile 索引，用于配置更新时保持语速/音调
        first = self.tts_profiles[0] if self.tts_profiles else {}
        self.tts_voice_id = first.get("voiceId") or config["tts"]["voice_id"]
        self.tts_speech_rate = float(first.get("speechRate") or config["tts"]["speech_rate"])
        self.tts_pitch_rate = float(first.get("pitchRate") or config["tts"]["pitch_rate"])
        self.tts_instruction = rc.get("ttsInstruction") or TTS_INSTRUCTION
        self.audio_broadcast_fn = audio_broadcast_fn
        self.callback = TTSStreamCallback(self, audio_broadcast_fn=audio_broadcast_fn)
        self.synthesizer = None
        # 以下是互动弹幕队列
        self.mandatory_queue = asyncio.Queue()  # 必播句队列
        self.important_queue = asyncio.Queue()  # 重要句队列
        self.normal_queue = asyncio.Queue()  # 一般句队列
        # 以下是循环播报队列
        self.loop_queue = asyncio.Queue()  # 循环播报队列
        # 过渡句子，优先级低于mandatory但高于important
        self.transitional_sentence = ""
        # 消费任务
        self.consumer_task = None

    def _init_synthesizer(self):
        """初始化synthesizer实例"""
        logger.info(f"会话{self.session_id}初始化TTS synthesizer")
        try:
            self.callback = TTSStreamCallback(self, audio_broadcast_fn=self.audio_broadcast_fn)
            self.synthesizer = SpeechSynthesizer(
                model=self.tts_model_name,
                voice=self.tts_voice_id,
                format=AudioFormat.PCM_22050HZ_MONO_16BIT,
                speech_rate=self.tts_speech_rate,
                pitch_rate=self.tts_pitch_rate,
                callback=self.callback,
                instruction=self.tts_instruction
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
                logger.info(f"当前队列大小: {self.mandatory_queue.qsize()}，【必播句】tts播报句子内容: {sentence}")
            elif self.transitional_sentence:
                sentence = self.transitional_sentence
                self.transitional_sentence = ""
                logger.info(f"【重要过渡句】tts播报句子内容: {sentence}")
            elif not self.important_queue.empty():
                sentence = await self.important_queue.get()
                logger.info(f"当前队列大小: {self.important_queue.qsize()}，【重要句】tts播报句子内容: {sentence}")
            elif not self.normal_queue.empty():
                sentence = await self.normal_queue.get()
                logger.info(f"当前队列大小: {self.normal_queue.qsize()}，【一般句】tts播报句子内容: {sentence}")
            elif not self.loop_queue.empty():
                sentence = await self.loop_queue.get()
                logger.info(f"当前队列大小: {self.loop_queue.qsize()}，【循环播报】tts播报句子内容: {sentence}")
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

            # 重置播放完成事件和字节计数（用于估算播放时长）
            self.callback.play_completed.clear()
            self.callback.total_bytes_received = 0
            self.callback.playing = False

            # 流式发送文本
            logger.debug(f"发送文本块: {sentence[:20]}...")
            try:
                self.synthesizer.streaming_call(sentence)
                await asyncio.sleep(0.1)
                try:
                    await asyncio.wait_for(self.callback.play_completed.wait(), timeout=15.0)
                    # 检查是否有错误发生
                    if self.callback.has_error:
                        logger.warning("检测到TTS错误，准备重启流式播报")
                        # 重置错误标志
                        self.callback.has_error = False
                        # 重新启动流式播报
                        await self.start_streaming()
                    self.callback.play_completed.clear()
                except asyncio.TimeoutError:
                    logger.warning(f"文本播放超时: {sentence[:20]}...")
                    # 超时也视为错误，重启流式播报
                    await self.start_streaming()
            except Exception as e:
                import traceback
                logger.error(f"发送文本块时出错: {traceback.print_exc()}")
                # 尝试重新启动并发送
                try:
                    await self.start_streaming()
                    self.callback.play_completed.clear()
                    self.callback.total_bytes_received = 0
                    self.callback.playing = False
                    self.synthesizer.streaming_call(sentence)
                    await asyncio.sleep(0.1)
                    try:
                        await asyncio.wait_for(self.callback.play_completed.wait(), timeout=15.0)
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

    def add_to_danmu_queue(self, sentence: str, level: str = "normal"):
        """根据等级添加文本到互动弹幕相应队列
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

    def add_to_loop_queue(self, sentence: str, cycle_count: int):
        """添加文本到循环播报队列

        Args:
            sentence: 要合成的文本
            cycle_count: 当前轮次，用于区分不同轮次的播报
        """
        if sentence:
            self.loop_queue.put_nowait(sentence)
            logger.info(
                f"当前第{cycle_count}轮次循环生成文本添加到播报队列成功，当前队列大小: {self.loop_queue.qsize()}")

    def get_loop_queue_size(self):
        """获取循环播报队列大小

        Returns:
            int: 队列大小
        """
        return self.loop_queue.qsize()

    def is_prepare_loop(self):
        """判断 loop_queue 队列为空且交互队列的元素总和为 1
        Returns:
            bool: 是否准备开始循环播报
        """
        # 检查 loop_queue 是否为空
        loop_queue_empty = self.loop_queue.empty()

        # 计算交互队列元素总和
        interact_queue_sum = (
                self.mandatory_queue.qsize() +
                self.important_queue.qsize() +
                self.normal_queue.qsize()
        )
        if interact_queue_sum == 1 and not loop_queue_empty:
            logger.warning(f"会话{self.session_id}检测到交互队列总和为1，但循环播报队列不为空，请检查代码逻辑")

        # 检查是否满足条件
        return loop_queue_empty and interact_queue_sum <= 1

    def clear_loop_queue(self):
        """清空循环播报队列"""
        while not self.loop_queue.empty():
            try:
                self.loop_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info(f"会话{self.session_id}循环播报队列已清空")

    async def clear_interact_queues(self, clear_important=True, clear_normal=True):
        """清空互动队列

        Args:
            clear_important: 是否清空重要句队列
            clear_normal: 是否清空一般句队列
        """
        # 清空重要句队列
        if clear_important:
            while not self.important_queue.empty():
                try:
                    self.important_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            logger.info(f"会话{self.session_id}重要句队列已清空")
        # 清空一般句队列
        if clear_normal:
            while not self.normal_queue.empty():
                try:
                    self.normal_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            logger.info(f"会话{self.session_id}一般句队列已清空")

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

    def update_config(self, room_config: dict):
        """更新服务配置（保留当前激活的 profile 索引，不重置语速/音调）

        Args:
            room_config: 新的直播间配置
        """
        rc = room_config or {}
        self.tts_enabled = True
        self.tts_model_name = rc.get("ttsModelName") or config["tts"]["model_name"]
        self.tts_profiles = rc.get("ttsProfiles") or []
        # 保留直播中当前激活的 profile，防止切换后配置热更新把语速/音调重置为 profile 0
        idx = self.current_profile_index if self.current_profile_index < len(self.tts_profiles) else 0
        active = self.tts_profiles[idx] if self.tts_profiles else {}
        self.tts_voice_id = active.get("voiceId") or config["tts"]["voice_id"]
        self.tts_speech_rate = float(active.get("speechRate") or config["tts"]["speech_rate"])
        self.tts_pitch_rate = float(active.get("pitchRate") or config["tts"]["pitch_rate"])
        self.tts_instruction = rc.get("ttsInstruction") or TTS_INSTRUCTION

        # 重新初始化synthesizer以应用新配置，但要确保当前播报完成
        async def update_synthesizer():
            # 检查是否正在播报
            if self.callback and self.callback.playing:
                logger.info("当前正在TTS播报，等待播报完成后再更新配置")
                # 等待当前播报完成
                try:
                    await asyncio.wait_for(self.callback.play_completed.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    logger.warning("等待播报完成超时，强制更新配置")

            # 关闭并重新初始化synthesizer
            if self.synthesizer:
                self._close_synthesizer()
                if self.tts_enabled:
                    await self.start_streaming()
            elif self.tts_enabled:
                # 如果之前没有synthesizer但现在启用了TTS
                await self.start_streaming()

            logger.info(f"TTSLiveService配置已更新")

        # 异步执行更新
        asyncio.create_task(update_synthesizer())

    def switch_voice_by_profile(self, index: int):
        """按 profile 索引切换音色（传输原始 DashScope voice ID，不依赖前端解析）"""
        if index < 0 or index >= len(self.tts_profiles):
            logger.warning(f"会话{self.session_id} switch_voice_by_profile 索引越界: {index}，共 {len(self.tts_profiles)} 个 profile")
            return
        profile = self.tts_profiles[index]
        self.current_profile_index = index
        self.tts_voice_id = profile.get("voiceId") or config["tts"]["voice_id"]
        self.tts_speech_rate = float(profile.get("speechRate") or config["tts"]["speech_rate"])
        self.tts_pitch_rate = float(profile.get("pitchRate") or config["tts"]["pitch_rate"])
        logger.info(f"会话{self.session_id}切换到 profile[{index}]: voice={self.tts_voice_id} rate={self.tts_speech_rate} pitch={self.tts_pitch_rate}")

        async def do_switch():
            if self.callback and self.callback.playing:
                try:
                    await asyncio.wait_for(self.callback.play_completed.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    logger.warning("等待播报完成超时，强制切换音色")
            if self.synthesizer:
                self._close_synthesizer()
            await self.start_streaming()
            logger.info(f"会话{self.session_id}已完成切换到 profile[{index}]，voice={self.tts_voice_id}")

        asyncio.create_task(do_switch())

    def switch_voice(self, voice_id: str):
        """按 voice_id 切换（兼容旧接口，推荐改用 switch_voice_by_profile）"""
        profile = next(
            (p for p in self.tts_profiles if p.get("voiceId") == voice_id),
            None
        )
        self.tts_voice_id = voice_id
        if profile:
            idx = self.tts_profiles.index(profile)
            self.current_profile_index = idx
            self.tts_speech_rate = float(profile.get("speechRate") or config["tts"]["speech_rate"])
            self.tts_pitch_rate = float(profile.get("pitchRate") or config["tts"]["pitch_rate"])

        async def do_switch():
            if self.callback and self.callback.playing:
                try:
                    await asyncio.wait_for(self.callback.play_completed.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    logger.warning("等待播报完成超时，强制切换音色")
            if self.synthesizer:
                self._close_synthesizer()
            await self.start_streaming()
            logger.info(f"会话{self.session_id}已切换音色到 {voice_id}")

        asyncio.create_task(do_switch())
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
# DashScope 流式会话需在每段文本后结束输入，否则服务端不发 FINISHED，on_complete 不会触发
_TTS_STREAMING_COMPLETE_MS = 600_000


class TTSStreamCallback(ResultCallback):
    """TTS流式回调：将音频数据通过 WebSocket 广播到前端"""

    def __init__(self, tts_service, audio_broadcast_fn=None, main_loop=None):
        self.playing = False
        self.tts_service = tts_service
        self.play_completed = asyncio.Event()
        self.has_error = False
        self.total_bytes_received = 0
        # 由 TTSLiveService 提供的异步广播函数 async def(data: bytes) -> None
        self.audio_broadcast_fn = audio_broadcast_fn
        # DashScope 在独立线程回调；必须用主事件循环投递协程，不可 asyncio.create_task
        self._main_loop = main_loop
        self._complete_future = None

    def on_open(self):
        """TTS WebSocket 连接打开"""
        logger.info("TTS WebSocket连接已打开")

    def on_data(self, data: bytes):
        """接收音频数据 — 广播给所有前端 WebSocket 客户端"""
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
        """合成完成 — 按音频时长估算播放完成时间"""
        logger.info("[TTS] on_complete: 服务端通知合成完成！")
        self.has_error = False
        # 估算播放时长（秒）；额外留 0.3s 缓冲
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
        """错误回调"""
        logger.error(f"[TTS] on_error: {msg}")
        self.has_error = True
        self.playing = False
        self.close()
        if self.tts_service:
            logger.info("通知 TTSLiveService 重启流式播报")
            self.play_completed.set()

    def on_close(self):
        """连接关闭（SDK 在 on_complete 后立即调用 on_close；勿在此调用 self.close()，否则会取消
        _delayed_complete 任务，导致 play_completed 永远不触发）"""
        logger.info("[TTS] on_close: 已触发")

    def reset(self):
        """重置单句合成状态，在每句合成前调用（不替换回调实例，避免引用失效竞态）"""
        self.play_completed.clear()
        self.total_bytes_received = 0
        self.playing = False
        self.has_error = False
        if self._complete_future and not self._complete_future.done():
            self._complete_future.cancel()
        self._complete_future = None

    def close(self):
        """清理回调资源"""
        if self._complete_future and not self._complete_future.done():
            self._complete_future.cancel()
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
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._main_loop = None
        self.callback = TTSStreamCallback(
            self, audio_broadcast_fn=audio_broadcast_fn, main_loop=self._main_loop
        )
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
        """初始化synthesizer实例（复用同一 callback 实例，避免引用失效竞态）"""
        logger.info(
            f"会话{self.session_id}初始化TTS synthesizer "
            f"voice={self.tts_voice_id} rate={self.tts_speech_rate} pitch={self.tts_pitch_rate}"
        )
        try:
            try:
                self._main_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
            # 更新 callback 的主事件循环引用（如有变更），但不替换回调实例
            self.callback._main_loop = self._main_loop
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
                # 仅创建实例；首句 streaming_call 时再建连。避免 streaming_call(" ") 且不 complete 导致会话悬空。
                self._init_synthesizer()

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

            # 每段播完会置空 synthesizer；此处按需新建
            if not self.synthesizer:
                logger.info("TTS synthesizer未就绪，正在初始化")
                try:
                    await self.start_streaming()
                except Exception as e:
                    logger.error(f"启动TTS synthesizer时出错: {e}")
                    continue

            # 重置单句合成状态（复用同一 callback 实例）
            self.callback.reset()

            # 流式发送文本；必须 streaming_complete 结束本轮输入，服务端才会 FINISHED → on_complete
            logger.debug(f"发送文本块: {sentence[:20]}...")
            try:
                self.synthesizer.streaming_call(sentence)
                await asyncio.sleep(0.05)
                try:
                    await asyncio.to_thread(
                        self.synthesizer.streaming_complete,
                        _TTS_STREAMING_COMPLETE_MS,
                    )
                except Exception as ce:
                    logger.error(f"streaming_complete 失败: {ce}")
                    await self.start_streaming()
                    continue

                # 本轮合成已结束，释放实例以便下一句重新建连（complete 会关闭会话）
                self.synthesizer = None

                est_playback = max(
                    20.0,
                    self.callback.total_bytes_received / _PCM_BYTES_PER_SEC + 10.0,
                )
                wait_cap = min(300.0, est_playback)
                try:
                    await asyncio.wait_for(
                        self.callback.play_completed.wait(),
                        timeout=wait_cap,
                    )
                    # 检查是否有错误发生
                    if self.callback.has_error:
                        logger.warning("检测到TTS错误，准备重启流式播报")
                        self.callback.has_error = False
                        await self.start_streaming()
                    self.callback.play_completed.clear()
                except asyncio.TimeoutError:
                    logger.warning(f"文本播放超时（估算上限 {wait_cap:.1f}s）: {sentence[:20]}...")
                    await self.start_streaming()
            except Exception as e:
                logger.error(f"发送文本块时出错: {traceback.format_exc()}")
                self.synthesizer = None
                # 尝试重新启动并发送
                try:
                    await self.start_streaming()
                    self.callback.reset()
                    self.synthesizer.streaming_call(sentence)
                    await asyncio.sleep(0.05)
                    await asyncio.to_thread(
                        self.synthesizer.streaming_complete,
                        _TTS_STREAMING_COMPLETE_MS,
                    )
                    self.synthesizer = None
                    est_playback = max(
                        20.0,
                        self.callback.total_bytes_received / _PCM_BYTES_PER_SEC + 10.0,
                    )
                    wait_cap = min(300.0, est_playback)
                    try:
                        await asyncio.wait_for(
                            self.callback.play_completed.wait(),
                            timeout=wait_cap,
                        )
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
                    # 首句之前仅 _init，ws 可能尚未建立，属正常
                    if not getattr(self.synthesizer, "_is_started", False):
                        pass
                    elif hasattr(self.synthesizer, "ws") and self.synthesizer.ws:
                        if not (self.synthesizer.ws.sock and self.synthesizer.ws.sock.connected):
                            logger.warning("检测到WebSocket连接断开，重新初始化")
                            self._close_synthesizer()
                    else:
                        logger.warning("会话已标记开始但 ws 不存在，重新初始化")
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

        # 配置变量已同步更新；若当前无播报则立即关闭旧会话，下一句重建时自动应用新语速/音色
        if self.synthesizer and not (self.callback and self.callback.playing):
            self._close_synthesizer()
        logger.info(
            f"TTSLiveService配置已更新（下一句生效）："
            f"voice={self.tts_voice_id} rate={self.tts_speech_rate} pitch={self.tts_pitch_rate}"
        )

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
        # 变量已同步更新；若当前无播报则立即关闭旧会话，下一句重建时应用新音色/语速
        if self.synthesizer and not (self.callback and self.callback.playing):
            self._close_synthesizer()
        logger.info(
            f"会话{self.session_id}切换到 profile[{index}]（下一句生效）："
            f"voice={self.tts_voice_id} rate={self.tts_speech_rate} pitch={self.tts_pitch_rate}"
        )

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

        if self.synthesizer and not (self.callback and self.callback.playing):
            self._close_synthesizer()
        logger.info(f"会话{self.session_id}切换音色到 {voice_id}（下一句生效）")
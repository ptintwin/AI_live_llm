import os
import time
import json
import dashscope
import pyaudio
import contextlib
from dashscope.audio.tts_v2 import VoiceEnrollmentService, SpeechSynthesizer, ResultCallback, AudioFormat

# 全局配置（DashScope 凭据由 main 在调用前通过 utils.dashscope_runtime 设置）
TARGET_MODEL = "cosyvoice-v3.5-flash"
VOICE_PREFIX = "myvoice"  # 仅允许数字和小写字母，小于十个字符
AUDIO_URL = """https://lucastao.oss-cn-beijing.aliyuncs.com/voice-recorder-2026-03-21--06-34-45.wav?Expires=1774711953&OSSAccessKeyId=TMP.3Kz9xSgVH29HrtfYqR1oJH23C5T2ZvBNSEA2dYB8i7tNkeSyZBpHT1KBrXtH5eTpAbxCgu2xno4eSFbYxWweyFSVZcAoAG&Signature=i3intE1%2F8uzrbAMbXVpNCEIHmvE%3D"""
VOICE_JSON_PATH = "voice_ids.json"  # 保存voice_id的JSON文件路径


@contextlib.contextmanager
def timer(description="Operation"):
    """计时器上下文管理器"""
    start_time = time.time()
    try:
        yield
    finally:
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"{description} 执行耗时: {elapsed_time:.2f} 秒")


class MyCallback(ResultCallback):
    _player = None
    _stream = None

    def on_open(self):
        print("websocket is open.")
        self._player = pyaudio.PyAudio()
        self._stream = self._player.open(
            format=pyaudio.paInt16, channels=1, rate=22050, output=True
        )

    def on_data(self, data: bytes) -> None:
        print(f"收到音频块，大小: {len(data)} 字节")
        self._stream.write(data)

    def on_complete(self):
        print("语音合成完成")

    def on_error(self, message: str):
        print(f"合成错误: {message}")

    def on_close(self):
        print("连接关闭")
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._player:
            self._player.terminate()

# ===================== 核心函数封装 =====================
def create_voice(target_model: str, prefix: str, audio_url: str) -> str:
    """
    创建复刻音色（异步任务）
    :param target_model: 使用的模型名称
    :param prefix: 音色前缀
    :param audio_url: 公网可访问的音频URL
    :return: 生成的voice_id
    """
    print("--- Step 1: Creating voice enrollment ---")
    service = VoiceEnrollmentService()
    try:
        voice_id = service.create_voice(
            target_model=target_model,
            prefix=prefix,
            url=audio_url
        )
        print(f"Voice enrollment submitted successfully. Request ID: {service.get_last_request_id()}")
        print(f"Generated Voice ID: {voice_id}")
        return voice_id
    except Exception as e:
        print(f"Error during voice creation: {e}")
        raise e


def poll_voice_status(voice_id: str, max_attempts: int = 30, poll_interval: int = 10) -> None:
    """
    轮询查询音色状态，直到状态为OK或超时/失败
    :param voice_id: 要查询的voice_id
    :param max_attempts: 最大轮询次数
    :param poll_interval: 轮询间隔（秒）
    """
    print("\n--- Step 2: Polling for voice status ---")
    service = VoiceEnrollmentService()
    for attempt in range(max_attempts):
        try:
            voice_info = service.query_voice(voice_id=voice_id)
            status = voice_info.get("status")
            print(f"Attempt {attempt + 1}/{max_attempts}: Voice status is '{status}'")

            if status == "OK":
                print("Voice is ready for synthesis.")
                return
            elif status == "UNDEPLOYED":
                error_msg = f"Voice processing failed with status: {status}. Please check audio quality or contact support."
                print(error_msg)
                raise RuntimeError(error_msg)
            time.sleep(poll_interval)
        except Exception as e:
            print(f"Error during status polling: {e}")
            time.sleep(poll_interval)
    # 超时处理
    error_msg = "Polling timed out. The voice is not ready after several attempts."
    print(error_msg)
    raise RuntimeError(error_msg)


def synthesize_and_play_voice(target_model: str, voice_id: str, text_generator) -> None:
    """
    使用复刻音色合成语音，并基于pyaudio通过扬声器播放（流式处理）
    :param target_model: 使用的模型名称
    :param voice_id: 复刻的音色ID
    :param text_generator: 文本生成器，用于流式提供文本
    """
    print("\n--- Step 3: Synthesizing speech with the new voice ---")
    try:
        INSTRUCTION_PROMPT = "游戏直播风格，激情快节奏，不定时带自然停顿（<2s）和重复关键词，音量语速随语义起伏，模拟真人话筒讲解的直播氛围"
        with timer("语音合成"):
            callback = MyCallback()
            synthesizer = SpeechSynthesizer(
                model=target_model,
                voice=voice_id,
                format=AudioFormat.PCM_22050HZ_MONO_16BIT,  # 流式调用必须指定格式
                instruction=INSTRUCTION_PROMPT,
                callback=callback
            )

            # 流式处理文本输入
            for text_chunk in text_generator:
                if text_chunk:  # 跳过空文本块
                    synthesizer.streaming_call(text_chunk)
                    time.sleep(0.1)  # 控制发送速度，避免API限流

            synthesizer.streaming_complete()
            print(f"Speech synthesis successful. Request ID: {synthesizer.get_last_request_id()}")
    except Exception as e:
        print(f"Error during speech synthesis/playback: {e}")
        # 确保pyaudio资源释放
        if hasattr(MyCallback, '_stream') and MyCallback._stream:
            try:
                MyCallback._stream.stop_stream()
                MyCallback._stream.close()
            except:
                pass
        if hasattr(MyCallback, '_player') and MyCallback._player:
            try:
                MyCallback._player.terminate()
            except:
                pass
        raise e

def manage_voice_ids(use_voice_num: str) -> str:
    """
    管理voice_id的保存和读取逻辑
    :param use_voice_num: 超参数，可选值：clear / add / 数字key
    :return: 最终使用的voice_id
    """
    # 初始化JSON文件（如果不存在）
    if not os.path.exists(VOICE_JSON_PATH):
        with open(VOICE_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

    # 读取现有voice_ids
    with open(VOICE_JSON_PATH, 'r', encoding='utf-8') as f:
        voice_ids = json.load(f)

    if use_voice_num == "clear":
        # 重新创建音色并覆盖JSON文件
        voice_id = create_voice(TARGET_MODEL, VOICE_PREFIX, AUDIO_URL)
        poll_voice_status(voice_id)
        # 覆盖保存
        with open(VOICE_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump({"1": voice_id}, f, ensure_ascii=False, indent=2)
        print(f"已重新创建音色，voice_id已覆盖保存到{VOICE_JSON_PATH}")
        return voice_id

    elif use_voice_num == "add":
        # 递增生成新key（从1开始）
        existing_keys = [int(k) for k in voice_ids.keys()]
        new_key = str(max(existing_keys) + 1) if existing_keys else "1"
        # 创建新音色
        voice_id = create_voice(TARGET_MODEL, VOICE_PREFIX, AUDIO_URL)
        poll_voice_status(voice_id)
        # 添加到JSON
        voice_ids[new_key] = voice_id
        with open(VOICE_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(voice_ids, f, ensure_ascii=False, indent=2)
        print(f"已新增音色，key={new_key}，voice_id已保存到{VOICE_JSON_PATH}")
        return voice_id

    else:
        # 检查是否为数字key
        if use_voice_num.isdigit():
            if use_voice_num in voice_ids:
                return voice_ids[use_voice_num]
            else:
                raise ValueError(f"错误：JSON文件中不存在key={use_voice_num}的voice_id！")
        else:
            raise ValueError(f"错误：use_voice_num仅支持'clear'/'add'或数字key，当前值：{use_voice_num}")

def text_stream():
    texts = [
        "家人们，刚刚有兄弟问咋下载这游戏。",
        "你们直接在应用商店里搜这个游戏的名字就能找到啦,",
        "或者也可以点击我直播间下方的小窗链接",
        "点进去就能立马下载咯。",
        "赶紧上车，别错过这么好玩的仙侠手游呀！"
    ]
    for text in texts:
        yield text
        time.sleep(0.2)  # 模拟实时输入延迟


# ===================== 主程序入口 =====================
if __name__ == "__main__":
    # 超参数：可修改为 "clear" / "add" / 数字（如"1"）
    USE_VOICE_NUM = "add"  # 核心超参数，根据需求修改

    try:
        # 管理voice_id并获取最终使用的ID
        target_voice_id = manage_voice_ids(USE_VOICE_NUM)
        print(f"\n当前使用的voice_id: {target_voice_id}")

        # 合成并播放语音
        synthesize_and_play_voice(TARGET_MODEL, target_voice_id, text_stream())

    except Exception as e:
        print(f"程序执行失败：{e}")

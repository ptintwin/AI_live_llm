# -*- coding: utf-8 -*-
"""
服务主入口：FastAPI异步服务 + uvicorn启动
核心接口：start_stream / send_question / stop_session / health_check / shutdown
"""
import asyncio
import uuid
import os
import re
import traceback
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks
import uvicorn
from yaml import safe_load
from core.models import *
from core.danmu_service import DanmuService
from core.llm_service import LLMLiveService
from core.tts_service import TTSLiveService
from audio_design.voice_clone import create_voice, poll_voice_status
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
from utils.logger import logger
from utils.oss_utils import upload_to_oss

# 加载服务配置
with open("./config/config.yaml", "r", encoding="utf-8") as f:
    config = safe_load(f)

# 初始化FastAPI
app = FastAPI(title="抖音游戏主播直播互动系统", version="1.0")

# 全局会话管理（session_id: {llm, tts task}）
SESSIONS = {}

# ------------------- 核心接口 -------------------
@app.get("/health_check", summary="服务健康检查")
async def health_check():
    return {"status": "ok", "sessions_count": len(SESSIONS)}


@app.post("/start_stream", summary="开启流式直播讲解")
async def start_stream(req: StartStreamRequest, background_tasks: BackgroundTasks):
    # 生成唯一会话ID
    session_id = str(uuid.uuid4())
    logger.info(f"创建新会话：{session_id}，直播间：{req.room_id}")

    # 初始化核心服务
    llm_service = LLMLiveService(session_id, req.background)
    tts_service = TTSLiveService(session_id)

    # 后台任务：循环生成讲解+播放
    async def live_loop():
        try:
            # 启动TTS消费者任务
            if config["tts"]["enabled"]:
                await tts_service.start_consumer()
                # 等待TTS服务完全启动
                await asyncio.sleep(1.0)

            # 标记是否正在生成文本
            is_generating = False
            while session_id in SESSIONS:
                if llm_service.loop_interrupt_flag:
                    if llm_service.generation_type != "live_danmu" and tts_service.is_prepare_loop():
                        logger.info(f"会话{session_id}检测到交互队列总和为1且循环播报队列为空，开始生成循环文本")
                        llm_service.set_loop_interrupt(False)
                    else:
                        await asyncio.sleep(0.2)
                        continue

                # 检查循环播报队列大小，如果小于等于3且不在生成中，开始下一轮生成
                if config["tts"]["enabled"] and tts_service.get_loop_queue_size() <= 3 and not is_generating:
                    # 流式生成段落并添加到队列（异步非阻塞）
                    logger.info(f"会话{session_id}开始第 {llm_service.cycle_count + 1} 轮循环讲解")
                    # 实时流式生成句子并添加到队列
                    async for sentence in llm_service.generate_stream_paragraph():
                        _, sentence = DanmuService.extract_level_and_sentence(sentence, is_interact=False)

                        # 检查中断标志
                        if llm_service.loop_interrupt_flag:
                            logger.info(f"会话{session_id}检测到中断标志，停止当前轮次讲解")
                            break
                        # 添加到循环播报队列
                        if config["tts"]["enabled"]:
                            tts_service.add_to_loop_queue(sentence, llm_service.cycle_count)
                        else:
                            # 非TTS模式下直接显示
                            await asyncio.sleep(0.5)
                        # 检查中断标志，确保能够及时响应
                        if llm_service.loop_interrupt_flag:
                            logger.info(f"会话{session_id}检测到中断标志，停止当前轮次讲解")
                            break
        except Exception as e:
            logger.error(f"会话{session_id}直播循环异常：{traceback.format_exc()}")
        finally:
            await stop_session(StopSessionRequest(session_id=session_id))

    # 保存会话
    task = asyncio.create_task(live_loop())
    SESSIONS[session_id] = {
        "llm": llm_service,
        "tts": tts_service,
        "room_id": req.room_id,
        "danmu_cache": [],
        "task": task,
        "created_at": datetime.now()
    }

    return {"session_id": session_id, "status": "start success!"}


@app.post("/live_danmu", summary="直播间弹幕互动")
async def live_danmu(req: LiveDanmuRequest):
    session = SESSIONS.get(req.session_id)
    if not session:
        return {"error": "会话不存在"}

    try:
        llm: LLMLiveService = session["llm"]
        tts: TTSLiveService = session["tts"]
        danmu_service = DanmuService()

        llm.set_loop_interrupt(True)
        if llm.generation_type == "live_loop":
            llm.set_generation_type(None)

        is_danmu_llm_generating, has_interact_queue_items = danmu_service.check_live_danmu_in_progress(llm, tts)
        logger.info(f"当前是否有弹幕交互文本在生成: {is_danmu_llm_generating}, 当前弹幕交互队列是否有待播报句子: {has_interact_queue_items}")
        if not (is_danmu_llm_generating or has_interact_queue_items):
            logger.info("上一次live_danmu调用已执行完或首次执行，直接处理新弹幕")
            # 准备处理互动回复
            full_answer = ""
            loop_queue_cleared = False

            logger.info(f"开始处理弹幕请求：{req.danmu_list}")
            async for sentence in llm.handle_interact(req.danmu_list):
                if config["tts"]["enabled"]:
                    level, sentence = DanmuService.extract_level_and_sentence(sentence)

                    tts.add_to_danmu_queue(sentence, level)
                    if not loop_queue_cleared and not (tts.mandatory_queue.empty() and tts.important_queue.empty() and tts.normal_queue.empty()):
                        # 只有在互动队列不为空时才清空循环播报队列，避免两个队列都为空，播报停滞
                        tts.clear_loop_queue()
                        loop_queue_cleared = True
                else:
                    logger.info(f"互动回复: {sentence}")

                full_answer += sentence

            return {"session_id": req.session_id, "answer": full_answer}
        else:
            logger.info("上一次live_danmu调用还未执行完，做进一步弹幕交互处理...")
            # 处理弹幕等级分类和缓存更新
            session["danmu_cache"] = await danmu_service.process_and_update_danmu(req.danmu_list, session["danmu_cache"])
            if is_danmu_llm_generating:
                return {"session_id": req.session_id, "answer": "上一轮互动弹幕文本正在生成中，已将当前弹幕缓存，稍后处理"}
            elif has_interact_queue_items:
                logger.info(f"当前上一轮互动弹幕文本生成已完成，开始处理最新danmu_cache弹幕请求：{session['danmu_cache']}")
                max_level = DanmuService.get_max_level(session["danmu_cache"])
                full_answer = await danmu_service.handle_danmu_queues(max_level, session["danmu_cache"], llm, tts)

                return {"session_id": req.session_id, "answer": full_answer}
    except Exception as e:
        logger.error(f"会话{req.session_id}处理弹幕互动异常：{traceback.print_exc()}")


@app.post("/switch_voice_role", summary="切换到某个声音角色")
async def switch_voice_role(req: SwitchVoiceRoleRequest):
    session = SESSIONS.get(req.session_id)
    if not session:
        return {"error": "会话不存在"}

    return {"session_id": req.session_id, "status": "switch success!"}


@app.get("/list_sessions", summary="查询所有活跃会话")
async def list_sessions():
    """查询所有活跃会话"""
    sessions_info = []
    for sid, data in SESSIONS.items():
        sessions_info.append({
            "session_id": sid,
            "room_id": data.get("room_id"),
            "created_at": data.get("created_at")
        })
    return {"sessions": sessions_info, "count": len(sessions_info)}


@app.post("/stop_session", summary="停止指定会话")
async def stop_session(req: StopSessionRequest):
    session = SESSIONS.pop(req.session_id, None)
    if not session:
        return {"error": "会话不存在"}

    # 清理资源
    session["task"].cancel()
    session["tts"].close()
    logger.info(f"会话{req.session_id}已停止并清理")
    return {"session_id": req.session_id, "status": "stopped"}


@app.get("/shutdown_all", summary="关闭所有会话")
async def shutdown_all_sessions():
    """关闭所有会话"""
    logger.info("开始关闭所有会话...")
    for session_id in list(SESSIONS.keys()):
        await stop_session(StopSessionRequest(session_id=session_id))
    logger.info("所有会话已关闭完成")
    return {"status": "success", "message": "所有会话已关闭"}


@app.post("/voice_clone", summary="语音克隆")
async def voice_clone(req: VoiceCloneRequest):
    """
    语音克隆接口
    入参：一段已经提前录制好的.wav远程文件url（阿里云OSS录制音频文件地址）
    出参：返回已克隆的voice_id
    """
    try:
        logger.info(f"开始语音克隆，音频URL: {req.audio_url}")

        # 调用语音克隆功能
        voice_id = create_voice(config["tts"]["model_name"], "myvoice", req.audio_url)
        logger.info(f"语音克隆请求提交成功，voice_id: {voice_id}")

        # 轮询查询音色状态
        await asyncio.to_thread(poll_voice_status, voice_id)
        logger.info(f"语音克隆完成，voice_id: {voice_id}")

        return {"voice_id": voice_id, "status": "success"}
    except Exception as e:
        logger.error(f"语音克隆失败: {e}")
        return {"error": str(e), "status": "failed"}


@app.post("/tts_synthesis", summary="语音合成")
async def tts_synthesis(req: TTSRequest):
    """
    语音合成接口
    入参：voice_id、instruction效果指令（可选）、text需要播报的文字内容（可选）
    出参：生成一段声音合成的.wav音频文件并保存到本地文件夹，返回该绝对路径
    """
    try:
        logger.info(f"开始语音合成，voice_id: {req.voice_id}")

        if not req.text:
            req.text = "恭喜，已成功复刻并合成了属于自己的声音，你觉得听起来怎么样？"

        output_dir = os.path.join(os.getcwd(), "audio_output")
        os.makedirs(output_dir, exist_ok=True)

        # 生成输出文件路径（包含时间戳，精确到秒）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file_name = f"tts_output_{timestamp}_{uuid.uuid4()}.wav"
        output_file = os.path.join(output_dir, output_file_name)

        # 构建synthesizer参数
        synthesizer_kwargs = {
            "model": config["tts"]["model_name"],
            "voice": req.voice_id,
            "format": AudioFormat.WAV_22050HZ_MONO_16BIT,
            "speech_rate": req.speech_rate,
            "pitch_rate": req.pitch_rate
        }
        if req.instruction:
            synthesizer_kwargs["instruction"] = req.instruction

        synthesizer = SpeechSynthesizer(**synthesizer_kwargs)
        audio_data = synthesizer.call(req.text)
        logger.info(f"语音合成成功，Request ID: {synthesizer.get_last_request_id()}")

        # 初始化返回结果
        result = {"status": "success"}

        if req.save_mode == "local":
            # 本地存储模式：只保存到本地
            with open(output_file, "wb") as f:
                f.write(audio_data)
            logger.info(f"音频文件已保存到: {output_file}")
            result["audio_path"] = os.path.abspath(output_file)
        elif req.save_mode == "upload":
            # 上传模式：先保存到临时文件，上传后删除
            with open(output_file, "wb") as f:
                f.write(audio_data)
            try:
                oss_url = upload_to_oss(output_file, output_file_name)
                result["audio_url"] = oss_url
                logger.info(f"音频文件已上传到OSS: {oss_url}")
                # 上传成功后删除临时文件
                os.unlink(output_file)
                logger.info(f"临时文件已删除: {output_file}")
            except Exception as e:
                logger.error(f"上传到OSS失败: {e}")
                # 上传失败时保留本地文件并返回路径
                result["audio_path"] = os.path.abspath(output_file)
        else:
            raise ValueError("save_mode参数错误，必须为'local'或'upload'")

        return result
    except Exception as e:
        logger.error(f"出现异常: {e}")
        return {"error": str(e), "status": "failed"}


if __name__ == "__main__":
    uvicorn.run(
        app="main:app",
        host=config["server"]["host"],
        port=config["server"]["port"],
        log_level=config["server"]["log_level"],
        reload=False
    )
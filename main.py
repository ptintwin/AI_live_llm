# -*- coding: utf-8 -*-
"""
服务主入口：FastAPI异步服务 + uvicorn启动
核心接口：start_stream / send_question / stop_session / health_check / shutdown
"""
import asyncio
import json
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect, UploadFile, File, Form
import uvicorn
from yaml import safe_load
from core.models import (
    StartStreamRequest, LiveDanmuRequest, SwitchVoiceRoleRequest,
    SwitchVoiceProfileRequest, StopSessionRequest, UpdateConfigRequest,
    VoiceCloneRequest, TTSRequest, DanmuLevelRequest
)
from core.danmu_service import DanmuService
from core.llm_service import LLMLiveService
from core.tts_service import TTSLiveService
from audio_design.voice_clone import create_voice, poll_voice_status
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
from utils.logger import logger
from utils.oss_utils import upload_to_oss
from utils.dashscope_runtime import (
    apply_dashscope_from_room_config,
    merge_global_llm_into_room_config,
    redact_room_config_for_log,
)
from utils.spring_llm_config import (
    fetch_global_llm_settings,
    fetch_knowledge_qa_text,
    resolve_room_llm_config,
)
from core.rag import (
    get_rag_service,
    get_document_count,
    get_vector_store_status,
    reset_rag_service,
    reload_rag_config,
    reload_rag_config_async,
    load_rag_config_async,
    get_rag_config,
    clear_vector_store,
    reset_decider,
    retrieve_with_answers,
    should_use_rag,
    get_rag_decider,
    reset_embedding_model,
    reset_reranker_model,
)

# 加载服务配置
with open("./config/config.yaml", "r", encoding="utf-8") as f:
    config = safe_load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    await startup()
    yield
    shutdown()


async def startup():
    """应用启动时执行。

    §十二：先从 Spring 拉 cfg_rag（若可达）以让 embedding_model_path 等运行态值生效；
    随后预热 RAG 服务（此时加载的模型路径已是 Spring 回的最新值）。
    """
    try:
        await load_rag_config_async()
    except Exception as e:
        logger.error(f"启动时拉取 Spring RAG 配置失败，将使用本地 YAML 兜底: {traceback.print_exc()}")
    warmup_rag()


def shutdown():
    """应用关闭时执行"""
    pass


# 初始化FastAPI
app = FastAPI(title="抖音游戏主播直播互动系统", version="1.0", lifespan=lifespan)

# 全局会话管理（session_id: {llm, tts task, danmu_lock, danmu_task}）
SESSIONS = {}

# RAG服务预热标志
RAG_WARMED = False


def warmup_rag():
    """全局RAG服务预热"""
    global RAG_WARMED
    if RAG_WARMED:
        return
    try:
        rag_service = get_rag_service()
        doc_count = get_document_count()
        logger.info(f"RAG服务预热完成，向量库文档数量: {doc_count}")
        RAG_WARMED = True
    except Exception as e:
        logger.warning(f"RAG服务预热失败: {traceback.print_exc()}")
        RAG_WARMED = False


# 启动时预热RAG



SESSIONS = {}

# 音频 WebSocket 客户端管理（session_id: set of WebSocket）
AUDIO_CLIENTS: dict[str, set] = {}

# ------------------- 核心接口 -------------------
@app.get("/health_check", summary="服务健康检查")
async def health_check():
    return {"status": "ok", "sessions_count": len(SESSIONS)}


@app.websocket("/ws/audio/{session_id}")
async def audio_ws(websocket: WebSocket, session_id: str):
    """前端音频 WebSocket 连接 — 接收 TTS 生成的 PCM 音频流。LAN 部署，无鉴权。"""
    await websocket.accept()
    if session_id not in AUDIO_CLIENTS:
        AUDIO_CLIENTS[session_id] = set()
    AUDIO_CLIENTS[session_id].add(websocket)
    logger.info(f"会话{session_id}新增音频 WS 客户端，当前连接数: {len(AUDIO_CLIENTS[session_id])}")
    try:
        while True:
            # 保持连接，等待断开
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        AUDIO_CLIENTS.get(session_id, set()).discard(websocket)
        logger.info(f"会话{session_id}音频 WS 客户端断开，剩余连接数: {len(AUDIO_CLIENTS.get(session_id, set()))}")


@app.post("/start_stream", summary="开启流式直播讲解")
async def start_stream(req: StartStreamRequest, background_tasks: BackgroundTasks):
    if not req.session_id:
        session_id = str(uuid.uuid4())
        logger.info(f"前端未传入session_id，自主创建：{session_id}，直播间id：{req.room_id}")
    else:
        session_id = req.session_id
        logger.info(f"获取到前端传入session_id：{session_id}，直播间id：{req.room_id}")

    # 从 Spring 合并直播间与系统设置（含 DashScope API Key）
    room_config = await resolve_room_llm_config(req.room_id)
    apply_dashscope_from_room_config(room_config)
    if room_config:
        logger.info(f"room_config（脱敏）: {json.dumps(redact_room_config_for_log(room_config), indent=4, ensure_ascii=False)}")
    else:
        logger.warning("未获取到远端配置，将使用本地 config.yaml / prompts；DashScope 凭据依赖环境变量 DASHSCOPE_API_KEY")

    # 初始化音频 WS 客户端集合（前端 connect 时会自动加入）
    AUDIO_CLIENTS[session_id] = set()

    # 音频广播函数：将 PCM 数据推送给所有已连接的前端 WS 客户端
    async def audio_broadcast(data: bytes):
        clients = list(AUDIO_CLIENTS.get(session_id, set()))
        if not clients:
            # 若已无前端连接，向上层提示（避免出现"Python 一直发但无人听"的静默故障）
            logger.debug(f"会话{session_id} audio_broadcast 无活跃 WS 客户端，丢弃 {len(data)} 字节")
            return
        for ws in clients:
            try:
                await ws.send_bytes(data)
            except Exception as e:
                logger.error(
                    f"会话{session_id} 音频 WS 发送失败已剔除客户端 ({len(data)} 字节): {traceback.print_exc()}"
                )
                AUDIO_CLIENTS.get(session_id, set()).discard(ws)

    # 初始化核心服务（使用直播间专属配置）
    llm_service = LLMLiveService(session_id, room_config)
    tts_service = TTSLiveService(session_id, room_config, audio_broadcast_fn=audio_broadcast)

    # 后台任务：循环生成讲解+播放
    async def live_loop():
        try:
            # 启动TTS消费者任务
            if tts_service.tts_enabled:
                await tts_service.start_consumer()
                await asyncio.sleep(0.1)

            while session_id in SESSIONS:
                if llm_service.loop_interrupt_flag:
                    if llm_service.generation_type != "live_danmu" and tts_service.is_prepare_loop():
                        logger.info(f"会话{session_id}检测到交互队列总和为1且循环播报队列为空，开始生成循环文本")
                        llm_service.set_loop_interrupt(False)
                    else:
                        await asyncio.sleep(0.2)
                        continue

                if tts_service.tts_enabled and tts_service.get_loop_queue_size() <= 3:
                    # 流式生成段落并添加到队列（异步非阻塞）
                    logger.info(f"会话{session_id}开始第 {llm_service.cycle_count + 1} 轮循环讲解")
                    # 实时流式生成句子并添加到队列
                    async for sentence in llm_service.generate_stream_paragraph():
                        # 检查中断标志
                        if llm_service.loop_interrupt_flag:
                            logger.info(f"会话{session_id}检测到中断标志，停止当前轮次讲解")
                            break
                        # 添加到循环播报队列
                        if tts_service.tts_enabled:
                            tts_service.add_to_loop_queue(sentence, llm_service.cycle_count)
                        else:
                            # 非TTS模式下直接显示
                            await asyncio.sleep(0.5)
                        # 检查中断标志，确保能够及时响应
                        if llm_service.loop_interrupt_flag:
                            logger.info(f"会话{session_id}检测到中断标志，停止当前轮次讲解")
                            break
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.error(f"会话{session_id}直播循环异常: {traceback.print_exc()}")
        finally:
            await stop_session(StopSessionRequest(session_id=session_id))

    # 弹幕处理循环
    danmu_service = DanmuService(room_config)

    async def danmu_processing_loop():
        try:
            while session_id in SESSIONS:
                # §四.2 Bug-5：原 "check → release → reacquire → drain" 两阶段加锁在
                # 窗口内若有新弹幕入队，会把中断机会错过。改为单次持锁完成 check+drain。
                danmu_cache = []
                async with SESSIONS[session_id]["danmu_lock"]:
                    if SESSIONS[session_id]["danmu_cache"]:
                        danmu_cache = SESSIONS[session_id]["danmu_cache"]
                        SESSIONS[session_id]["danmu_cache"] = []

                if danmu_cache:
                    # 原子地拿到一批后再触发中断；中断信号对 live_loop 是幂等的
                    llm_service.set_loop_interrupt(True)
                    logger.info(f"会话{session_id}开始处理{len(danmu_cache)}条弹幕缓存：{danmu_cache}")

                    max_level = DanmuService.get_max_level(danmu_cache)
                    await danmu_service.handle_danmu_queues(max_level, danmu_cache, llm_service, tts_service)

                    logger.info(f"会话{session_id}弹幕处理完成")

                await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"会话{session_id}弹幕处理循环异常: {traceback.print_exc()}")
        finally:
            await stop_session(StopSessionRequest(session_id=session_id))

    # 保存会话
    task = asyncio.create_task(live_loop())
    danmu_task = asyncio.create_task(danmu_processing_loop())
    SESSIONS[session_id] = {
        "llm": llm_service,
        "tts": tts_service,
        "danmu_service": danmu_service,
        "room_id": req.room_id,
        "danmu_cache": [],
        "danmu_lock": asyncio.Lock(),
        "task": task,
        "danmu_task": danmu_task,
        "created_at": datetime.now()
    }

    return {"session_id": session_id, "status": "start success!"}


@app.post("/live_danmu", summary="直播间弹幕互动")
async def live_danmu(req: LiveDanmuRequest, background_tasks: BackgroundTasks):
    session = SESSIONS.get(req.session_id)
    if not session:
        return {"error": "会话不存在"}

    try:
        # 立即返回，弹幕处理在后台进行
        logger.info(f"开始处理弹幕等级分类，原始弹幕数量: {len(req.danmu_list)}")

        # 后台任务处理弹幕等级识别和缓存更新
        async def process_danmu_background():
            try:
                # 处理弹幕（使用会话绑定的 danmu_service 实例）
                processed_danmu_list = await session["danmu_service"].process_danmu(req.danmu_list)
                logger.info(f"处理弹幕等级分类完成，处理后弹幕数量: {len(processed_danmu_list)}")

                # 更新弹幕缓存
                async with session["danmu_lock"]:
                    session["danmu_cache"] = session["danmu_service"].update_danmu_cache(session["danmu_cache"], processed_danmu_list)
                    updated_cache_size = len(session["danmu_cache"])

                logger.info(f"弹幕处理完成，已缓存 {updated_cache_size} 条弹幕")
            except Exception as e:
                logger.error(f"会话{req.session_id}后台处理弹幕互动异常: {traceback.print_exc()}")

        # 添加后台任务
        background_tasks.add_task(process_danmu_background)

        # 立即返回，不等待处理完成
        return {"session_id": req.session_id, "status": "processing", "message": "弹幕处理已开始"}
    except Exception as e:
        logger.error(f"会话{req.session_id}处理弹幕互动异常: {traceback.print_exc()}")
        return {"error": str(e)}


@app.post("/switch_voice_role", summary="切换到某个声音角色")
async def switch_voice_role(req: SwitchVoiceRoleRequest):
    session = SESSIONS.get(req.session_id)
    if not session:
        return {"error": "会话不存在"}
    try:
        logger.info(f"会话: {req.session_id}开始执行音色切换，voice_id={req.voice_id}, with_transition={req.with_transition}")
        if req.with_transition:
            await session["tts"].switch_voice_with_transition(voice_id=req.voice_id, profile_index=None)
        else:
            session["tts"].switch_voice(req.voice_id)
        logger.info(f"会话: {req.session_id}完成voice_id={req.voice_id}的音色切换")
    except Exception as e:
        logger.error(f"音色切换接口执行异常，error：{traceback.print_exc()}")
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

    # §四.2 Bug-6：取消任务后必须 await，否则资源（DashScope ws、缓冲区等）释放不及时。
    tasks_to_cancel = []
    main_task = session.get("task")
    if main_task:
        main_task.cancel()
        tasks_to_cancel.append(main_task)
    danmu_task = session.get("danmu_task")
    if danmu_task:
        danmu_task.cancel()
        tasks_to_cancel.append(danmu_task)
    if tasks_to_cancel:
        # return_exceptions=True 吸收 CancelledError，避免被 FastAPI 包装成 500
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    try:
        session["tts"].close()
    except Exception as e:
        logger.error(f"会话{req.session_id} TTS 关闭异常: {traceback.print_exc()}")

    # 关闭音频 WS 客户端
    for ws in list(AUDIO_CLIENTS.pop(req.session_id, set())):
        try:
            await ws.close()
        except Exception:
            pass
    logger.info(f"会话{req.session_id}已停止并清理")
    return {"session_id": req.session_id, "status": "stopped"}


@app.post("/force_stop_session", summary="强制停止指定会话（关播失败时兜底）")
async def force_stop_session(req: StopSessionRequest):
    """强制停止 — 取消所有任务不等待，忽略所有错误，关闭音频 WS"""
    session = SESSIONS.pop(req.session_id, None)
    if not session:
        return {"session_id": req.session_id, "status": "not_found"}

    for key in ("task", "danmu_task"):
        t = session.get(key)
        if t:
            t.cancel()
    try:
        session["tts"].close()
    except Exception:
        pass
    for ws in list(AUDIO_CLIENTS.pop(req.session_id, set())):
        try:
            await ws.close()
        except Exception:
            pass
    logger.info(f"会话{req.session_id}已强制停止")
    return {"session_id": req.session_id, "status": "force_stopped"}


@app.post("/switch_voice_profile", summary="按 profile 索引切换音色")
async def switch_voice_profile(req: SwitchVoiceProfileRequest):
    session = SESSIONS.get(req.session_id)
    if not session:
        return {"error": "会话不存在"}
    try:
        logger.info(f"会话{req.session_id}切换 profile 索引: {req.profile_index}, with_transition={req.with_transition}")
        if req.with_transition:
            await session["tts"].switch_voice_with_transition(voice_id=None, profile_index=req.profile_index)
        else:
            session["tts"].switch_voice_by_profile(req.profile_index)
    except Exception as e:
        logger.error(f"切换 profile 失败: {traceback.print_exc()}")
        return {"error": "切换失败"}
    return {"session_id": req.session_id, "status": "switching", "profile_index": req.profile_index}


@app.post("/update_llm_config", summary="更新直播间配置")
async def update_config(req: UpdateConfigRequest):
    """
    更新直播间配置接口
    当后端配置数据库更新后，通过此接口触发配置刷新
    """
    session = SESSIONS.get(req.session_id)
    if not session:
        return {"error": "会话不存在"}

    try:
        room_config = await resolve_room_llm_config(req.room_id)
        apply_dashscope_from_room_config(room_config)

        logger.info(f"为会话{req.session_id}更新配置（脱敏）: {json.dumps(redact_room_config_for_log(room_config), indent=4, ensure_ascii=False)}")
        session["llm"].update_config(room_config)
        session["tts"].update_config(room_config)
        session["danmu_service"].update_config(room_config)

        logger.info(f"会话{req.session_id}配置更新成功")
        return {
            "session_id": req.session_id,
            "status": "success",
            "config": redact_room_config_for_log(room_config),
        }
    except Exception as e:
        logger.error(f"更新配置失败: {traceback.print_exc()}")
        return {"error": str(e), "status": "failed"}


@app.get("/rag_status", summary="查询RAG向量库状态")
async def rag_status():
    """查询RAG向量库状态"""
    try:
        status = get_vector_store_status()
        return {"status": "success", **status}
    except Exception as e:
        logger.error(f"查询RAG状态失败: {traceback.print_exc()}")
        return {"error": str(e), "status": "failed"}


@app.post("/rebuild_rag_index", summary="重建RAG向量库")
async def rebuild_rag_index(force: bool = True):
    """
    重建RAG向量库
    - force=True: 强制重建（删除旧库，重新从文档解析入库）
    - force=False: 仅在向量库为空时构建
    """
    try:
        # §十二：先从 Spring 拉最新 cfg_rag；失败自动降级到 YAML
        await reload_rag_config_async()
        reset_rag_service()
        reset_embedding_model()
        reset_reranker_model()
        rag_service = get_rag_service(force_rebuild=force)
        doc_count = get_document_count()
        global RAG_WARMED
        RAG_WARMED = True
        logger.info(f"RAG向量库重建完成，文档数量: {doc_count}")
        return {"status": "success", "document_count": doc_count}
    except Exception as e:
        logger.error(f"重建RAG向量库失败: {traceback.print_exc()}")
        return {"error": str(e), "status": "failed"}


@app.post("/clear_rag_index", summary="清空RAG向量库")
async def clear_rag_index():
    """清空RAG向量库"""
    try:
        clear_vector_store()
        reset_rag_service()
        reset_decider()
        global RAG_WARMED
        RAG_WARMED = False
        logger.info("RAG向量库已清空")
        return {"status": "success", "message": "向量库已清空"}
    except Exception as e:
        logger.error(f"清空RAG向量库失败: {traceback.print_exc()}")
        return {"error": str(e), "status": "failed"}


@app.get("/rag_search", summary="RAG检索测试")
async def rag_search(q: str, top_k: int = 3):
    """RAG检索测试接口"""
    try:
        if not q:
            return {"error": "请提供查询参数 q"}
        should_use = should_use_rag(q)
        answers = retrieve_with_answers(q) if should_use else []
        return {
            "status": "success",
            "question": q,
            "trigger_rag": should_use,
            "answers": answers[:top_k]
        }
    except Exception as e:
        logger.error(f"RAG检索失败: {traceback.print_exc()}")
        return {"error": str(e), "status": "failed"}


@app.post("/rag/upload_qa", summary="[Deprecated] 上传 QA 文本并可选触发重建", deprecated=True)
async def rag_upload_qa(
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    rebuild: bool = Form(True),
):
    """@deprecated §十二.7 改为 Pull 模型 —— Python 通过 GET /api/knowledge/qa-export 主动拉取，
    不再接受 Java 主动推送。保留 2 个版本兼容旧调用方，之后删除。

    新链路：调用方请改用 POST /reload_rag_config?rebuild=true[&room_id=X]。
    """
    logger.warning("/rag/upload_qa 已弃用（§十二.7）；请改用 /reload_rag_config?rebuild=true&room_id=X")
    try:
        rag_cfg = config.get("rag") or {}
        docs_path = rag_cfg.get("docs_path", "docs/organized_Q&A.txt")
        abs_path = docs_path if os.path.isabs(docs_path) else os.path.join(os.getcwd(), docs_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        if file is not None:
            data = await file.read()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("utf-8", errors="replace")
        elif content is not None:
            text = content
        else:
            return {"status": "failed", "error": "content 或 file 必须提供其一"}

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info(f"QA 文档已写入 {abs_path}，长度 {len(text)} 字符")

        if rebuild:
            await reload_rag_config_async()
            reset_rag_service()
            rag_service = get_rag_service(force_rebuild=True)
            doc_count = get_document_count()
            global RAG_WARMED
            RAG_WARMED = True
            return {"status": "success", "path": abs_path, "bytes": len(text), "document_count": doc_count, "deprecated": True}
        return {"status": "success", "path": abs_path, "bytes": len(text), "deprecated": True}
    except Exception as e:
        logger.error(f"上传 QA 文档失败: {traceback.format_exc()}")
        return {"status": "failed", "error": str(e)}


@app.post("/reload_rag_config", summary="热加载 RAG 配置，可选从 Spring 拉最新 QA 并重建")
async def reload_rag_config_endpoint(
    rebuild: bool = False,
    room_id: Optional[str] = None,
    room_name: Optional[str] = None,
):
    """§十二.7：RAG 配置/数据的统一刷新入口（Pull 模型）。

    - rebuild=False：仅热加载配置，不写文件、不重建向量库。
    - rebuild=True + room_id=None：拉全局 QA → 写 docs/organized_Q&A.txt → 重建向量库。
    - rebuild=True + room_id=X + room_name=Y：拉专属 QA → 写 docs/Y-organized_Q&A.txt → 重建向量库。
    """
    try:
        cfg = await reload_rag_config_async()
        reset_decider()
        reset_rag_service()
        reset_embedding_model()
        reset_reranker_model()
        logger.info(f"RAG 配置已热加载（rebuild={rebuild}, room_id={room_id}, room_name={room_name}）")

        if not rebuild:
            return {"status": "success", "rebuilt": False}

        # 确定目标文件路径
        base_docs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
        if room_id and room_name:
            # 专属知识库 → docs/{room_name}-organized_Q&A.txt
            docs_path = os.path.join(base_docs, f"{room_name}-organized_Q&A.txt")
        else:
            # 全局知识库 → docs/organized_Q&A.txt
            global_path = cfg.get("docs_path") or get_rag_config().get("docs_path")
            docs_path = global_path if global_path else os.path.join(base_docs, "organized_Q&A.txt")

        # Pull QA 文本 → 落盘
        text = await fetch_knowledge_qa_text(room_id)
        os.makedirs(os.path.dirname(docs_path), exist_ok=True)
        with open(docs_path, "w", encoding="utf-8") as f:
            f.write(text or "")
        logger.info(f"QA 文档已写入 {docs_path}，长度 {len(text or '')} 字符（room_id={room_id}）")

        rag_service = get_rag_service(force_rebuild=True)
        doc_count = get_document_count()
        global RAG_WARMED
        RAG_WARMED = True
        return {
            "status": "success",
            "rebuilt": True,
            "path": docs_path,
            "bytes": len(text or ""),
            "document_count": doc_count,
        }
    except Exception as e:
        logger.error(f"热加载/重建 RAG 失败: {traceback.format_exc()}")
        return {"status": "failed", "error": str(e)}


@app.get("/rag_decider_test", summary="RAG触发判断测试")
async def rag_decider_test(q: str):
    """测试RAG触发判断"""
    try:
        decider = get_rag_decider()
        should_use = should_use_rag(q)
        reason = decider.get_match_reason(q)
        return {
            "status": "success",
            "question": q,
            "trigger_rag": should_use,
            "reason": reason
        }
    except Exception as e:
        logger.error(f"RAG触发判断测试失败: {traceback.print_exc()}")
        return {"error": str(e), "status": "failed"}


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

        g = await fetch_global_llm_settings()
        apply_dashscope_from_room_config(merge_global_llm_into_room_config({}, g))

        # 调用语音克隆功能
        voice_id = create_voice(config["tts"]["model_name"], "myvoice", req.audio_url)
        logger.info(f"语音克隆请求提交成功，voice_id: {voice_id}")

        # 轮询查询音色状态
        await asyncio.to_thread(poll_voice_status, voice_id)
        logger.info(f"语音克隆完成，voice_id: {voice_id}")

        return {"voice_id": voice_id, "status": "success"}
    except Exception as e:
        logger.error(f"语音克隆失败: {traceback.print_exc()}")
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

        g = await fetch_global_llm_settings()
        apply_dashscope_from_room_config(merge_global_llm_into_room_config({}, g))

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
                logger.error(f"上传到OSS失败: {traceback.print_exc()}")
                # 上传失败时保留本地文件并返回路径
                result["audio_path"] = os.path.abspath(output_file)
        else:
            raise ValueError("save_mode参数错误，必须为'local'或'upload'")

        return result
    except Exception as e:
        logger.error(f"出现异常: {traceback.print_exc()}")
        return {"error": str(e), "status": "failed"}


if __name__ == "__main__":
    uvicorn.run(
        app="main:app",
        host=config["server"]["host"],
        port=config["server"]["port"],
        log_level=config["server"]["log_level"],
        reload=False
    )
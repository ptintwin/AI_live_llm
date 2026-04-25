# -*- coding: utf-8 -*-
"""从 Spring Boot 拉取已合并的"有效配置"（§八.4.3 SSoT）。

历史回退链（本模块中的 merge_global_llm_into_room_config / fetch_global_llm_settings）
已被 Java 端 EffectiveConfigService 一次性合并取代；这里只保留兼容包装以便
旧调用点平滑迁移。

LAN 部署：管理端与 LLM 服务在内网受信链路上，所有 GET 直连，不再使用预共享 token。
"""
import httpx
from yaml import safe_load

from utils.logger import logger

with open("./config/config.yaml", "r", encoding="utf-8") as f:
    _cfg = safe_load(f)

SPRING_BASE_URL = _cfg["spring_boot"]["base_url"]


async def fetch_effective_config(room_id: str) -> dict:
    """GET /api/rooms/{id}/effective-config，返回 {"config": {...}, "meta": {...}}。

    失败返回空 dict。调用方应容错使用 .get("config", {}) 等。
    """
    url = f"{SPRING_BASE_URL}/api/rooms/{room_id}/effective-config"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            body = resp.json()
            return (body.get("data") or {}) if isinstance(body, dict) else {}
    except Exception as e:
        logger.warning(f"拉取 effective-config 失败（room={room_id}）: {e}")
        return {}


async def resolve_room_llm_config(room_id: str) -> dict:
    """返回合并后的 LLM 运行配置（原 RoomLlmConfigDTO 形状）。

    Spring 端 EffectiveConfigService 已完成：
      - DashScope 凭据合并
      - LLM / TTS / Prompt / 直播参数 / RAG 按 "room > global > default" 合并
      - ttsProfiles 的 voiceId 已解析为 DashScope 原始 ID，rate/pitch 信任 JSON

    所以本函数**不再做任何兜底合并**；Python 只做消费，不再拥有二次合并逻辑。
    """
    effective = await fetch_effective_config(room_id)
    cfg = effective.get("config") or {}
    if not cfg:
        logger.warning(f"room={room_id} effective config 为空，调用方应使用本地默认兜底")
    return cfg


# ─────────────────────────────────────────────────────────────
# 向后兼容：旧调用点可能直接 import 这两个符号；保留薄包装以免破坏
# ─────────────────────────────────────────────────────────────

async def fetch_room_llm_config_raw(room_id: str) -> dict:
    """@deprecated 请改用 fetch_effective_config / resolve_room_llm_config。"""
    return await resolve_room_llm_config(room_id)


async def fetch_global_llm_settings() -> dict:
    """拉取 Spring 系统设置里的「大模型/百炼」全局配置（未脱敏）。

    说明：
    - 早期版本中本函数被标注为 deprecated 并直接返回 {}，导致旧调用点（如 /voice_clone）
      在没有 room_id 的场景下无法拿到 dashscopeApiKey，只能依赖环境变量。
    - 目前为了保证“所有 key 和配置都读取系统设置”，这里改为直连 Spring 兼容接口：
      GET /api/system-settings/llm（返回 dashscopeApiKey、region、baseWs/baseHttp、模型名、温度等）。

    返回形状：尽量返回 Spring 响应体中的 data（若存在），否则返回 body 本身；失败返回 {}。
    """
    url = f"{SPRING_BASE_URL}/api/system-settings/llm"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            body = resp.json()
    except Exception as e:
        logger.warning(f"拉取 /api/system-settings/llm 失败：{e}")
        return {}

    if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict):
        return body["data"]
    if isinstance(body, dict):
        return body
    return {}


# ─────────────────────────────────────────────────────────────
# §十二：RAG 配置与知识库数据的标准 Pull 接口
# ─────────────────────────────────────────────────────────────

# Spring camelCase → Python snake_case 映射（§十二.3）
_RAG_FIELD_MAP = {
    "enabled": "enabled",
    "embeddingType": "embedding_type",
    "embeddingModelPath": "embedding_model_path",
    "chromaDir": "vector_db_path",          # Python 内部仍用历史名 vector_db_path
    "collectionName": "collection_name",
    "topK": "retrieve_k",                   # Python 历史命名
    "similarityThreshold": "similarity_threshold",
    "triggerMode": "trigger_mode",
    "ruleKeywords": "rule_keywords",
    "enabledCategories": "enabled_categories",
    "useAdvancedDecision": "use_advanced_decision",
    # §十二.3 新字段（原仅存于 YAML）
    "docsPath": "docs_path",
    "rerankerModelPath": "reranker_model_path",
    "enableReranker": "enable_reranker",
    "rerankTopN": "rerank_top_n",
    "semanticThreshold": "semantic_threshold",
}


async def fetch_rag_config() -> dict:
    """从 Spring `/api/config/rag` 拉取 RAG 配置（已由 Spring 返回脱敏后的明文值）。

    返回值按 Python snake_case 字段命名（见 _RAG_FIELD_MAP）。
    仅保留 Spring 端明确返回的键，**缺失键不填默认**——由调用方的合并链决定兜底。
    调用失败或响应为空 → 返回 {}。
    """
    url = f"{SPRING_BASE_URL}/api/config/rag"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            body = resp.json()
    except Exception as e:
        logger.warning(f"拉取 /api/config/rag 失败：{e}")
        return {}

    if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict):
        payload = body["data"]
    elif isinstance(body, dict):
        payload = body
    else:
        return {}

    out: dict = {}
    for camel, snake in _RAG_FIELD_MAP.items():
        if camel in payload and payload[camel] is not None:
            out[snake] = payload[camel]
    # 规则关键词在 Spring 里可能是 jsonb 字符串，统一成 list
    kw = out.get("rule_keywords")
    if isinstance(kw, str):
        try:
            import json as _json
            parsed = _json.loads(kw)
            if isinstance(parsed, list):
                out["rule_keywords"] = parsed
        except Exception:
            pass
    ec = out.get("enabled_categories")
    if isinstance(ec, str):
        try:
            import json as _json
            parsed = _json.loads(ec)
            if isinstance(parsed, list):
                out["enabled_categories"] = parsed
        except Exception:
            pass
    return out


async def fetch_knowledge_qa_text(room_id: str | None = None) -> str:
    """§十二.7：从 Spring 拉取 knowledge 表 QA 纯文本（Pull 模型的标准入口）。

    Spring 端接口：GET /api/knowledge/qa-export?roomId=X（text/plain，LAN 内直连）
    格式：`【问】：xx【答 1】：yy【答 2】：zz`，Python document_processor 可直接解析。

    失败返回空字符串；调用方需兜底（例如保留旧的 docs/organized_Q&A.txt）。
    """
    params = {}
    if room_id is not None and str(room_id).strip() != "":
        params["roomId"] = str(room_id)
    url = f"{SPRING_BASE_URL}/api/knowledge/qa-export"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.text or ""
    except Exception as e:
        logger.warning(f"拉取 /api/knowledge/qa-export 失败（room={room_id}）：{e}")
        return ""

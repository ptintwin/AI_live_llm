# -*- coding: utf-8 -*-
"""从 Spring Boot 拉取 LLM / 系统设置，供 Python 服务使用。"""
import httpx
from yaml import safe_load

from utils.dashscope_runtime import merge_global_llm_into_room_config
from utils.logger import logger

import os

with open("./config/config.yaml", "r", encoding="utf-8") as f:
    _cfg = safe_load(f)

SPRING_BASE_URL = os.getenv("SPRING_BOOT_URL") or _cfg["spring_boot"]["base_url"]


async def fetch_room_llm_config_raw(room_id: str) -> dict:
    """GET /api/rooms/{id}/llm-config，失败返回空 dict。"""
    url = f"{SPRING_BASE_URL}/api/rooms/{room_id}/llm-config"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            body = resp.json()
            return (body.get("data") or {}) if isinstance(body, dict) else {}
    except Exception as e:
        logger.warning(f"拉取直播间 LLM 配置失败，将尝试系统设置或本地默认：{e}")
        return {}


async def fetch_global_llm_settings() -> dict:
    """GET /api/system-settings/llm（系统设置中的 DashScope 等）。"""
    url = f"{SPRING_BASE_URL}/api/system-settings/llm"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            body = resp.json()
            return (body.get("data") or {}) if isinstance(body, dict) else {}
    except Exception as e:
        logger.warning(f"拉取系统 LLM 设置失败：{e}")
        return {}


async def resolve_room_llm_config(room_id: str) -> dict:
    """合并直播间配置与系统设置，保证 DashScope 凭据可用（与 Java buildLlmConfig 一致优先使用库中全局 key）。"""
    room = await fetch_room_llm_config_raw(room_id)
    if (room.get("dashscopeApiKey") or "").strip():
        return room
    global_cfg = await fetch_global_llm_settings()
    return merge_global_llm_into_room_config(room, global_cfg)

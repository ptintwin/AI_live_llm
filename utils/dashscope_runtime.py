# -*- coding: utf-8 -*-
"""DashScope 运行时凭据：优先 Spring 系统设置（合并后的 room_config），其次环境变量 DASHSCOPE_API_KEY。"""
import os
from typing import Any, Mapping, Optional

import dashscope

DEFAULT_WS = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
DEFAULT_HTTP = "https://dashscope.aliyuncs.com/api/v1"


def apply_dashscope_from_room_config(room_config: Optional[Mapping[str, Any]]) -> None:
    """根据直播间/系统配置字典设置全局 dashscope 凭据与 API 基址。"""
    rc = dict(room_config or {})
    key = (rc.get("dashscopeApiKey") or "").strip() or os.getenv("DASHSCOPE_API_KEY", "").strip()
    if key:
        dashscope.api_key = key
    ws = (rc.get("dashscopeBaseWebsocketApiUrl") or "").strip()
    http = (rc.get("dashscopeBaseHttpApiUrl") or "").strip()
    dashscope.base_websocket_api_url = ws or DEFAULT_WS
    dashscope.base_http_api_url = http or DEFAULT_HTTP


def merge_global_llm_into_room_config(
    room_config: Optional[Mapping[str, Any]],
    global_settings: Optional[Mapping[str, Any]],
) -> dict:
    """当房间接口未返回或缺少 DashScope 凭据时，用系统设置 /api/system-settings/llm 补全。"""
    rc = dict(room_config or {})
    g = dict(global_settings or {})
    if not (rc.get("dashscopeApiKey") or "").strip():
        k = g.get("dashscopeApiKey")
        if k:
            rc["dashscopeApiKey"] = k
    for field in ("dashscopeRegion", "dashscopeBaseWebsocketApiUrl", "dashscopeBaseHttpApiUrl"):
        if not (rc.get(field) or "").strip():
            gv = g.get(field)
            if gv:
                rc[field] = gv
    # 房间接口失败时，用全局模型名、温度等兜底（字段名与 RoomLlmConfigDTO 对齐）
    if not rc.get("modelName") and g.get("llmModelName"):
        rc["modelName"] = g["llmModelName"]
    if rc.get("temperature") is None and g.get("temperature") is not None:
        rc["temperature"] = g["temperature"]
    return rc


def redact_room_config_for_log(room_config: Optional[Mapping[str, Any]]) -> dict:
    if not room_config:
        return {}
    out = dict(room_config)
    if out.get("dashscopeApiKey"):
        out["dashscopeApiKey"] = "***"
    return out

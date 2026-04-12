# -*- coding: utf-8 -*-
"""
数据模型定义
"""
from pydantic import BaseModel, Field
from typing import Optional


class DanmuItem(BaseModel):
    username: str = Field(..., description="用户名")
    content: str = Field(..., description="弹幕内容")
    type: str = Field(..., description="弹幕类型")
    danmu_time: str = Field(..., description="弹幕时间，格式为YYYY-MM-DD HH:MM:SS")
    level: Optional[str] = Field(None, description="弹幕等级：mandatory（必播）、important（重要）、normal（一般）")


class StartStreamRequest(BaseModel):
    room_id: str = Field(..., description="直播间ID")
    background: str = Field("", description="当前直播间专属系统提示词")


class LiveDanmuRequest(BaseModel):
    session_id: str = Field(..., description="直播间唯一会话ID")
    danmu_list: list[DanmuItem] = Field(default_factory=list, description="最近n秒内的观众弹幕内容列表")


class SwitchVoiceRoleRequest(BaseModel):
    session_id: str = Field(..., description="直播间唯一会话ID")
    voice_id: str = Field(..., description="音色id")


class StopSessionRequest(BaseModel):
    session_id: str = Field(..., description="直播间唯一会话ID")


class VoiceCloneRequest(BaseModel):
    audio_url: str = Field(..., description="阿里云OSS的音频URL")


class TTSRequest(BaseModel):
    voice_id: str = Field(..., description="语音模型ID")
    speech_rate: float = Field(1.0, description="语音语速，默认1.0")
    pitch_rate: float = Field(1.0, description="语音音高，默认1.0")
    instruction: Optional[str] = Field(None, description="语音模型指令提示词")
    text: Optional[str] = Field(None, description="要合成语音的文本")
    save_mode: str = Field("local", description="合成文件的保存模式，'local'表示本地存储，upload表示上传到OSS")


class DanmuLevelRequest(BaseModel):
    content: str = Field(..., description="弹幕内容")
    type: str = Field(..., description="弹幕类型")

# -*- coding: utf-8 -*-
"""
通义千问流式文本生成服务
满足：临时缓存、历史记录限制、段落流式生成、自然中断、循环续讲
"""
import re
import random
import asyncio
import time
from http import HTTPStatus
from typing import AsyncGenerator, Any
# from dashscope import Generation
from dashscope.aigc.generation import AioGeneration
from yaml import safe_load
from config.prompts import SYSTEM_PROMPT, CURRENT_LIVE_ROOM_PROMPT, CONTINUE_PROMPT, INTERACT_PROMPT, DANMU_LEVEL_PROMPT
from utils.logger import logger
from core.rag import get_rag_service, get_rag_config

# 加载配置
with open("./config/config.yaml", "r", encoding="utf-8") as f:
    config = safe_load(f)


class LLMLiveService:
    """LLM实时服务类，负责管理流式文本生成和互动响应"""

    def __init__(self, session_id: str, room_config: dict = None):
        """初始化LLM服务

        Args:
            session_id: 会话ID，用于日志跟踪
            room_config: 直播间 LLM 配置（来自数据库），缺省时回退到 config.yaml 和 prompts.py 默认值
        """
        rc = room_config or {}
        self.session_id = session_id
        self.history = []
        self.loop_interrupt_flag = False
        self.generation_type = None
        self.cycle_count = 0
        self.user_focus_cycle = 0

        # 运行时参数：房间配置优先，回退 config.yaml
        self.model_name = rc.get("modelName") or config["llm"]["model_name"]
        self.temperature = float(rc.get("temperature") or config["llm"]["temperature"])
        self.max_history = int(rc.get("maxHistory") or config["llm"]["max_history"])
        self.max_cycle_focus = int(rc.get("maxCycleFocus") or config["live"]["max_cycle_focus"])

        # Prompt 模板：房间配置优先，回退 prompts.py 默认值
        system_prompt    = rc.get("systemPrompt")    or SYSTEM_PROMPT
        live_background  = rc.get("liveBackground")  or CURRENT_LIVE_ROOM_PROMPT
        self.continue_prompt     = rc.get("continuePrompt")    or CONTINUE_PROMPT
        self.interact_prompt     = rc.get("interactPrompt")    or INTERACT_PROMPT
        self.danmu_level_prompt  = rc.get("danmuLevelPrompt")  or DANMU_LEVEL_PROMPT

        self.fixed_prefix_history = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_prompt
                    },
                    {
                        "type": "text",
                        "text": f"【当前直播间背景信息】{live_background}",
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
            }
        ]

        rag_config = get_rag_config()
        self.rag_enabled = rag_config.get("enabled", True)
        self.rag_service = None
        if self.rag_enabled:
            self.rag_service = get_rag_service()

    def _trim_history(self):
        """裁剪历史：仅保留最近指定次数的assistant对话及其相关的其他角色对话"""
        assistant_indices = [i for i, m in enumerate(self.history) if m["role"] == "assistant"]
        if len(assistant_indices) > self.max_history:
            start_idx = assistant_indices[-self.max_history]
            # 保存原始历史记录的副本，用于获取起始索引之前的消息
            original_history = self.history.copy()
            self.history = self.history[start_idx:]

            # 检查是否需要保留起始索引之前的最后一条非assistant消息（如果存在）
            if start_idx > 0 and self.history[0]["role"] != "assistant":
                pass  # 已经包含在切片中了
            elif start_idx > 0:
                # 如果起始索引之前有非assistant消息，需要保留
                # 使用原始历史记录来获取起始索引之前的消息
                prev_msgs = original_history[:start_idx]
                non_assistant_prev = [m for m in prev_msgs if m["role"] != "assistant"]
                if non_assistant_prev:
                    # 保留最后一条非assistant消息
                    self.history = [non_assistant_prev[-1]] + self.history

    async def _stream_llm_response(self, prompt: str, is_interact: bool, danmu_summary: str = "") -> AsyncGenerator[
        str, Any]:
        """通用LLM流式响应处理

        Args:
            prompt: 提示文本
            is_interact: 是否为互动模式
            danmu_summary: 互动模式下，观众弹幕交互摘要，用于上下文提示

        Yields:
            流式生成的文本片段，确保以完整句子为单位
        """

        self.generation_type = 'live_danmu' if is_interact else 'live_loop'
        logger.info(f"会话{self.session_id}开始生成{self.generation_type}类型文本")

        # 构建用于发送给LLM的消息列表
        messages = self.fixed_prefix_history + self.history.copy()

        # 对于最新的互动消息，保留完整的INTERACT_PROMPT用于LLM
        if prompt:
            _his_content = danmu_summary if is_interact else prompt
            self.history.append({"role": "user", "content": _his_content})
            messages.append({"role": "user", "content": prompt})
        self._trim_history()

        full_content = ""
        assistant_content = ""  # 保存完整的assistant响应
        chunk_count = 0  # 手动计数，替代 enumerate
        try:
            # 调用通义千问（流式+临时缓存+增量输出）
            logger.info(f"开始调用LLM：模型={self.model_name}，消息长度={len(messages)}")
            logger.info(f"self.history: {self.history}")
            responses = await AioGeneration.call(
                model=self.model_name,
                messages=messages,
                result_format="message",
                stream=True,
                incremental_output=True,
                temperature=self.temperature
            )
            logger.info("LLM调用成功，开始接收流式响应")

            # 修正：使用 async for 直接迭代，手动计数
            async for resp in responses:
                chunk_count += 1
                if hasattr(resp, 'status_code') and resp.status_code != HTTPStatus.OK:
                    # 处理错误情况
                    error_msg = f"LLM请求失败: code={resp.code}, message={resp.message}"
                    logger.error(error_msg)
                    error_response = f"抱歉，{'回复您的问题' if is_interact else '讲解'}暂时遇到问题：{resp.message}"
                    yield error_response
                    break

                if hasattr(resp, 'output') and resp.output and hasattr(resp.output, 'choices') and resp.output.choices:
                    chunk = resp.output.choices[0].message.content
                    if chunk:
                        full_content += chunk

                        # 确保以完整句子为单位返回，以句号、感叹号或问号结尾
                        sentence_endings = ["。", "！", "？", "~"]
                        has_ending = any(ending in chunk for ending in sentence_endings)

                        if has_ending:
                            for ending in sentence_endings:
                                if ending in full_content:
                                    last_end_idx = full_content.rfind(ending)
                                    if last_end_idx != -1:
                                        # logger.info(f"full_content: {full_content}")
                                        complete_sentence = full_content[:last_end_idx + 1].strip()
                                        logger.info(
                                            f"当前“{'弹幕互动' if is_interact else '循环播报'}”模式complete_sentence: {complete_sentence}")

                                        if is_interact:
                                            tag_match = re.match(r'^【([^】]+)】', full_content)
                                            if tag_match:
                                                _level = tag_match.group(0)
                                                assistant_content += complete_sentence[len(_level):].strip()
                                                self._prev_level = _level
                                            else:
                                                if hasattr(self, '_prev_level') and self._prev_level:
                                                    complete_sentence = self._prev_level + complete_sentence
                                                else:
                                                    raise ValueError(
                                                        f"弹幕互动模式下，句子{complete_sentence}未包含有效标签")
                                        else:
                                            assistant_content += complete_sentence

                                        if not is_interact and self.loop_interrupt_flag:
                                            logger.info(
                                                f"会话{self.session_id}检测到循环生成中断标志，当前句子结束后停止生成")
                                            yield complete_sentence
                                            full_content = ""
                                            break
                                        else:
                                            yield complete_sentence
                                            full_content = full_content[last_end_idx + 1:].strip()

                # 检查是否是最后一个包
                if hasattr(resp, 'output') and resp.output and hasattr(resp.output, 'choices') and resp.output.choices:
                    if resp.output.choices[0].finish_reason == "stop":
                        # 记录使用量
                        if hasattr(resp, 'usage') and resp.usage:
                            logger.info(
                                f"会话{self.session_id}LLM{'互动' if is_interact else ''}使用量：输入{resp.usage.input_tokens}，"
                                f"输出{resp.usage.output_tokens}，总计{resp.usage.total_tokens}"
                            )
                        logger.info(f"LLM{'互动' if is_interact else ''}流式响应结束")
                        break

            # 处理剩余的累积内容
            if full_content:
                assistant_content += full_content
                yield full_content

            # 保存完整的assistant响应到历史记录
            if assistant_content:
                self.history.append({"role": "assistant", "content": assistant_content})
                logger.info(f"保存assistant响应到历史记录，长度: {len(assistant_content)}")

        except Exception as e:
            import traceback
            logger.error(f"错误栈：{traceback.format_exc()}")
            error_response = f"抱歉，{'回复您的问题' if is_interact else '讲解'}暂时遇到问题，请稍后再试。"
            yield error_response
        finally:
            self.generation_type = None

    async def generate_stream_paragraph(self) -> AsyncGenerator[str, Any]:
        """流式生成段落讲解内容（无互动时循环调用）"""
        if self.loop_interrupt_flag:
            return

        self.cycle_count += 1
        # 构建续讲Prompt
        prompt = ""
        max_focus_cycle = self.max_cycle_focus
        if self.user_focus_cycle > max_focus_cycle:
            # 超过了最大“照顾观众交互”轮次，置为0表示不再“照顾交互”
            self.user_focus_cycle = 0
        if self.cycle_count > 1:
            prompt = self.continue_prompt
            if self.user_focus_cycle > 0:
                # 计算照顾度：值越小表示越近期，照顾度越高
                focus_level = max_focus_cycle - self.user_focus_cycle + 1
                if focus_level == max_focus_cycle:
                    # 最近一次交互，最高照顾度
                    prompt += "，【重要提醒】请优先重点结合最近的观众弹幕交互内容"
                elif focus_level == max_focus_cycle - 1:
                    # 较近的交互，较高照顾度
                    prompt += "，【重要提醒】请适当结合近期观众弹幕交互内容"
                else:
                    # 较早的交互，较低照顾度
                    prompt += "，【重要提醒】请参考早期观众弹幕交互内容"
        async for chunk in self._stream_llm_response(prompt, False):
            yield chunk
        if self.user_focus_cycle > 0:
            # 值越大表示最新“观众交互”轮次越远，照顾程度越低
            self.user_focus_cycle += 1

    async def handle_interact(self, danmu_list: list) -> AsyncGenerator[str, Any]:
        """处理观众互动弹幕（自然中断后调用）"""
        danmu_summary = ""
        rag_context = ""
        rag_hit_count = 0

        for danmu in danmu_list:
            username = getattr(danmu, 'username', '观众')
            content = getattr(danmu, 'content', '')
            danmu_type = getattr(danmu, 'type', '')

            if self.rag_enabled and self.rag_service and danmu_type == 'question':
                if self.rag_service.should_use_rag(content):
                    answers = self.rag_service.get_answer(content)
                    if answers:
                        chosen_answer = random.choice(answers) if len(answers) > 1 else answers[0]
                        rag_context += f"【问题】：{content}\n"
                        for i, ans in enumerate(answers, 1):
                            if len(answers) > 1:
                                rag_context += f"【参考回复{i}】：{ans}\n"
                            else:
                                rag_context += f"【参考回复】：{ans}\n"
                        rag_context += "\n"
                        rag_hit_count += 1
                        answer_preview = chosen_answer[:30] + "..." if len(chosen_answer) > 30 else chosen_answer
                        logger.info(f"RAG命中: 问题='{content}', pick答案='{answer_preview}', 共{len(answers)}个候选")

            prefix_map = {'question': "【互动问题类】", 'gift': "【礼物灯牌类】", 'enter': "【进入直播间】",
                          'follow': "【关注或点赞类】"}
            suffix_pmt = f"观众'{username}'：{content}\n" if danmu_type == 'question' else f"观众'{username}'{content}\n"
            danmu_summary += (prefix_map[danmu_type] + suffix_pmt)

        if rag_hit_count > 0:
            logger.info(f"RAG本次命中 {rag_hit_count} 个问题，已添加到prompt中")

        prompt = self.interact_prompt.format(danmu_summary=danmu_summary, rag_context=rag_context)

        full_response = ""
        async for chunk in self._stream_llm_response(prompt, True, danmu_summary=danmu_summary):
            full_response += chunk
            yield chunk

        self.user_focus_cycle = 1

    def set_loop_interrupt(self, flag: bool):
        """设置live_loop的中断标志"""
        self.loop_interrupt_flag = flag
        logger.info(f"会话{self.session_id}live_loop中断标志：{flag}， 当前状态：{'已中断' if flag else '恢复讲解'}")

    def set_generation_type(self, _type: str):
        """设置当前生成任务类型"""
        self.generation_type = _type

    def update_config(self, room_config: dict):
        """更新服务配置

        Args:
            room_config: 新的直播间配置
        """
        rc = room_config or {}
        # 更新运行时参数：房间配置优先，回退 config.yaml
        self.model_name = rc.get("modelName") or config["llm"]["model_name"]
        self.temperature = float(rc.get("temperature") or config["llm"]["temperature"])
        self.max_history = int(rc.get("maxHistory") or config["llm"]["max_history"])
        self.max_cycle_focus = int(rc.get("maxCycleFocus") or config["live"]["max_cycle_focus"])

        # 更新Prompt模板：房间配置优先，回退 prompts.py 默认值
        system_prompt    = rc.get("systemPrompt")    or SYSTEM_PROMPT
        live_background  = rc.get("liveBackground")  or CURRENT_LIVE_ROOM_PROMPT
        self.continue_prompt     = rc.get("continuePrompt")    or CONTINUE_PROMPT
        self.interact_prompt     = rc.get("interactPrompt")    or INTERACT_PROMPT
        self.danmu_level_prompt  = rc.get("danmuLevelPrompt")  or DANMU_LEVEL_PROMPT

        # 更新固定前缀历史
        self.fixed_prefix_history = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_prompt
                    },
                    {
                        "type": "text",
                        "text": f"【当前直播间背景信息】{live_background}",
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
            }
        ]
        logger.info(f"LLMLiveService配置已更新")

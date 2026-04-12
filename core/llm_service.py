# -*- coding: utf-8 -*-
"""
通义千问流式文本生成服务
满足：临时缓存、历史记录限制、段落流式生成、自然中断、循环续讲
"""
import os
import re
import asyncio
import time
from http import HTTPStatus
from typing import AsyncGenerator, Any
import dashscope
from botocore.hooks import first_non_none_response
# from dashscope import Generation
from dashscope.aigc.generation import AioGeneration
from yaml import safe_load
from config.prompts import SYSTEM_PROMPT, CURRENT_LIVE_ROOM_PROMPT, CONTINUE_PROMPT, INTERACT_PROMPT
from utils.logger import logger

# 加载配置
with open("./config/config.yaml", "r", encoding="utf-8") as f:
    config = safe_load(f)

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
if not dashscope.api_key:
    raise ValueError("DASHSCOPE_API_KEY环境变量未设置")


class LLMLiveService:
    """LLM实时服务类，负责管理流式文本生成和互动响应"""

    def __init__(self, session_id: str, background: str = None):
        """初始化LLM服务

        Args:
            session_id: 会话ID，用于日志跟踪
            background: 背景信息，用于系统提示
        """
        self.history = []
        self.session_id = session_id
        self.background = background if background else CURRENT_LIVE_ROOM_PROMPT
        self.max_history = config["llm"]["max_history"]
        self.loop_interrupt_flag = False  # 控制live_loop中断或继续的标志
        self.generation_type = None
        self.cycle_count = 0  # 循环次数
        self.user_focus_cycle = 0  # 循环生成中已"关注近期观众弹幕交互"的循环次数
        self.fixed_prefix_history = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"}
                    },
                    {
                        "type": "text",
                        "text": f"【当前直播间背景信息】{self.background}"
                    }
                ]
            }
        ]

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

    async def _stream_llm_response(self, prompt: str, is_interact: bool = False) -> AsyncGenerator[str, Any]:
        """通用LLM流式响应处理

        Args:
            prompt: 提示文本
            is_interact: 是否为互动模式

        Yields:
            流式生成的文本片段，确保以完整句子为单位
        """
        # if self.generation_type is not None:
        #     logger.info(f"会话{self.session_id}当前正在生成{self.generation_type}类型文本，已中断")

        self.generation_type = 'live_danmu' if is_interact else 'live_loop'
        logger.info(f"会话{self.session_id}开始生成{self.generation_type}类型文本")

        if prompt:
            self.history.append({"role": "user", "content": prompt})
        self._trim_history()

        full_content = ""
        assistant_content = ""  # 保存完整的assistant响应
        chunk_count = 0  # 手动计数，替代 enumerate
        try:
            # 调用通义千问（流式+临时缓存+增量输出）
            logger.info(f"开始调用LLM：模型={config['llm']['model_name']}，self.history长度={len(self.history)}")
            # logger.info(f"self.history: {self.history}")
            # 如果最近的
            responses = await AioGeneration.call(
                model=config["llm"]["model_name"],
                messages=self.fixed_prefix_history + self.history,
                result_format="message",  # 消息格式输出
                stream=True,
                incremental_output=True,  # 关键：设置为True以获取增量输出，性能更佳
                temperature=config["llm"]["temperature"]
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
                        sentence_endings = ["。", "！", "？"]
                        has_ending = any(ending in chunk for ending in sentence_endings)

                        if has_ending:
                            for ending in sentence_endings:
                                if ending in full_content:
                                    last_end_idx = full_content.rfind(ending)
                                    if last_end_idx != -1:
                                        logger.info(f"full_content: {full_content}")
                                        complete_sentence = full_content[:last_end_idx + 1].strip()

                                        if is_interact:
                                            # 检查是否有起始的"【xxx】"格式标签
                                            tag_match = re.match(r'^【([^】]+)】', complete_sentence)

                                            # 如果没有标签且存在上一句的标签，则添加
                                            if not tag_match and hasattr(self, 'previous_tag') and self.previous_tag:
                                                complete_sentence = f"{self.previous_tag}{complete_sentence}"

                                            # 更新上一句的标签
                                            if tag_match:
                                                self.previous_tag = tag_match.group(0)

                                        logger.info(f"complete_sentence: {complete_sentence}")
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
        max_focus_cycle = config["live"]["max_cycle_focus"]
        if self.user_focus_cycle > max_focus_cycle:
            # 超过了最大“照顾观众交互”轮次，置为0表示不再“照顾交互”
            self.user_focus_cycle = 0
        if self.cycle_count > 1:
            prompt = CONTINUE_PROMPT
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
        async for chunk in self._stream_llm_response(prompt, is_interact=False):
            yield chunk
        if self.user_focus_cycle > 0:
            # 值越大表示最新“观众交互”轮次越远，照顾程度越低
            self.user_focus_cycle += 1

    async def handle_interact(self, danmu_list: list) -> AsyncGenerator[str, Any]:
        """处理观众互动弹幕（自然中断后调用）"""
        # 构建弹幕摘要
        danmu_summary = ""

        # 构建弹幕摘要，按时间顺序从新到旧处理
        for danmu in danmu_list:
            username = getattr(danmu, 'username', '观众')
            content = getattr(danmu, 'content', '')
            danmu_type = getattr(danmu, 'type', '')
            level = getattr(danmu, 'level', 'normal')

            # 根据等级添加前缀
            level_prefix = "" if level == "normal" else f"【{level}】"
            prefix_map = {'question': "【互动问题类】", 'gift': "【礼物灯牌类】", 'enter': "【进入直播间】",
                          'follow': "【关注或点赞类】"}
            suffix_pmt = f"观众‘{username}’：{content}\n" if danmu_type == 'question' else f"观众‘{username}’{content}\n"
            danmu_summary += (level_prefix + prefix_map[danmu_type] + suffix_pmt)

        prompt = INTERACT_PROMPT.format(danmu_summary=danmu_summary)
        async for chunk in self._stream_llm_response(prompt, is_interact=True):
            yield chunk
        self.user_focus_cycle = 1

    def set_loop_interrupt(self, flag: bool):
        """设置live_loop的中断标志"""
        self.loop_interrupt_flag = flag
        logger.info(f"会话{self.session_id}live_loop中断标志：{flag}， 当前状态：{'已中断' if flag else '恢复讲解'}")

    def set_generation_type(self, _type: str):
        """设置当前生成任务类型"""
        self.generation_type = _type

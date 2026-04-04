# -*- coding: utf-8 -*-
"""
通义千问流式文本生成服务
满足：临时缓存、历史记录限制、段落流式生成、自然中断、循环续讲
"""
import os
import asyncio
from http import HTTPStatus
from typing import AsyncGenerator, Any
import dashscope
from dashscope import Generation
from yaml import safe_load
from config.prompts import SYSTEM_PROMPT, CONTINUE_PROMPT, INTERACT_PROMPT, WELCOME_PROMPT
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
        self.session_id = session_id
        self.background = background or config["live"]["default_background"]
        self.max_history = config["llm"]["max_history"]
        self.interrupt_flag = False  # 自然中断标志
        self.history = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT + self.background,
                        "cache_control": {"type": "ephemeral"}  # 阿里百炼文档的上下文缓存策略
                    }
                ]
            }
        ]
        self.user_focus = []  # 观众关注点（前3次循环纳入）
        self.cycle_count = 0  # 循环次数

    def _trim_history(self):
        """裁剪历史：仅保留最近指定次数的assistant对话"""
        assistant_msgs = [m for m in self.history if m["role"] == "assistant"]
        if len(assistant_msgs) > self.max_history:
            keep_assistant = assistant_msgs[-self.max_history:]
            # 重建历史（system + 用户消息 + 保留的assistant）
            new_history = [self.history[0]]
            for msg in self.history[1:]:
                if msg["role"] != "assistant" or msg in keep_assistant:
                    new_history.append(msg)
            self.history = new_history

    async def _stream_llm_response(self, prompt: str, is_interact: bool = False) -> AsyncGenerator[str, Any]:
        """通用LLM流式响应处理

        Args:
            prompt: 提示文本
            is_interact: 是否为互动模式

        Yields:
            流式生成的文本片段，确保以完整句子为单位
        """
        self.history.append({"role": "user", "content": prompt})
        self._trim_history()

        full_content = ""
        try:
            # 调用通义千问（流式+临时缓存+增量输出）
            logger.info(f"开始调用LLM：模型={config['llm']['model_name']}，历史记录长度={len(self.history)}")

            # 打印历史记录的最后几条，用于调试
            for i, msg in enumerate(self.history[-3:]):
                logger.debug(f"历史记录[{i}]: {msg['role']}: {msg['content'][:50]}...")

            responses = Generation.call(
                model=config["llm"]["model_name"],
                messages=self.history,
                result_format="message",  # 消息格式输出
                stream=True,
                incremental_output=True,  # 关键：设置为True以获取增量输出，性能更佳
                temperature=config["llm"]["temperature"]
            )

            logger.info("LLM调用成功，开始接收流式响应")
            for i, resp in enumerate(responses):
                if hasattr(resp, 'status_code') and resp.status_code != HTTPStatus.OK:
                    # 处理错误情况
                    error_msg = f"LLM请求失败: code={resp.code}, message={resp.message}"
                    logger.error(error_msg)
                    error_response = f"抱歉，{'回复您的问题' if is_interact else '讲解'}暂时遇到问题：{resp.message}"
                    yield error_response
                    break

                if hasattr(resp, 'output') and resp.output and hasattr(resp.output, 'choices') and resp.output.choices:
                    chunk = resp.output.choices[0].message.content
                    full_content += chunk

                    # 实时返回段落（按句子切割，自然断点）
                    # 确保以完整句子为单位返回，以句号、感叹号或问号结尾
                    sentence_endings = ["。", "！", "？"]
                    if any(p in chunk for p in sentence_endings):
                        # 检查是否有完整句子
                        for ending in sentence_endings:
                            if ending in full_content:
                                # 找到最后一个句子结束符
                                last_end_idx = full_content.rfind(ending)
                                if last_end_idx != -1:
                                    # 提取完整句子
                                    complete_sentence = full_content[:last_end_idx + 1]
                                    # 检查中断标志，在句子结束时检查
                                    if not is_interact and self.interrupt_flag:
                                        logger.info(f"会话{self.session_id}检测到中断标志，在句子结束后停止讲解")
                                        yield complete_sentence
                                        full_content = ""
                                        break
                                    else:
                                        yield complete_sentence
                                        full_content = full_content[last_end_idx + 1:].strip()
                    # 定期检查中断标志，确保能够及时响应
                    elif not is_interact and i % 3 == 0:  # 每3个响应检查一次
                        if self.interrupt_flag:
                            logger.info(f"会话{self.session_id}检测到中断标志，等待句子结束后停止讲解")
                            # 继续累积内容，直到遇到标点

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

            if full_content:
                self.history.append({"role": "assistant", "content": full_content})
                yield full_content
        except Exception as e:
            import traceback
            logger.error(f"错误栈：{traceback.format_exc()}")
            error_response = f"抱歉，{'回复您的问题' if is_interact else '讲解'}暂时遇到问题，请稍后再试。"
            yield error_response

    async def generate_stream_paragraph(self) -> AsyncGenerator[str, Any]:
        """流式生成段落讲解内容（无互动时循环调用）"""
        if self.interrupt_flag:
            return

        self.cycle_count += 1
        # 构建续讲Prompt（前3次循环纳入观众关注点）
        prompt = CONTINUE_PROMPT
        if self.cycle_count <= config["live"]["max_cycle_focus"] and self.user_focus:
            prompt += f"，结合观众关注点：{'、'.join(self.user_focus)}"

        async for chunk in self._stream_llm_response(prompt, is_interact=False):
            yield chunk

    async def handle_interact(self, question: str) -> AsyncGenerator[str, Any]:
        """处理观众互动弹幕（自然中断后调用）"""
        self.user_focus.append(question)
        prompt = INTERACT_PROMPT.format(question=question)

        async for chunk in self._stream_llm_response(prompt, is_interact=True):
            yield chunk

    async def handle_welcome(self, username: str) -> str:
        """处理观众进场欢迎"""
        return WELCOME_PROMPT.format(username=username)

    def set_interrupt(self, flag: bool):
        """设置自然中断标志"""
        self.interrupt_flag = flag
        logger.info(f"会话{self.session_id}中断标志：{flag}， 当前状态：{'已中断' if flag else '恢复讲解'}")
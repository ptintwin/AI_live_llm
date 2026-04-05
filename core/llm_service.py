# -*- coding: utf-8 -*-
"""
通义千问流式文本生成服务
满足：临时缓存、历史记录限制、段落流式生成、自然中断、循环续讲
"""
import os
import asyncio
import time
from http import HTTPStatus
from typing import AsyncGenerator, Any
import dashscope
# from dashscope import Generation
from dashscope.aigc.generation import AioGeneration
from yaml import safe_load
from core.danmu_service import DanmuService
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
        self.session_id = session_id
        self.background = background if background else CURRENT_LIVE_ROOM_PROMPT
        self.max_history = config["llm"]["max_history"]
        self.interrupt_flag = False  # 自然中断标志
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
                        "text": f"【当前直播间专属背景信息】{self.background}"
                    }
                ]
            }
        ]
        self.history = []
        self.cycle_count = 0  # 循环次数
        self.user_focus_cycle = 0  # 循环生成中已"关注近期观众弹幕交互"的循环次数

    def _trim_history(self):
        """裁剪历史：仅保留最近指定次数的assistant对话及其相关的其他角色对话"""
        assistant_indices = [i for i, m in enumerate(self.history) if m["role"] == "assistant"]
        if len(assistant_indices) > self.max_history:
            start_idx = assistant_indices[-self.max_history]
            self.history = self.history[start_idx:]

            # 检查是否需要保留起始索引之前的最后一条非assistant消息（如果存在）
            if start_idx > 0 and self.history[0]["role"] != "assistant":
                pass  # 已经包含在切片中了
            elif start_idx > 0:
                # 如果起始索引之前有非assistant消息，需要保留
                prev_msgs = self.history[:start_idx]
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
        if prompt:
            self.history.append({"role": "user", "content": prompt})
        self._trim_history()

        full_content = ""
        assistant_content = ""  # 保存完整的assistant响应
        chunk_count = 0  # 手动计数，替代 enumerate
        try:
            # 调用通义千问（流式+临时缓存+增量输出）
            logger.info(f"开始调用LLM：模型={config['llm']['model_name']}，self.history长度={len(self.history)}")
            logger.info(f"self.history: {self.history}")
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
                    if chunk:  # 检查 chunk 不为空
                        full_content += chunk
                        assistant_content += chunk  # 累积完整的assistant响应

                        # 实时返回段落（按句子切割，自然断点）
                        # 确保以完整句子为单位返回，以句号、感叹号或问号结尾
                        sentence_endings = ["。", "！", "？"]

                        # 检查是否有句子结束符
                        has_ending = any(ending in chunk for ending in sentence_endings)

                        if has_ending:
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
                        elif not is_interact and chunk_count % 3 == 0:  # 使用 chunk_count 替代 i
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

            # 处理剩余的累积内容
            if full_content:
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

    async def generate_stream_paragraph(self) -> AsyncGenerator[str, Any]:
        """流式生成段落讲解内容（无互动时循环调用）"""
        if self.interrupt_flag:
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

        # 提取所有question类型的弹幕内容
        question_contents = []
        question_indices = []

        for i, danmu in enumerate(danmu_list):
            danmu_type = getattr(danmu, 'type', '')
            if danmu_type == 'question':
                content = getattr(danmu, 'content', '')
                question_contents.append(content)
                question_indices.append(i)

        # 批量识别question类型弹幕的等级
        if question_contents:
            start_time = time.time()
            levels = await DanmuService.identify_levels(question_contents)

            # 将识别结果赋值给对应的弹幕
            for i, level in zip(question_indices, levels):
                setattr(danmu_list[i], 'level', level)
            logger.info(f"识别弹幕等级耗时: {time.time() - start_time:.2f}秒")

        # 构建弹幕摘要
        for danmu in danmu_list:
            username = getattr(danmu, 'username', '观众')
            content = getattr(danmu, 'content', '')
            danmu_type = getattr(danmu, 'type', '')
            level = getattr(danmu, 'level', '')

            prefix_map = {'question': f"【互动问题类-{level}】", 'gift': "【礼物类】", 'enter': "【进入直播间】",
                          'follow': "【关注或点赞类】"}
            suffix_pmt = f"观众‘{username}’：{content}\n" if danmu_type == 'question' else f"观众‘{username}’{content}\n"
            danmu_summary += (prefix_map[danmu_type] + suffix_pmt)

        prompt = INTERACT_PROMPT.format(danmu_summary=danmu_summary)
        async for chunk in self._stream_llm_response(prompt, is_interact=True):
            yield chunk
        self.user_focus_cycle = 1

    def set_interrupt(self, flag: bool):
        """设置自然中断标志"""
        self.interrupt_flag = flag
        logger.info(f"会话{self.session_id}中断标志：{flag}， 当前状态：{'已中断' if flag else '恢复讲解'}")